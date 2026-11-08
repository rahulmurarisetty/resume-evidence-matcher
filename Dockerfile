# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
RUN useradd --create-home --uid 10001 appuser

# Pinned, hash-checked dependencies first so this layer is cached between builds.
# v0.2 adds sentence-transformers. Install PyTorch from the CPU-only index then
# (https://download.pytorch.org/whl/cpu); the default Linux wheel pulls several GB
# of CUDA libraries this service does not need.
COPY requirements.lock .
RUN pip install --require-hashes -r requirements.lock

COPY pyproject.toml README.md LICENSE ./
COPY app ./app
RUN pip install --no-deps . && rm -rf /app/build

USER appuser
ENV DATABASE_URL=sqlite:////home/appuser/data/app.db
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status != 200)"

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
