FROM python:3.13-slim

# The archived JSON under data/ is committed to the repo, so the rebuild
# just reads those files — no git session or network needed at build time.
RUN pip install --no-cache-dir uv==0.11.7

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

COPY . .

RUN uv run python scripts/rebuild.py \
    && uv run python scripts/check_integrity.py

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uv", "run", "--no-sync", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
