"""Uvicorn/Gunicorn entrypoint."""
from api.server import create_app

app = create_app()
