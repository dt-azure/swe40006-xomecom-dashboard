"""Source API.

PLACEHOLDER: only /health exists so CI, the image, and deploys can be built
and tested before the real API lands. The Source API workstream replaces the
body of this module but keeps `create_app()` and `/health`, because the
Dockerfile, compose healthcheck, and smoke test depend on them.
"""

import os

from flask import Flask, jsonify


def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/health")
    def health():
        return jsonify(
            status="ok",
            service="source-api",
            env=os.getenv("APP_ENV", "local"),
            version=os.getenv("APP_VERSION", "dev"),
        )

    return app


if __name__ == "__main__":
    # Local debugging only. In the container, gunicorn serves the app.
    create_app().run(host="0.0.0.0", port=int(os.getenv("SOURCE_API_PORT", "5000")))
