FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/data/library.sqlite3
WORKDIR /app
COPY requirements.txt requirements-docker.txt ./
RUN pip install --no-cache-dir -r requirements-docker.txt \
    && useradd --uid 10001 --create-home library \
    && mkdir /data && chown library:library /data
COPY app.py schema.sql ./
COPY static ./static
USER library
EXPOSE 5000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/health', timeout=2)"
CMD ["waitress-serve", "--listen=0.0.0.0:5000", "--call", "app:create_app"]
