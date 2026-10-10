import asyncio
from os import mkdir
from pathlib import Path
from ..utils.commands import run_command

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


class CreateEnvironment():
    def __init__(self, env_id: str, name: str, cpu_quota: int, cpu_weight: int, mem_limit: int):
        self.env_id = env_id
        self.name = name
        self.cpu_quota = cpu_quota # %
        self.cpu_weight = cpu_weight # 
        self.mem_limit = mem_limit # MB

async def create_env(env: CreateEnvironment) -> int:
    if env.cpu_quota <= 0 or env.cpu_quota > 100:
        raise ValueError("CPU quota must be between 1 and 100")

    if env.mem_limit <= 0 or env.mem_limit > 16384:
        raise ValueError("Memory limit must be between 1 and 16384 MB")

    if not env.name:
        raise ValueError("Environment name must not be empty")

    new_env_name = (
        env.name.replace(" ", "_").lower()
        + f"_{env.env_id[:8]}"
    )
    cgroup_path = CGROUPS_DIR / new_env_name

    period = 100_000
    quota = env.cpu_quota * period // 100
    memory_bytes = env.mem_limit * 1024 * 1024

    try:
        # Cria e configura o cgroup.
        await run_command(
            "mkdir", "-p", str(cgroup_path)
        )

        await run_command(
            "bash", "-c",
            'printf "%s %s" "$1" "$2" > "$3"',
            "bash", str(quota), str(period),
            str(cgroup_path / "cpu.max")
        )

        await run_command(
            "bash", "-c",
            'printf "%s" "$1" > "$2"',
            "bash", str(env.cpu_weight),
            str(cgroup_path / "cpu.weight")
        )

        await run_command(
            "bash", "-c",
            'printf "%s" "$1" > "$2"',
            "bash", str(memory_bytes),
            str(cgroup_path / "memory.max")
        )

    except Exception as e:
        print(f"Failed to create environment {new_env_name}: {e}")
        return 1

    start_pid = await start_env(new_env_name)
    print(start_pid)

    return 0