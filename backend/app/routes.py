import asyncio
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


class JobLogResponse(BaseModel):
    source: str
    content: str
    created_at: datetime


@router.post("/environment", status_code=status.HTTP_201_CREATED)
async def create_environment(request: CreateEnvironmentRequest) -> dict[str, str]:
    env_id = str(uuid.uuid4())

    # async with SessionLocal() as session:
    #     await session.execute(
    #         text(
    #             """
    #             INSERT INTO environments (id, name, created_at)
    #             VALUES (:env_id, :name, NOW())
    #             """
    #         ),
    #         {"env_id": env_id, "name": request.name},
    #     )
    #     await session.commit()

    env_data = CreateEnvironment(
        name=request.name,
        env_id=env_id,
        cpu_quota=50, 
        mem_limit=512,
        cpu_weight=100,
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

    # Valida se o ambiente existe
    async with SessionLocal() as session:
        environment = await session.execute(
            text("SELECT id FROM environments WHERE id = :env_id"),
            {"env_id": env_id},
        )
        if environment.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Environment not found")

    # Valida se o arquivo de script é um arquivo sh
    if not script.filename or not script.filename.endswith(".sh"):
        raise HTTPException(status_code=400, detail="Invalid script file type")

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    file_path = UPLOADS_DIR / f"{job_id}-{Path(script.filename).name}"
    contents = await script.read()
    try:
        script_content = contents.decode("utf-8")
    except UnicodeDecodeError as error:
        raise HTTPException(
            status_code=400,
            detail="Script must be a valid UTF-8 text file",
        ) from error

    file_path.write_bytes(contents)

    try:
        async with SessionLocal.begin() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO jobs (id, status, env_id, created_at)
                    VALUES (:job_id, 'queued', :env_id, NOW())
                    """
                ),
                {"job_id": job_id, "env_id": env_id},
            )
            await session.execute(
                text(
                    """
                    INSERT INTO files (id, job_id, name, path, created_at)
                    VALUES (:file_id, :job_id, :name, :path, NOW())
                    """
                ),
                {
                    "file_id": str(uuid.uuid4()),
                    "job_id": job_id,
                    "name": script.filename,
                    "path": str(file_path),
                },
            )
    except SQLAlchemyError as error:
        file_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=500,
            detail="Could not create the job",
        ) from error

    asyncio.create_task(run_job(job_id, script_content))
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
