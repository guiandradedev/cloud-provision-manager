import asyncio
from os import mkdir
from pathlib import Path
from ..utils.commands import run_command
from pydantic import BaseModel

from sqlalchemy import text

SYSTEMD_DIR = Path("/etc/systemd/system")
ENVIRONMENTS_DIR = Path("/var/lib/provision-manager/environments")
CGROUPS_DIR = Path("/sys/fs/cgroup")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER_PATH = PROJECT_ROOT / "app" / "services" / "start-env.sh"

async def start_env(env_name: str) -> int:
    proc = await asyncio.create_subprocess_exec(
        "bash",
        str(LAUNCHER_PATH),
        env_name,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    # Dá tempo para o launcher falhar durante a inicialização.
    try:
        _, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=2,
        )
    except asyncio.TimeoutError:
        # O processo continua vivo: o ambiente foi iniciado
        # ou ainda está inicializando.
        return proc.pid

    if proc.returncode != 0:
        raise RuntimeError(
            stderr.decode(errors="replace")
        )

    return proc.pid


class CreateEnvironment(BaseModel):
    env_id: str
    name: str
    cpu_quota: int
    cpu_weight: int
    mem_limit: int

async def create_env(env: CreateEnvironment) -> int:
    # A validação de limites pode ser mantida aqui
    if env.cpu_quota <= 0 or env.cpu_quota > 100:
        raise ValueError("CPU quota must be between 1 and 100")
    if env.mem_limit <= 0 or env.mem_limit > 16384:
        raise ValueError("Memory limit must be between 1 and 16384 MB")
    if not env.name:
        raise ValueError("Environment name must not be empty")
        
    # O registo na base de dados (em routes.py) e a validação são suficientes.
    # O Cgroup será materializado durante a execução do Job.
    return 0