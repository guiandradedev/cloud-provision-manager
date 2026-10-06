import asyncio
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .database import SessionLocal
from .worker import run_job

router = APIRouter(tags=["jobs"])
UPLOADS_DIR = Path("uploads")


class CreateEnviromentRequest(BaseModel):
    name: str


@router.post("/environment", status_code=status.HTTP_201_CREATED)
async def create_environment(request: CreateEnviromentRequest) -> dict[str, str]:
    env_id = str(uuid.uuid4())

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
