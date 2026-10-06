import asyncio
import uuid

from fastapi import APIRouter, status
from pydantic import BaseModel
from sqlalchemy import text

from .database import SessionLocal
from .worker import run_job

router = APIRouter(tags=["jobs"])


class JobRequest(BaseModel):
    script: str


@router.post("/jobs", status_code=status.HTTP_201_CREATED)
async def create_job(request: JobRequest) -> dict[str, str]:
    job_id = str(uuid.uuid4())

    async with SessionLocal() as session:
        await session.execute(
            text(
                """
                INSERT INTO jobs (id, status, created_at)
                VALUES (:job_id, 'queued', NOW())
                """
            ),
            {"job_id": job_id},
        )
        await session.commit()

    asyncio.create_task(run_job(job_id, request.script))
    return {"id": job_id, "status": "running"}
