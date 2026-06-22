"""Główna aplikacja FastAPI - Generator Pozwów SKD."""
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from pathlib import Path

from app.routers.api import router as api_router

app = FastAPI(
    title="Generator Pozwów SKD",
    description="Automatyzacja pozwów o Sankcję Kredytu Darmowego",
    version="1.0.0",
)

app.include_router(api_router)

BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
