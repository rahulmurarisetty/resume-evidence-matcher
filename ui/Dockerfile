# syntax=docker/dockerfile:1
# The Streamlit screen. It only talks to the API over HTTP (API_URL), so it needs
# neither the app package nor its dependencies.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /ui
RUN useradd --create-home --uid 10001 appuser \
    && pip install "streamlit>=1.40" "httpx>=0.27"

COPY app.py .

USER appuser
ENV API_URL=http://api:8000
EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--browser.gatherUsageStats=false"]
