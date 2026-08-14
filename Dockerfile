FROM python:3.13-slim

# The archived JSON under data/ is committed to the repo, so the rebuild
# just reads those files — no git session or network needed at build time.
RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev

COPY . .

RUN uv run python scripts/rebuild.py \
    && uv run python scripts/check_integrity.py

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
