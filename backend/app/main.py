from __future__ import annotations

import importlib
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.chat import router as chat_router
from app.agent import AgentError
from app.api.errors import agent_exception_handler, http_exception_handler, unhandled_exception_handler, validation_exception_handler
from app.api.health import router as health_router
from app.api.sessions import router as sessions_router
from app.config import Settings
from app.sessions import SessionStore


async def _close_if_present(service) -> None:
    close = getattr(service, "close", None)
    if close is not None:
        await close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    app.state.settings = settings
    app.state.sessions = SessionStore()
    app.state.catalog = None
    app.state.conditions = None
    app.state.cart = None
    app.state.agent = None
    app.state.llm_client = None
    app.state.startup_dependency_error = None

    try:
        catalog_module = importlib.import_module("app.catalog")
        conditions_module = importlib.import_module("app.conditions")
        cart_module = importlib.import_module("app.cart")
        app.state.catalog = catalog_module.CatalogService(settings.catalog_db_path, settings)
        app.state.conditions = conditions_module.ConditionsService(settings.conditions_path, settings.catalog_mode)
        app.state.cart = cart_module.CartService(settings.cart_db_path, app.state.catalog, settings)
        await app.state.catalog.initialize()
        await app.state.conditions.initialize()
        await app.state.cart.initialize()

        llm_client = None
        if settings.openai_api_key:
            try:
                from openai import AsyncOpenAI

                llm_client = AsyncOpenAI(api_key=settings.openai_api_key)
            except ImportError:
                app.state.startup_dependency_error = "OpenAI SDK is not installed"
        app.state.llm_client = llm_client

        agent_module = importlib.import_module("app.agent")
        app.state.agent = agent_module.AgentService(
            llm_client,
            app.state.catalog,
            app.state.cart,
            app.state.conditions,
            app.state.sessions,
            settings,
        )
    except (ImportError, AttributeError) as exc:
        app.state.startup_dependency_error = f"Neighbor service not connected: {exc}"

    try:
        yield
    finally:
        for name in ("cart", "conditions", "catalog"):
            service = getattr(app.state, name, None)
            if service is not None:
                await _close_if_present(service)
        client = getattr(app.state, "llm_client", None)
        close = getattr(client, "close", None)
        if close is not None:
            await close()


def _create_app() -> FastAPI:
    application = FastAPI(title="EKT AI", lifespan=lifespan)
    application.add_exception_handler(StarletteHTTPException, http_exception_handler)
    application.add_exception_handler(RequestValidationError, validation_exception_handler)
    application.add_exception_handler(AgentError, agent_exception_handler)
    application.add_exception_handler(Exception, unhandled_exception_handler)
    application.include_router(health_router)
    application.include_router(sessions_router)
    application.include_router(chat_router)

    try:
        application.include_router(importlib.import_module("app.api.catalog").router)
    except (ImportError, AttributeError):
        pass
    try:
        application.include_router(importlib.import_module("app.api.cart").router)
    except (ImportError, AttributeError):
        pass

    backend_dir = Path(__file__).resolve().parents[1]
    web_dir = backend_dir.parent / "web"
    if web_dir.exists():
        assets_dir = web_dir / "assets"
        if assets_dir.exists():
            application.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @application.get("/", include_in_schema=False)
        async def index() -> FileResponse:
            return FileResponse(web_dir / "index.html")

    certificates_dir = backend_dir / "data" / "certificates"
    if certificates_dir.exists():
        application.mount("/demo-certificates", StaticFiles(directory=certificates_dir), name="demo-certificates")
    return application


app = _create_app()
