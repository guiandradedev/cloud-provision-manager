from pathlib import Path

from ..config import settings


STORAGE_DIR = Path(settings.storage_dir)
SCRIPTS_DIR = STORAGE_DIR / "scripts"
OUTPUTS_DIR = STORAGE_DIR / "outputs"


def prepare_storage() -> None:
    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)


def script_path(job_id: str, filename: str) -> Path:
    return SCRIPTS_DIR / f"{job_id}-{Path(filename).name}"


def job_output_path(job_id: str) -> Path:
    return OUTPUTS_DIR / f"{job_id}.log"


def append_job_output(job_id: str, stream: str, message: str) -> None:
    with job_output_path(job_id).open("a", encoding="utf-8") as output:
        output.write(f"[{stream}] {message}\n")
