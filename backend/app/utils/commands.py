import asyncio

async def run_command(*args: str) -> None:
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        raise RuntimeError(
            f"Comando falhou: {' '.join(args)}\n"
            f"{stderr.decode(errors='replace')}"
        )
