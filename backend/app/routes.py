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
    
class ScriptResponse(BaseModel):
    id: str
    name: str
    job_id: str
    created_at: datetime


class RerunScriptRequest(BaseModel):
    env_id: str | None = None


@router.post("/environment", status_code=status.HTTP_201_CREATED)
async def create_environment(request: CreateEnvironmentRequest) -> dict[str, str]:
    env_id = str(uuid.uuid4())
    
    # 1. DESCOMENTAR A INSERÇÃO NA BASE DE DADOS (obrigatório para o job achar o ambiente)
    async with SessionLocal() as session:
        await session.execute(
            text(
                """
                INSERT INTO environments (id, name, created_at)
                VALUES (:env_id, :name, NOW())
                """
            ),
            {"env_id": env_id, "name": request.name},
        )
        await session.commit()

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

    # CORREÇÃO: Consulta o nome do ambiente correspondente ao ID submetido
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

@router.get("/environment/{env_id}/scripts", status_code=status.HTTP_200_OK)
async def get_environment_scripts(env_id: str) -> list[ScriptResponse]:
    """Lista todos os scripts já enviados e executados em um ambiente específico."""
    async with SessionLocal() as session:
        env_check = await session.execute(
            text("SELECT id FROM environments WHERE id = :env_id"),
            {"env_id": env_id},
        )
        if env_check.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Environment not found")

        result = await session.execute(
            text(
                """
                SELECT f.id, f.name, f.job_id, f.created_at
                FROM files f
                INNER JOIN jobs j ON f.job_id = j.id
                WHERE j.env_id = :env_id
                ORDER BY f.created_at DESC
                """
            ),
            {"env_id": env_id},
        )
        scripts = result.mappings().all()

    return [
        ScriptResponse(
            id=row["id"],
            name=row["name"],
            job_id=row["job_id"],
            created_at=row["created_at"],
        )
        for row in scripts
    ]


@router.post("/scripts/{file_id}/run", status_code=status.HTTP_201_CREATED)
async def rerun_script(
    file_id: str,
    request: RerunScriptRequest | None = None,
) -> dict[str, str]:
    """Reexecuta um script já armazenado criando um novo job."""
    async with SessionLocal() as session:
        result = await session.execute(
            text(
                """
                SELECT f.id, f.name, f.path, j.env_id AS original_env_id
                FROM files f
                INNER JOIN jobs j ON f.job_id = j.id
                WHERE f.id = :file_id
                """
            ),
            {"file_id": file_id},
        )
        script_row = result.mappings().one_or_none()

        if script_row is None:
            raise HTTPException(status_code=404, detail="Script not found")

        target_env_id = (request.env_id if request and request.env_id else script_row["original_env_id"])

        env_result = await session.execute(
            text("SELECT name FROM environments WHERE id = :env_id"),
            {"env_id": target_env_id},
        )
        env_name = env_result.scalar_one_or_none()
        if env_name is None:
            raise HTTPException(status_code=404, detail="Target environment not found")

    file_path = Path(script_row["path"])
    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Stored script file is missing from disk",
        )

    try:
        script_content = file_path.read_text(encoding="utf-8")
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail="Could not read stored script file",
        ) from error

    new_job_id = str(uuid.uuid4())
    try:
        async with SessionLocal.begin() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO jobs (id, status, env_id, created_at)
                    VALUES (:job_id, 'queued', :env_id, NOW())
                    """
                ),
                {"job_id": new_job_id, "env_id": target_env_id},
            )
            await session.execute(
                text(
                    """
                    INSERT INTO files (id, job_id, name, path, created_at)
                    VALUES (:new_file_id, :job_id, :name, :path, NOW())
                    """
                ),
                {
                    "new_file_id": str(uuid.uuid4()),
                    "job_id": new_job_id,
                    "name": script_row["name"],
                    "path": str(file_path),
                },
            )
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=500,
            detail="Could not create the rerun job",
        ) from error

    cgroup_name = f"{env_name.replace(' ', '_').lower()}_{target_env_id[:8]}"
    asyncio.create_task(run_job(new_job_id, script_content, cgroup_name))

    return {"id": new_job_id, "status": "running"}