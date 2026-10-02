"""Start Wizard: python -m wizard_api  (settings from environment / .env, see .env.example)."""
from __future__ import annotations

import logging
import sys

import uvicorn

from .app import create_app
from .config import ConfigError, load_settings


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        settings = load_settings()
        app = create_app(settings)
    except ConfigError as error:
        print(f"Wizard configuration error: {error}", file=sys.stderr)
        return 2
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info", proxy_headers=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
