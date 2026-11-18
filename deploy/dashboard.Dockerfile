FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY dashboard/requirements.txt dashboard/requirements.txt
RUN pip install --no-cache-dir -r dashboard/requirements.txt \
    && useradd --uid 10001 --create-home --no-log-init commercepulse

COPY .streamlit/config.toml .streamlit/config.toml
COPY dashboard/__init__.py dashboard/app.py dashboard/
COPY dashboard/components/ dashboard/components/
COPY dashboard/data/ dashboard/data/
COPY dashboard/views/ dashboard/views/
COPY dashboard/static/ dashboard/static/
COPY dashboard/styles/ dashboard/styles/

USER commercepulse
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
    CMD ["python", "-c", "from urllib.request import urlopen; urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3).close()"]
CMD ["streamlit", "run", "dashboard/app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
