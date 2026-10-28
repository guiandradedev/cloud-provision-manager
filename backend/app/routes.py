import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .database import SessionLocal
from .services.create_job import schedule_job
from .services.create_env import create_env, CreateEnvironment
from .services.runtime import (
    cleanup_environment_cgroup,
    environment_cgroup_name,
)

router = APIRouter(tags=["jobs"])
UPLOADS_DIR = Path("uploads")


class CreateEnvironmentRequest(BaseModel):
    name: str
    cpu_quota: int
    mem_limit: int
    cpu_weight: int
    io_limit_bps: int = 0


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
    if request.io_limit_bps < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="I/O limit must be zero or a positive number of bytes per second",
        )
    
    env_id = str(uuid.uuid4())
    cgroup_name = environment_cgroup_name(request.name, env_id)

    env_data = CreateEnvironment(
        name=request.name,
        env_id=env_id,
        cpu_quota=request.cpu_quota, 
        mem_limit=request.mem_limit,
        cpu_weight=request.cpu_weight,
        io_limit_bps=request.io_limit_bps,
    )
    
    try:
        async with SessionLocal.begin() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO environments (
                        id, name, cpu_quota, mem_limit, cpu_weight, io_limit_bps,
                        status, cgroup_name, created_at
                    )
                    VALUES (
                        :env_id, :name, :cpu_quota, :mem_limit, :cpu_weight, :io_limit_bps,
                        'pending', :cgroup_name, NOW()
                    )
                    """
                ),
                {
                    "env_id": env_id,
                    "name": request.name,
                    "cpu_quota": request.cpu_quota,
                    "mem_limit": request.mem_limit,
                    "cpu_weight": request.cpu_weight,
                    "io_limit_bps": request.io_limit_bps,
                    "cgroup_name": cgroup_name,
                },
            )

            runtime = await create_env(env_data)
            await session.execute(
                text(
                    """
                    UPDATE environments
                    SET status = 'running', anchor_pid = :anchor_pid,
                        cgroup_name = :cgroup_name, error_message = NULL
                    WHERE id = :env_id
                    """
                ),
                {
                    "env_id": env_id,
                    "anchor_pid": runtime.anchor_pid,
                    "cgroup_name": runtime.cgroup_name,
                },
            )
    except Exception as error:
        try:
            await cleanup_environment_cgroup(cgroup_name)
        except OSError:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not start environment: {error}",
        ) from error

    return {"id": env_id, "name": request.name, "status": "running"}


@router.post("/jobs", status_code=status.HTTP_201_CREATED)
async def create_job(
    env_id: str = Form(...),
    script: UploadFile = File(...),
) -> dict[str, str]:
    job_id = str(uuid.uuid4())

    async with SessionLocal() as session:
        environment = await session.execute(
            text(
                """
                SELECT name, status, cgroup_name
                FROM environments
                WHERE id = :env_id
                """
            ),
            {"env_id": env_id},
        )
        environment_row = environment.mappings().one_or_none()
        if environment_row is None:
            raise HTTPException(status_code=404, detail="Environment not found")
        if environment_row["status"] != "running":
            raise HTTPException(
                status_code=409,
                detail="Environment is not ready to run jobs",
            )

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

    cgroup_name = environment_row["cgroup_name"] or environment_cgroup_name(
        environment_row["name"],
        env_id,
    )
    schedule_job(job_id, script_content, cgroup_name)

    return {"id": job_id, "status": "queued"}

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
        result = await session.execute(
            text("SELECT id, name, status FROM environments")
        )
        environments = result.fetchall()

    return [
        {"id": env.id, "name": env.name, "status": env.status}
        for env in environments
    ]

@router.get("/environment/{env_id}", status_code=status.HTTP_200_OK)
async def get_environment(env_id: str) -> dict[str, str | int | None]:
    async with SessionLocal() as session:
        result = await session.execute(
            text(
                """
                SELECT id, name, status, cpu_quota, mem_limit, cpu_weight,
                       io_limit_bps,
                       anchor_pid, error_message
                FROM environments
                WHERE id = :env_id
                """
            ),
            {"env_id": env_id},
        )
        environment = result.mappings().one_or_none()

    if environment is None:
        raise HTTPException(status_code=404, detail="Environment not found")

    return dict(environment)

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
            text(
                """
                SELECT name, status, cgroup_name
                FROM environments
                WHERE id = :env_id
                """
            ),
            {"env_id": target_env_id},
        )
        env_row = env_result.mappings().one_or_none()
        if env_row is None:
            raise HTTPException(status_code=404, detail="Target environment not found")
        if env_row["status"] != "running":
            raise HTTPException(
                status_code=409,
                detail="Target environment is not ready to run jobs",
            )

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

    cgroup_name = env_row["cgroup_name"] or environment_cgroup_name(
        env_row["name"],
        target_env_id,
    )
    schedule_job(new_job_id, script_content, cgroup_name)

    return {"id": new_job_id, "status": "queued"}
