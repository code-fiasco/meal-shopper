"""FastAPI application factory."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routers import health, ingredients, pages, shops

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app() -> FastAPI:
    """Build the application. Docs UIs stay off because they load remote assets."""
    application = FastAPI(
        title="Meal Shopper",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    application.include_router(health.router)
    application.include_router(pages.router)
    application.include_router(ingredients.router)
    application.include_router(shops.router)
    return application


app = create_app()
