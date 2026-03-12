"""FastAPI-Anwendung für das Skriptendruck Web-Dashboard."""
import asyncio
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from ..config import get_logger, settings
from .routes.auth_routes import router as auth_router
from .routes.dashboard_routes import router as dashboard_router
from .routes.api_routes import router as api_router

logger = get_logger("web.app")

# Pfade
BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


# ---------------------------------------------------------------------------
# Lifespan: File-Watcher als Background-Task starten/stoppen
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Managed den Lebenszyklus der App (Startup / Shutdown)."""
    from .file_watcher import scan_orders_directory, watch_orders_loop

    # Konfigurierbare Werte
    poll_interval = float(os.environ.get("FILE_WATCHER_INTERVAL", "10"))
    watcher_enabled = os.environ.get("FILE_WATCHER_ENABLED", "true").lower() in (
        "true", "1", "yes", "ja",
    )
    orders_dir_env = os.environ.get("FILE_WATCHER_DIR", "")
    orders_dir = Path(orders_dir_env) if orders_dir_env else None

    watcher_task = None
    if watcher_enabled:
        # Einmaliger initialer Scan
        scan_orders_directory(orders_dir)
        # Periodischen Watcher starten
        watcher_task = asyncio.create_task(
            watch_orders_loop(poll_interval=poll_interval, orders_dir=orders_dir)
        )
        logger.info("File-Watcher Background-Task gestartet")
    else:
        logger.info("File-Watcher ist deaktiviert (FILE_WATCHER_ENABLED=false)")

    yield  # --- App läuft ---

    # Shutdown: Watcher sauber beenden
    if watcher_task is not None:
        watcher_task.cancel()
        try:
            await watcher_task
        except asyncio.CancelledError:
            pass
        logger.info("File-Watcher Background-Task beendet")


# ---------------------------------------------------------------------------
# App-Factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    """Erstellt und konfiguriert die FastAPI-Anwendung."""

    app = FastAPI(
        title="Skriptendruck Dashboard",
        description="Web-Dashboard für die Skriptendruck-Verwaltung der Fachschaft",
        version="1.0.0",
        docs_url="/api/docs",
        redoc_url=None,
        lifespan=lifespan,
    )

    # Session Middleware (Secret Key aus .env oder generiert)
    secret_key = os.environ.get("DASHBOARD_SECRET_KEY", secrets.token_hex(32))
    app.add_middleware(
        SessionMiddleware,
        secret_key=secret_key,
        session_cookie="skriptendruck_session",
        max_age=3600 * 8,  # 8 Stunden
        same_site="lax",
        https_only=False,  # Für lokale Entwicklung; in Prod auf True setzen
    )

    # Static Files
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Templates global verfügbar machen
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.state.templates = templates

    # Router einbinden
    app.include_router(auth_router)
    app.include_router(dashboard_router)
    app.include_router(api_router, prefix="/api")

    logger.info("Skriptendruck Web-Dashboard initialisiert")

    return app


# Globale App-Instanz für uvicorn
app = create_app()
