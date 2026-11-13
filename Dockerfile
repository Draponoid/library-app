FROM python:3.13.9-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt requirements-docker.txt ./
RUN pip install --no-cache-dir -r requirements-docker.txt \
    && useradd --uid 10001 --create-home library
COPY app.py pg_adapter.py schema.sql schema-postgres.sql ./
COPY static ./static
USER 10001:10001
EXPOSE 5000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/health', timeout=2)"
CMD ["gunicorn", "--bind=0.0.0.0:5000", "--workers=2", "--graceful-timeout=25", "--access-logfile=-", "app:create_app()"]
