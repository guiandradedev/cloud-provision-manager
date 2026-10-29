import asyncio
import shlex
from sqlalchemy import text
from ..database import SessionLocal
from .runtime import (
    cleanup_job_cgroup,
    environment_cgroup_path,
    find_environment_anchor,
    job_cgroup_name,
    prepare_job_cgroup,
)
from .storage import append_job_output

_job_tasks: dict[str, asyncio.Task[int]] = {}


def schedule_job(job_id: str, script: str, env_cgroup_name: str) -> None:
    task = asyncio.create_task(run_job(job_id, script, env_cgroup_name))
    _job_tasks[job_id] = task
    task.add_done_callback(
        lambda completed_task: _finish_scheduled_job(job_id, completed_task)
    )


def _finish_scheduled_job(job_id: str, task: asyncio.Task[int]) -> None:
    if _job_tasks.get(job_id) is task:
        _job_tasks.pop(job_id, None)
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        print(f"Job task failed unexpectedly: {error}")


async def shutdown_scheduled_jobs() -> None:
    tasks = list(_job_tasks.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def cancel_scheduled_job(job_id: str) -> bool:
    task = _job_tasks.get(job_id)
    if task is None:
        return False

    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    return True


async def save_log(job_id: str, stream: str, message: str) -> None:
    append_job_output(job_id, stream, message)
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
        message = line.decode(errors="replace").rstrip("\n")
        print(f"[{job_id}] {message}")
        await save_log(job_id, stream_name, message)

async def run_job(job_id: str, script: str, env_cgroup_name: str) -> int:
    env_cgroup_path = environment_cgroup_path(env_cgroup_name)
    job_runtime_created = False
    process: asyncio.subprocess.Process | None = None

    try:
        target_pid = find_environment_anchor(env_cgroup_path)
        if target_pid is None:
            raise RuntimeError("Nenhum processo âncora ativo neste ambiente.")

        job_cgroup_path = prepare_job_cgroup(env_cgroup_name, job_id)
        job_runtime_created = True

        safe_script = shlex.quote(script)

        wrapper_cmd = (
            f"echo $$ > {job_cgroup_path}/cgroup.procs && "
            f"exec /usr/bin/nsenter -t {target_pid} -m -u -i -p -n "
            f"/bin/bash -c {safe_script}"
        )

        process = await asyncio.create_subprocess_exec(
            "bash",
            "-c",
            wrapper_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        print(
            f"Job {job_id} reutilizando namespace "
            f"(Target PID={target_pid}, Job PID={process.pid})"
        )
        await _mark_job_as_running(
            job_id,
            process.pid,
            job_cgroup_name(job_id),
        )

        await asyncio.gather(
            read_stream(process.stdout, job_id, "stdout"),
            read_stream(process.stderr, job_id, "stderr"),
        )

        exit_code = await process.wait()
        await _mark_job_as_finished(job_id, exit_code)

        print(f"Job {job_id} terminou (exit={exit_code})")
        return exit_code
    except asyncio.CancelledError:
        await save_log(
            job_id,
            "stderr",
            "Execução interrompida.",
        )
        await _mark_job_as_terminated(job_id)
        raise
    except Exception as error:
        await save_log(job_id, "stderr", f"Erro de execução: {error}")
        await _mark_job_as_finished(job_id, 1)
        return 1
    finally:
        if process is not None and process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        if job_runtime_created:
            try:
                await cleanup_job_cgroup(env_cgroup_name, job_id)
            except OSError as error:
                await save_log(
                    job_id,
                    "stderr",
                    f"Não foi possível limpar o cgroup do job: {error}",
                )
        if process is not None and process.returncode is None:
            await process.wait()

async def _mark_job_as_running(
    job_id: str,
    pid: int | None,
    cgroup_name: str,
) -> None:
    async with SessionLocal() as session:
        await session.execute(
            text(
                """
                UPDATE jobs
                SET status = 'running', pid = :pid,
                    cgroup_name = :cgroup_name, started_at = NOW()
                WHERE id = :job_id
                """
            ),
            {
                "job_id": job_id,
                "pid": pid,
                "cgroup_name": cgroup_name,
            },
        )
        await session.commit()

async def _mark_job_as_finished(job_id: str, exit_code: int) -> None:
    final_status = "completed" if exit_code == 0 else "failed"
    async with SessionLocal() as session:
        await session.execute(
            text("UPDATE jobs SET status = :status, exit_code = :exit_code, finished_at = NOW() WHERE id = :job_id"),
            {"job_id": job_id, "status": final_status, "exit_code": exit_code},
        )
        await session.commit()


async def _mark_job_as_terminated(job_id: str) -> None:
    async with SessionLocal() as session:
        await session.execute(
            text(
                """
                UPDATE jobs
                SET status = 'terminated', exit_code = 143,
                    pid = NULL, finished_at = NOW()
                WHERE id = :job_id
                """
            ),
            {"job_id": job_id},
        )
        await session.commit()
