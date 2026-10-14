import asyncio
from unittest import result
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .database import SessionLocal
from .services.create_job import run_job
from .services.create_env import create_env, CreateEnvironment

router = APIRouter(tags=["jobs"])
UPLOADS_DIR = Path("uploads")


class CreateEnvironmentRequest(BaseModel):
    name: str
    cpu_quota: int
    mem_limit: int
    cpu_weight: int


class JobLogResponse(BaseModel):
    source: str
    content: str
    created_at: datetime


@router.post("/environment", status_code=status.HTTP_201_CREATED)
async def create_environment(request: CreateEnvironmentRequest) -> dict[str, str]:
    if not (1 <= request.cpu_quota <= 100):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="CPU quota must be between 1 and 100",
        )
    if not (1 <= request.mem_limit <= 16384):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Memory limit must be between 1 and 16384 MB",
        )
    if not (1 <= request.cpu_weight <= 1000):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="CPU weight must be between 1 and 1000",
        )
    
    env_id = str(uuid.uuid4())
    
    async with SessionLocal() as session:
        await session.execute(
            text(
                """
                INSERT INTO environments (id, name, cpu_quota, mem_limit, cpu_weight, created_at)
                VALUES (:env_id, :name, :cpu_quota, :mem_limit, :cpu_weight, NOW())
                """
            ),
            {"env_id": env_id, "name": request.name, "cpu_quota": request.cpu_quota, "mem_limit": request.mem_limit, "cpu_weight": request.cpu_weight},
        )
        await session.commit()

    env_data = CreateEnvironment(
        name=request.name,
        env_id=env_id,
        cpu_quota=request.cpu_quota, 
        mem_limit=request.mem_limit,
        cpu_weight=request.cpu_weight,
    )
    
    try:
        result = await create_env(env_data)
    except (RuntimeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not start environment: {error}",
        ) from error

    if result != 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create environment",
        )

    return {"id": env_id, "name": request.name}


@router.post("/jobs", status_code=status.HTTP_201_CREATED)
async def create_job(
    env_id: str = Form(...),
    script: UploadFile = File(...),
) -> dict[str, str]:
    job_id = str(uuid.uuid4())

    async with SessionLocal() as session:
        environment = await session.execute(
            text("SELECT name FROM environments WHERE id = :env_id"),
            {"env_id": env_id},
        )
        env_name = environment.scalar_one_or_none()
        if not env_name:
            raise HTTPException(status_code=404, detail="Environment not found")

    if not script.filename or not script.filename.endswith(".sh"):
        raise HTTPException(status_code=400, detail="Invalid script file type")

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    file_path = UPLOADS_DIR / f"{job_id}-{Path(script.filename).name}"
    contents = await script.read()

    try:
        script_content = contents.decode("utf-8")
    except UnicodeDecodeError as error:
        raise HTTPException(status_code=400, detail="Script must be a valid UTF-8 text file") from error

    file_path.write_bytes(contents)

    try:
        async with SessionLocal.begin() as session:
            await session.execute(
                text("INSERT INTO jobs (id, status, env_id, created_at) VALUES (:job_id, 'queued', :env_id, NOW())"),
                {"job_id": job_id, "env_id": env_id},
            )
            await session.execute(
                text("INSERT INTO files (id, job_id, name, path, created_at) VALUES (:file_id, :job_id, :name, :path, NOW())"),
                {"file_id": str(uuid.uuid4()), "job_id": job_id, "name": script.filename, "path": str(file_path)},
            )
    except SQLAlchemyError as error:
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Could not create the job") from error

    # CORREÇÃO: Reconstrói a nomenclatura exata do Cgroup (igual ao create_env.py) e passa para o Job
    cgroup_name = env_name.replace(" ", "_").lower() + f"_{env_id[:8]}"
    asyncio.create_task(run_job(job_id, script_content, cgroup_name))

    return {"id": job_id, "status": "running"}

@router.get("/jobs/{job_id}", status_code=status.HTTP_200_OK)
async def get_job_status(job_id: str) -> dict[str, str]:
    async with SessionLocal() as session:
        result = await session.execute(
            text("SELECT status FROM jobs WHERE id = :job_id"),
            {"job_id": job_id},
        )
        job_status = result.scalar_one_or_none()

    if job_status is None:
        raise HTTPException(status_code=404, detail="Job not found")

    return {"id": job_id, "status": job_status}

@router.get("/jobs/{job_id}/output", status_code=status.HTTP_200_OK)
async def get_job_output(
    job_id: str,
) -> dict[str, str | list[JobLogResponse]]:
    async with SessionLocal() as session:
        job_result = await session.execute(
            text("SELECT id FROM jobs WHERE id = :job_id"),
            {"job_id": job_id},
        )
        if job_result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Job not found")

        logs_result = await session.execute(
            text(
                """
                SELECT stream, message, created_at
                FROM job_logs
                WHERE job_id = :job_id
                ORDER BY id
                """
            ),
            {"job_id": job_id},
        )
        logs = logs_result.mappings().all()

    output = [
        JobLogResponse(
            source=log["stream"],
            content=log["message"],
            created_at=log["created_at"],
        )
        for log in logs
    ]
    return {"id": job_id, "output": output}

@router.get("/jobs/{job_id}/script", status_code=status.HTTP_200_OK)
async def get_job_script(job_id: str) -> dict[str, str]:
    async with SessionLocal() as session:
        result = await session.execute(
            text("SELECT path FROM files WHERE job_id = :job_id"),
            {"job_id": job_id},
        )        
        job_script = result.scalar_one_or_none()

    if job_script is None:
        raise HTTPException(status_code=404, detail="Job not found")

    # Retornar o conteúdo do script em vez do caminho do arquivo
    try:
        with open(job_script, "r", encoding="utf-8") as f:
            job_script = f.read()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Script file not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading script file: {str(e)}")

    return {"id": job_id, "script": job_script}

@router.get("/jobs/{job_id}/status", status_code=status.HTTP_200_OK)
async def get_job_status(job_id: str) -> dict[str, str]:
    async with SessionLocal() as session:
        result = await session.execute(
            text("SELECT status FROM jobs WHERE id = :job_id"),
            {"job_id": job_id},
        )
        job_status = result.scalar_one_or_none()

    if job_status is None:
        raise HTTPException(status_code=404, detail="Job not found")

    return {"id": job_id, "status": job_status}


@router.get("/jobs", status_code=status.HTTP_200_OK)
async def get_jobs() -> list[dict[str, str]]:
    async with SessionLocal() as session:
        result = await session.execute(text("SELECT id, status FROM jobs"))
        jobs = result.fetchall()

    return [{"id": job.id, "status": job.status} for job in jobs]

@router.get("/environment", status_code=status.HTTP_200_OK)
async def get_environments() -> list[dict[str, str]]:
    async with SessionLocal() as session:
        result = await session.execute(text("SELECT id, name FROM environments"))
        environments = result.fetchall()

    return [{"id": env.id, "name": env.name} for env in environments]

@router.get("/environment/{env_id}", status_code=status.HTTP_200_OK)
async def get_environment(env_id: str) -> dict[str, str]:
    async with SessionLocal() as session:
        result = await session.execute(
            text("SELECT id, name FROM environments WHERE id = :env_id"),
            {"env_id": env_id},
        )
        environment = result.mappings().one_or_none()

    if environment is None:
        raise HTTPException(status_code=404, detail="Environment not found")

    return {"id": environment["id"], "name": environment["name"]}

@router.get("/environment/{env_id}/jobs", status_code=status.HTTP_200_OK)
async def get_environment_jobs(env_id: str) -> list[dict[str, str]]:
    async with SessionLocal() as session:
        result = await session.execute(
            text(
                """
                SELECT id, status
                FROM jobs
                WHERE env_id = :env_id
                """
            ),
            {"env_id": env_id},
        )
        jobs = result.mappings().all()

    return [{"id": job["id"], "status": job["status"]} for job in jobs]