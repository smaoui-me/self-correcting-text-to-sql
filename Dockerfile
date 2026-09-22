FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8 \
    DATABASE_PATH=/app/chinook.db

WORKDIR /app
COPY requirements-lock.txt ./
RUN python -m pip install --no-cache-dir -r requirements-lock.txt

COPY src/ ./src/
COPY scripts/ ./scripts/
COPY tests/ ./tests/
COPY benchmarks/ ./benchmarks/
COPY main.py pytest.ini ./

# Download and verify the pinned public dataset during build, without API keys.
RUN python scripts/setup_db.py \
    && chmod 444 /app/chinook.db \
    && mkdir -p /app/results \
    && chown 1000:1000 /app/results

USER 1000:1000
ENTRYPOINT ["python"]
CMD ["main.py"]
