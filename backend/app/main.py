from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.database import init_db


def create_app() -> FastAPI:
    app = FastAPI(
        title="Governed SaaS AIOps Copilot",
        description="Evidence-grounded SaaS monitoring copilot with LangGraph, CrewAI, approval gates, and auditability.",
        version="0.1.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)

    @app.on_event("startup")
    def _startup() -> None:
        init_db()

    return app


app = create_app()

