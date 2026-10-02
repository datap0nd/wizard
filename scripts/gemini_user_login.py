"""Operator fallback for Step 02: sign one Wizard user into Gemini CLI inside that user's own isolated home.

Prefer the in-app flow (Account → Sign in with Google), which ties the Google account to the signed-in Wizard user and
refuses a mismatched email. Use this only when the user is physically at the host (or screen-sharing) and the operator
needs to run the CLI's own interactive sign-in, e.g. to compare behaviour during the spike.

  uv run python scripts/gemini_user_login.py --user u-alice [--data-dir D:/wizard-data]

It prepares <data>/users/<hash>/gemini with Wizard's settings, forces per-home file credential storage, and opens the
interactive Gemini CLI there. In the CLI, choose "Login with Google" and complete the sign-in AS THAT USER, then /quit."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for sub in ("api", "agent", "connectors", "checks"):
    sys.path.insert(0, str(ROOT / "services" / sub))

from wizard_agent.gemini_cli import GeminiCliConfig, GeminiCliRuntime, resolve_cli_js  # noqa: E402
from wizard_api.config import load_settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--user", required=True)
    parser.add_argument("--data-dir")
    args = parser.parse_args()
    env = {k: v for k, v in os.environ.items() if k.startswith(("WIZARD_", "GOOGLE_CLOUD_PROJECT"))}
    if args.data_dir:
        env["WIZARD_DATA_DIR"] = args.data_dir
    settings = load_settings(env=env)
    cli_js = resolve_cli_js(settings.gemini_cli_js, ROOT)
    node = settings.node or shutil.which("node")
    if not cli_js or not node:
        print("Gemini CLI or Node.js not found. Install @google/gemini-cli or set WIZARD_GEMINI_CLI_JS.", file=sys.stderr)
        return 2
    runtime = GeminiCliRuntime(GeminiCliConfig(model=settings.model, internal_url=settings.internal_url, cli_js=cli_js, node=node,
                                               google_cloud_project=settings.google_cloud_project))
    user_home = settings.user_home(args.user)
    home = runtime.prepare_home(user_home)
    child_env = {k: v for k, v in runtime._base_env(home).items() if k != "NO_BROWSER"}
    if settings.google_cloud_project:
        child_env["GOOGLE_CLOUD_PROJECT"] = settings.google_cloud_project
    print(f"Gemini CLI home for {args.user}: {home}\nCredentials will be stored only in {home / '.gemini'}.\n")
    return subprocess.call([node, str(cli_js), "--model", settings.model], cwd=home, env=child_env)


if __name__ == "__main__":
    sys.exit(main())
