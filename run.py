"""Start Wizard from a work-PC install (portable Python, see setup.ps1) or from a development checkout.

  python run.py --home <install folder>           serve on WIZARD_HOST:WIZARD_PORT (settings from <home>/.env)
  python run.py --home <install folder> --check   validate settings, web app and Gemini CLI compatibility
  python run.py --home <home> --desktop           the desktop app's service (started and restarted by WizardBar)
  python run.py --home <home> --import-provision <file>   store a provisioning file's settings for this PC
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
    parser.add_argument("--desktop", action="store_true", help="run as the desktop app's service (needs --home)")
    parser.add_argument("--import-provision", type=Path, default=None, metavar="FILE",
                        help="import a wizard.provision file into the data folder (the file is deleted afterwards)")
    args = parser.parse_args()
    if (args.desktop or args.import_provision) and not args.home:
        parser.error("--desktop and --import-provision need --home")

    import logging

    from wizard_api.config import ConfigError, load_settings
    try:
        if args.import_provision:
            from wizard_api import provisioning
            data_dir = load_settings(home=args.home).data_dir
            provision = provisioning.import_file(args.import_provision, data_dir)
            print(f"Imported {provision.name or 'provisioning'}: {', '.join(sorted(provision.values()))}")
            return 0
        if args.desktop:
            from wizard_api.desktop import prepare
            settings = prepare(args.home)
        else:
            settings = load_settings(home=args.home)
    except ConfigError as error:
        logging.getLogger("wizard").error("configuration error: %s", error)
        print(f"Wizard configuration error: {error}", file=sys.stderr)
        return 2
    except ValueError as error:  # ProvisionError
        print(f"Wizard provisioning error: {error}", file=sys.stderr)
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
    server = uvicorn.Server(uvicorn.Config(app, host=settings.host, port=settings.port, log_level="warning",
                                           proxy_headers=False))
    if args.desktop:
        from wizard_api.desktop import RESTART_EXIT_CODE
        restart = {"asked": False}

        def request_restart() -> None:
            restart["asked"] = True
            server.should_exit = True

        def request_stop() -> None:
            server.should_exit = True

        app.state.request_restart, app.state.request_stop = request_restart, request_stop
        server.run()
        return RESTART_EXIT_CODE if restart["asked"] else 0
    server.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
