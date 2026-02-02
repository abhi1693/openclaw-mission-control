from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.activities import router as activities_router
from app.api.org import router as org_router
from app.api.projects import router as projects_router
from app.api.work import router as work_router
from app.core.config import settings
from app.db.session import init_db

app = FastAPI(title="OpenClaw Agency API", version="0.3.0")

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
if origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.on_event("startup")
def on_startup() -> None:
    init_db()


app.include_router(org_router)
app.include_router(projects_router)
app.include_router(work_router)
app.include_router(activities_router)


@app.get("/health")
def health():
    return {"ok": True}
