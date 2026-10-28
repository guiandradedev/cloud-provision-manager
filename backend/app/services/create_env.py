import asyncio
from pydantic import BaseModel

from .runtime import (
    CGROUPS_DIR,
    EnvironmentRuntime,
    cleanup_environment_cgroup,
    configure_environment_cgroup,
    environment_cgroup_name,
    environment_cgroup_path,
    find_environment_anchor,
)

class CreateEnvironment(BaseModel):
    env_id: str
    name: str
    cpu_quota: int
    cpu_weight: int
    mem_limit: int

async def create_env(env: CreateEnvironment) -> EnvironmentRuntime:
    cgroup_name = environment_cgroup_name(env.name, env.env_id)
    cgroup_path = environment_cgroup_path(cgroup_name)
    cgroup_existed = cgroup_path.exists()

    try:
        (CGROUPS_DIR / "cgroup.subtree_control").write_text("+cpu +memory +io")
    except Exception:
        pass

    cgroup_path.mkdir(parents=True, exist_ok=True)
    configure_environment_cgroup(
        cgroup_path,
        cpu_quota=env.cpu_quota,
        cpu_weight=env.cpu_weight,
        mem_limit=env.mem_limit,
    )

    anchor_pid = find_environment_anchor(cgroup_path)
    if anchor_pid is not None:
        return EnvironmentRuntime(cgroup_name=cgroup_name, anchor_pid=anchor_pid)

    if cgroup_existed:
        await cleanup_environment_cgroup(cgroup_name)
        cgroup_path.mkdir(parents=True, exist_ok=False)
        configure_environment_cgroup(
            cgroup_path,
            cpu_quota=env.cpu_quota,
            cpu_weight=env.cpu_weight,
            mem_limit=env.mem_limit,
        )

    hostname = cgroup_name.replace("_", "-")[:63]
    cmd = (
        f"echo $$ > {cgroup_path}/cgroup.procs && "
        f"exec /usr/bin/unshare --mount --pid --fork --uts --ipc --mount-proc "
        f"/bin/bash -c 'hostname {hostname}; exec sleep infinity'"
    )

    proc = await asyncio.create_subprocess_exec(
        "bash", "-c", cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )

    for _ in range(40):
        await asyncio.sleep(0.05)
        anchor_pid = find_environment_anchor(cgroup_path)
        if anchor_pid is not None:
            return EnvironmentRuntime(cgroup_name=cgroup_name, anchor_pid=anchor_pid)
        if proc.returncode is not None:
            break

    await cleanup_environment_cgroup(cgroup_name)
    raise RuntimeError(
        f"Namespace anchor did not start (exit={proc.returncode})"
    )
