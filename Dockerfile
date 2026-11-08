# syntax=docker/dockerfile:1

# INSTALL_ML=true adds sentence-transformers for matching by meaning. PyTorch then
# comes from the CPU-only index (https://download.pytorch.org/whl/cpu), because the
# default Linux wheel pulls several GB of CUDA libraries this service does not use.
# With the default (false) the ml-true stage below is never built.
ARG INSTALL_ML=false

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
# The data and model-cache folders exist in the image so named volumes mounted
# there start out owned by appuser.
RUN useradd --create-home --uid 10001 appuser \
    && install -d -o appuser -g appuser \
        /home/appuser/data /home/appuser/.cache /home/appuser/.cache/huggingface

# Pinned, hash-checked dependencies first so this layer is cached between builds.
COPY requirements.lock .
RUN pip install --require-hashes -r requirements.lock

FROM base AS ml-false

FROM base AS ml-true
# Not hash-locked: see the ml extra in pyproject.toml.
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch \
    && pip install "sentence-transformers>=3"

FROM ml-${INSTALL_ML}

COPY pyproject.toml README.md LICENSE ./
COPY app ./app
RUN pip install --no-deps . && rm -rf /app/build

USER appuser
ENV DATABASE_URL=sqlite:////home/appuser/data/app.db
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status != 200)"

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
