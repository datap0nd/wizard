"""Start Wizard from a work-PC install (portable Python, see setup.ps1) or from a development checkout.

  python run.py --home <install folder>           serve on WIZARD_HOST:WIZARD_PORT (settings from <home>/.env)
  python run.py --home <install folder> --check   validate settings, web app and Gemini CLI compatibility
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for entry in ("services/checks", "services/connectors", "services/documents", "services/agent", "services/api", "vendor"):
    sys.path.insert(0, str(ROOT / entry))


def main() -> int:
    parser = argparse.ArgumentParser(description="Wizard")
    parser.add_argument("--home", type=Path, default=None, help="install folder holding .env and data (default: repository)")
    parser.add_argument("--check", action="store_true", help="validate the installation and exit")
    args = parser.parse_args()

    import logging

    from wizard_api.config import ConfigError, load_settings
    try:
        settings = load_settings(home=args.home)
    except ConfigError as error:
        print(f"Wizard configuration error: {error}", file=sys.stderr)
        return 2
    if args.check:
        from wizard_api.preflight import run_checks
        return run_checks(settings)

    import uvicorn

    from wizard_api.app import create_app
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        app = create_app(settings)
    except ConfigError as error:
        print(f"Wizard configuration error: {error}", file=sys.stderr)
        return 2
    print(f"Wizard {settings.runtime} runtime | http://{settings.internal_url.split('//')[1]} | data {settings.data_dir}", flush=True)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="warning", proxy_headers=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
