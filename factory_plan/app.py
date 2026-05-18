from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from factory_plan.database import initialize_database
from factory_plan.routers import api


templates = Jinja2Templates(directory="factory_plan/templates")


def create_app() -> FastAPI:
    app = FastAPI(title="Factory Plan")
    app.mount("/static", StaticFiles(directory="factory_plan/static"), name="static")
    app.include_router(api.router, prefix="/api")

    @app.on_event("startup")
    def on_startup() -> None:
        initialize_database()

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "active_page": "plan", "title": "План"},
        )

    @app.get("/import", response_class=HTMLResponse)
    def import_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            "import.html",
            {"request": request, "active_page": "import", "title": "Імпорт"},
        )

    @app.get("/calendar", response_class=HTMLResponse)
    def calendar_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            "calendar.html",
            {"request": request, "active_page": "calendar", "title": "Календар"},
        )

    @app.get("/priorities", response_class=HTMLResponse)
    def priorities_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            "priorities.html",
            {"request": request, "active_page": "priorities", "title": "Черга"},
        )

    @app.get("/doors", response_class=HTMLResponse)
    def doors_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            "doors.html",
            {"request": request, "active_page": "doors", "title": "Двері"},
        )

    return app

