"""Start Wizard for browser E2E: replay runtime, SYNTHETIC fixtures, a fresh temporary data directory.
Usage: python scripts/e2e_server.py --port 8779"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for sub in ("api", "agent", "connectors", "checks"):
    sys.path.insert(0, str(ROOT / "services" / sub))

import uvicorn  # noqa: E402

from wizard_api.app import create_app  # noqa: E402
from wizard_api.config import load_settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8779)
    args = parser.parse_args()
    data = Path(tempfile.mkdtemp(prefix="wizard-e2e-"))
    try:
        settings = load_settings(env={"WIZARD_DATA_DIR": str(data), "WIZARD_PORT": str(args.port), "WIZARD_AGENT_RUNTIME": "replay",
                                      "WIZARD_REPLAY_DELAY_S": "0.01"}, env_file=data / "none.env")
        if not (settings.web_dist / "index.html").is_file():
            print("apps/web/dist is missing: run `npm --prefix apps/web run build` first.", file=sys.stderr)
            return 2
        uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        shutil.rmtree(data, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
