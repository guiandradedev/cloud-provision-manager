import asyncio
import shlex
from pathlib import Path
from sqlalchemy import text
from ..database import SessionLocal

CGROUPS_DIR = Path("/sys/fs/cgroup")

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
        message = line.decode(errors="replace").rstrip("\n")
        print(f"[{job_id}] {message}")
        await save_log(job_id, stream_name, message)

def _get_namespace_holder_pid(cgroup_path: Path) -> int:
    """Busca o PID do 'sleep infinity' (PID 1 do namespace) dentro do cgroup."""
    procs_file = cgroup_path / "cgroup.procs"
    if not procs_file.exists():
        raise RuntimeError(f"Cgroup {cgroup_path} não existe.")

    pids = [p.strip() for p in procs_file.read_text().splitlines() if p.strip()]
    if not pids:
        raise RuntimeError("Nenhum processo âncora ativo neste ambiente.")

    # Procura especificamente o processo 'sleep' que detém os namespaces filhos
    for pid in pids:
        try:
            cmdline = Path(f"/proc/{pid}/cmdline").read_text()
            if "sleep" in cmdline:
                return int(pid)
        except Exception:
            continue

    # Fallback: ultimo PID criado no grupo
    return int(pids[-1])

async def run_job(job_id: str, script: str, env_cgroup_name: str) -> int:
    cgroup_path = CGROUPS_DIR / env_cgroup_name
    
    try:
        target_pid = _get_namespace_holder_pid(cgroup_path)
    except Exception as e:
        await save_log(job_id, "stderr", f"Erro de ambiente: {e}")
        await _mark_job_as_finished(job_id, 1)
        return 1

    safe_script = shlex.quote(script)

    # Coloca o processo atual no cgroup
    # Usa nsenter para entrar nos exatos mesmos namespaces do processo ancora (target_pid)
    wrapper_cmd = (
        f"echo $$ > {cgroup_path}/cgroup.procs && "
        f"exec /usr/bin/nsenter -t {target_pid} -m -u -i -p /bin/bash -c {safe_script}"
    )

    process = await asyncio.create_subprocess_exec(
        "bash",
        "-c",
        wrapper_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    print(f"Job {job_id} reutilizando namespace (Target PID={target_pid}, Job PID={process.pid})")
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
            text("UPDATE jobs SET status = 'running', pid = :pid, started_at = NOW() WHERE id = :job_id"),
            {"job_id": job_id, "pid": pid},
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