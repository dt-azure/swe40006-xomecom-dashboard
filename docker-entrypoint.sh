#!/bin/sh
# One image, three components
# docker run <image> api | dashboard | pipeline
# Anything else is run as a command: `docker run <image> python -V`
set -eu

case "${1:-}" in
  api)
    exec gunicorn \
      --bind "0.0.0.0:${SOURCE_API_PORT:-5000}" \
      --workers "${API_WORKERS:-2}" \
      --access-logfile - \
      "api.app:create_app()"
    ;;
  dashboard)
    exec streamlit run "${DASHBOARD_ENTRYPOINT:-dashboard/app.py}" \
      --server.port "${DASHBOARD_PORT:-8501}" \
      --server.address 0.0.0.0 \
      --server.headless true \
      --browser.gatherUsageStats false
    ;;
  pipeline)
    exec python -m pipeline.run
    ;;
  "")
    echo "usage: <image> api | dashboard | pipeline" >&2
    exit 64
    ;;
  *)
    exec "$@"
    ;;
esac
