from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.tasks import router as tasks_router
from app.core.config import settings

app = FastAPI(title="OpenClaw Agency API", version="0.1.0")

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
if origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"] ,
        allow_headers=["*"],
    )

app.include_router(tasks_router)


@app.get("/health")
def health():
    return {"ok": True}
