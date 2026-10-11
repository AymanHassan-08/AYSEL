FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY pyproject.toml ./
COPY api agents services models schemas db celery_worker ./
RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["gunicorn", "api.boot:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "2", "--bind", "0.0.0.0:8000", "--timeout", "300"]
