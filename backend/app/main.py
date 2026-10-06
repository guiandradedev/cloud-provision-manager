from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import settings
from .database import engine
from .migrations import run_migrations
from .routes import router


@asynccontextmanager
async def lifespan(_: FastAPI):
    await run_migrations(engine)
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(title="Provision Manager API", lifespan=lifespan)
app.include_router(router)


@app.get("/")
def healthcheck() -> dict[str, str]:
    return {"message": "Hello World!"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.port, reload=True)
