import asyncio
import os
from pathlib import Path
from pydantic import BaseModel

CGROUPS_DIR = Path("/sys/fs/cgroup")

class CreateEnvironment(BaseModel):
    env_id: str
    name: str
    cpu_quota: int
    cpu_weight: int
    mem_limit: int

async def create_env(env: CreateEnvironment) -> int:
    if not (1 <= env.cpu_quota <= 100):
        raise ValueError("CPU quota must be between 1 and 100")
    if not (1 <= env.mem_limit <= 16384):
        raise ValueError("Memory limit must be between 1 and 16384 MB")

    cgroup_name = f"{env.name.replace(' ', '_').lower()}_{env.env_id[:8]}"
    cgroup_path = CGROUPS_DIR / cgroup_name

    # 1. Garante que os controladores estão ativos na raiz do cgroup v2
    try:
        Path("/sys/fs/cgroup/cgroup.subtree_control").write_text("+cpu +memory +io")
    except Exception:
        pass

    # 2. Cria o diretório do Cgroup do ambiente
    cgroup_path.mkdir(parents=True, exist_ok=True)

    # 3. Escreve os limites diretamente nos arquivos do Kernel
    period = 100_000
    quota = (env.cpu_quota * period) // 100
    memory_bytes = env.mem_limit * 1024 * 1024

    (cgroup_path / "cpu.max").write_text(f"{quota} {period}\n")
    (cgroup_path / "cpu.weight").write_text(f"{env.cpu_weight}\n")
    (cgroup_path / "memory.max").write_text(f"{memory_bytes}\n")

    # 4. Cria o Namespace persistente (processo âncora) dentro do Cgroup
    hostname = cgroup_name.replace("_", "-")[:63]
    cmd = (
        f"echo $$ > {cgroup_path}/cgroup.procs && "
        f"exec /usr/bin/unshare --mount --pid --fork --uts --ipc --mount-proc "
        f"/bin/bash -c 'hostname {hostname}; exec sleep infinity'"
    )

    proc = await asyncio.create_subprocess_exec(
        "bash", "-c", cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE
    )

    # Aguarda 0.3s para verificar se não falhou imediatamente e se o fork ocorreu
    await asyncio.sleep(0.3)
    if proc.returncode is not None and proc.returncode != 0:
        err = (await proc.stderr.read()).decode(errors="replace")
        raise RuntimeError(f"Erro ao criar namespace: {err}")

    return 0