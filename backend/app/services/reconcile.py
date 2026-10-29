from sqlalchemy import text

from ..database import SessionLocal
from .create_env import CreateEnvironment, create_env
from .runtime import cleanup_job_cgroup, environment_cgroup_name


async def reconcile_runtime_state() -> None:
    await _interrupt_unfinished_jobs()
    await _restore_environments()


async def _interrupt_unfinished_jobs() -> None:
    async with SessionLocal() as session:
        result = await session.execute(
            text(
                """
                SELECT j.id, e.id AS env_id, e.name AS env_name,
                       e.cgroup_name AS env_cgroup_name
                FROM jobs j
                INNER JOIN environments e ON e.id = j.env_id
                WHERE j.status IN ('queued', 'running')
                """
            )
        )
        unfinished_jobs = result.mappings().all()

    for job in unfinished_jobs:
        env_cgroup_name = job["env_cgroup_name"] or environment_cgroup_name(
            job["env_name"],
            job["env_id"],
        )
        cleanup_error: str | None = None
        try:
            await cleanup_job_cgroup(env_cgroup_name, job["id"])
        except OSError as error:
            cleanup_error = str(error)

        message = "Execução interrompida durante a reinicialização do backend."
        if cleanup_error:
            message += f" Falha ao limpar o cgroup: {cleanup_error}"

        async with SessionLocal.begin() as session:
            await session.execute(
                text(
                    """
                    UPDATE jobs
                    SET status = 'failed', exit_code = 143, finished_at = NOW()
                    WHERE id = :job_id
                    """
                ),
                {"job_id": job["id"]},
            )
            await session.execute(
                text(
                    """
                    INSERT INTO job_logs (job_id, stream, message, created_at)
                    VALUES (:job_id, 'stderr', :message, NOW())
                    """
                ),
                {"job_id": job["id"], "message": message},
            )


async def _restore_environments() -> None:
    async with SessionLocal() as session:
        result = await session.execute(
            text(
                """
                SELECT id, name, cpu_quota, mem_limit, cpu_weight, io_limit_bps
                FROM environments
                WHERE status != 'terminated'
                """
            )
        )
        environments = result.mappings().all()

    for environment in environments:
        env_data = CreateEnvironment(
            env_id=environment["id"],
            name=environment["name"],
            cpu_quota=environment["cpu_quota"],
            mem_limit=environment["mem_limit"],
            cpu_weight=environment["cpu_weight"],
            io_limit_bps=environment["io_limit_bps"],
        )

        try:
            runtime = await create_env(env_data)
        except Exception as error:
            async with SessionLocal.begin() as session:
                await session.execute(
                    text(
                        """
                        UPDATE environments
                        SET status = 'error', anchor_pid = NULL,
                            error_message = :error_message
                        WHERE id = :env_id
                        """
                    ),
                    {
                        "env_id": environment["id"],
                        "error_message": str(error)[:65535],
                    },
                )
            continue

        async with SessionLocal.begin() as session:
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
                    "env_id": environment["id"],
                    "anchor_pid": runtime.anchor_pid,
                    "cgroup_name": runtime.cgroup_name,
                },
            )
