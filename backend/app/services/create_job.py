import asyncio
import shlex
from sqlalchemy import text
from ..database import SessionLocal


async def save_log(job_id: str, stream: str, message: str) -> None:
    async with SessionLocal() as session:
        await session.execute(
            text(
                """
                INSERT INTO job_logs (job_id, stream, message, created_at)
                VALUES (:job_id, :stream, :message, NOW())
                """
            ),
            {"job_id": job_id, "stream": stream, "message": message},
        )
        await session.commit()


async def read_stream(stream, job_id: str, stream_name: str) -> None:
    while line := await stream.readline():
        message = line.decode().rstrip("\n")
        print(f"[{job_id}] {message}")
        await save_log(job_id, stream_name, message)


async def run_job(job_id: str, script: str, env_cgroup_name: str) -> int:
    cgroup_path = f"/sys/fs/cgroup/{env_cgroup_name}"
    safe_script = shlex.quote(script)
    
    # CORREÇÃO: Escreve o PID ($$) na pasta do Cgroup do ambiente associado ANTES do unshare
    wrapper_cmd = (
        f"echo $$ > {cgroup_path}/cgroup.procs && "
        f"exec /usr/bin/unshare --mount --pid --fork --ipc --mount-proc bash -c {safe_script}"
    )

    process = await asyncio.create_subprocess_exec(
        "bash",
        "-c",
        wrapper_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    
    print(f"Job {job_id} iniciado no Cgroup '{env_cgroup_name}' (PID={process.pid})")
    await _mark_job_as_running(job_id, process.pid)

    await asyncio.gather(
        read_stream(process.stdout, job_id, "stdout"),
        read_stream(process.stderr, job_id, "stderr"),
    )

    exit_code = await process.wait()
    await _mark_job_as_finished(job_id, exit_code)
    
    print(f"Job {job_id} terminou (exit={exit_code})")
    return exit_code


async def _mark_job_as_running(job_id: str, pid: int | None) -> None:
    async with SessionLocal() as session:
        await session.execute(
            text(
                """
                UPDATE jobs
                SET status = 'running', pid = :pid, started_at = NOW()
                WHERE id = :job_id
                """
            ),
            {"job_id": job_id, "pid": pid},
        )
        await session.commit()


async def _mark_job_as_finished(job_id: str, exit_code: int) -> None:
    final_status = "completed" if exit_code == 0 else "failed"

    async with SessionLocal() as session:
        await session.execute(
            text(
                """
                UPDATE jobs
                SET status = :status, exit_code = :exit_code, finished_at = NOW()
                WHERE id = :job_id
                """
            ),
            {
                "job_id": job_id,
                "status": final_status,
                "exit_code": exit_code,
            },
        )
        await session.commit()
