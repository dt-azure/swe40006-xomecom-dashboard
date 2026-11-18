# One image for Source API, pipeline and dashboard
# docker run <image> api|dashboard|pipeline
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY api/ api/
COPY pipeline/ pipeline/
COPY dashboard/ dashboard/
COPY sql/ sql/
COPY scripts/ scripts/
COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# Run as a non-root user
# Mount SQLite file in /app/data
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /app/data \
    && chown app:app /app/data
USER app

# Set by CI to the git commit, so /health shows which version is running
ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION}

EXPOSE 5000 8501
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["api"]
