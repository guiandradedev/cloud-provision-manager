import asyncio
import os
import re
import signal
import unicodedata
from dataclasses import dataclass
from pathlib import Path


CGROUPS_DIR = Path("/sys/fs/cgroup")
_COMPONENT_PATTERN = re.compile(r"[^a-z0-9_-]+")


@dataclass(frozen=True)
class EnvironmentRuntime:
    cgroup_name: str
    anchor_pid: int


def environment_cgroup_name(name: str, env_id: str) -> str:
    normalized = unicodedata.normalize("NFKD", name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii").lower()
    safe_name = _COMPONENT_PATTERN.sub("_", ascii_name).strip("_-")
    safe_name = safe_name[:80] or "environment"
    safe_id = _safe_identifier(env_id)[:8]
    return f"{safe_name}_{safe_id}"


def job_cgroup_name(job_id: str) -> str:
    return f"job_{_safe_identifier(job_id)}"


def environment_cgroup_path(cgroup_name: str) -> Path:
    return CGROUPS_DIR / _validate_component(cgroup_name)


def job_cgroup_path(env_cgroup_name: str, job_id: str) -> Path:
    return environment_cgroup_path(env_cgroup_name) / job_cgroup_name(job_id)


def configure_environment_cgroup(
    cgroup_path: Path,
    *,
    cpu_quota: int,
    cpu_weight: int,
    mem_limit: int,
    io_limit_bps: int = 0,
) -> None:
    period = 100_000
    quota = (cpu_quota * period) // 100
    memory_bytes = mem_limit * 1024 * 1024

    (cgroup_path / "cpu.max").write_text(f"{quota} {period}\n")
    (cgroup_path / "cpu.weight").write_text(f"{cpu_weight}\n")
    (cgroup_path / "memory.max").write_text(f"{memory_bytes}\n")
    device = os.stat("/").st_dev
    major, minor = os.major(device), os.minor(device)
    io_limit = str(io_limit_bps) if io_limit_bps > 0 else "max"
    (cgroup_path / "io.max").write_text(
        f"{major}:{minor} rbps={io_limit} wbps={io_limit}\n"
    )


async def configure_network_namespace(anchor_pid: int) -> None:
    process = await asyncio.create_subprocess_exec(
        "/usr/bin/nsenter",
        "-t",
        str(anchor_pid),
        "-n",
        "ip",
        "link",
        "set",
        "lo",
        "up",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(
            "Could not enable namespace loopback: "
            f"{stderr.decode(errors='replace').strip()}"
        )


def find_environment_anchor(cgroup_path: Path) -> int | None:
    for pid in read_cgroup_pids(cgroup_path):
        try:
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue

        arguments = [part for part in cmdline.split(b"\0") if part]
        if arguments and arguments[0].endswith(b"sleep") and b"infinity" in arguments[1:]:
            return pid

    return None


def has_isolated_network_namespace(anchor_pid: int) -> bool:
    try:
        host_namespace = os.stat("/proc/self/ns/net").st_ino
        environment_namespace = os.stat(f"/proc/{anchor_pid}/ns/net").st_ino
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return False
    return environment_namespace != host_namespace


def read_cgroup_pids(cgroup_path: Path) -> list[int]:
    procs_file = cgroup_path / "cgroup.procs"
    if not procs_file.exists():
        return []

    return [
        int(pid)
        for pid in procs_file.read_text().splitlines()
        if pid.strip().isdigit()
    ]


def prepare_job_cgroup(env_cgroup_name: str, job_id: str) -> Path:
    cgroup_path = job_cgroup_path(env_cgroup_name, job_id)
    cgroup_path.mkdir(parents=False, exist_ok=False)
    return cgroup_path


async def cleanup_job_cgroup(env_cgroup_name: str, job_id: str) -> None:
    await cleanup_cgroup_tree(job_cgroup_path(env_cgroup_name, job_id))


async def cleanup_environment_cgroup(cgroup_name: str) -> None:
    await cleanup_cgroup_tree(environment_cgroup_path(cgroup_name))


async def cleanup_cgroup_tree(cgroup_path: Path) -> None:
    if not cgroup_path.exists():
        return

    kill_file = cgroup_path / "cgroup.kill"
    if kill_file.exists():
        kill_file.write_text("1\n")
    else:
        for group in reversed(_cgroup_tree(cgroup_path)):
            for pid in read_cgroup_pids(group):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    for _ in range(40):
        if all(not read_cgroup_pids(group) for group in _cgroup_tree(cgroup_path)):
            break
        await asyncio.sleep(0.05)

    groups = _cgroup_tree(cgroup_path)
    for group in reversed(groups[1:]):
        group.rmdir()
    cgroup_path.rmdir()


def _cgroup_tree(root: Path) -> list[Path]:
    groups = [root]
    for child in root.iterdir():
        if child.is_dir():
            groups.extend(_cgroup_tree(child))
    return groups


def _safe_identifier(value: str) -> str:
    safe_value = re.sub(r"[^a-zA-Z0-9]", "", value).lower()
    if not safe_value:
        raise ValueError("Identifier must contain at least one alphanumeric character")
    return safe_value


def _validate_component(value: str) -> str:
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError("Invalid cgroup component")
    return value
