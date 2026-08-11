FROM python:3.13-slim

# git is needed at build time to replay the snapshot history that
# reconstructs the incident database.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev

COPY . .

RUN uv run python scripts/rebuild.py \
    && uv run python scripts/check_integrity.py

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
