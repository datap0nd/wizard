"""Start-up for the desktop app: WizardBar runs `run.py --home <home> --desktop` and keeps it running.

The home folder (%LOCALAPPDATA%\\Wizard) holds .env, data\\ and logs\\; the program files are replaced by every update.
Before serving, this:
- adds missing .env defaults for a desktop install (code-assist runtime, so no Node or Gemini CLI is needed);
- imports wizard.provision if the installer or the tray menu put one in the home folder;
- syncs the knowledge base once, so a PC that was off for a week starts on the current version.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import subprocess
from pathlib import Path

from . import knowledge_sync, provisioning
from .config import ConfigError, Settings, kb_source, load_settings, read_env_file

RESTART_EXIT_CODE = 75  # the service asks WizardBar to start it again (new knowledge base)
DEFAULT_PORT = 8771  # not 8770, so the work-PC install (start.ps1) can run beside it
log = logging.getLogger("wizard.desktop")


def _work_email() -> str:
    if os.name != "nt":
        return ""
    try:
        result = subprocess.run(["whoami", "/upn"], capture_output=True, text=True, timeout=10,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return ""
    upn = result.stdout.strip()
    return upn if result.returncode == 0 and "@" in upn and " " not in upn else ""


def ensure_env(home: Path) -> list[str]:
    """Add the desktop defaults that are missing from <home>/.env; never changes a value. Returns the keys added."""
    home.mkdir(parents=True, exist_ok=True)
    path = home / ".env"
    present = read_env_file(path)
    defaults = [
        ("WIZARD_AGENT_RUNTIME", "code-assist", "Gemini runs in Wizard with your own Google sign-in (no Node or Gemini CLI)"),
        ("WIZARD_DATA_DIR", "data", "Conversations, your Gemini sign-in and the knowledge base"),
        ("WIZARD_PORT", str(DEFAULT_PORT), "Local port the desktop app uses"),
        ("WIZARD_DIAGNOSTICS", "false", "true shows developer diagnostics in the app"),
        ("WIZARD_LOCAL_USER_EMAIL", _work_email(), "Your work email"),
        ("WIZARD_LOCAL_USER_NAME", os.environ.get("USERNAME", ""), ""),
    ]
    added = [(k, v, c) for k, v, c in defaults if v and k not in present]
    if not added:
        return []
    text = path.read_text(encoding="utf-8-sig") if path.is_file() else "# Wizard desktop settings for this PC.\n"
    if text and not text.endswith("\n"):
        text += "\n"
    for key, value, comment in added:
        text += (f"# {comment}\n" if comment else "") + f"{key}={value}\n"
    path.write_text(text, encoding="utf-8")
    return [k for k, _, _ in added]


def log_to_file(folder: Path) -> Path:
    """<home>/logs/wizard.log, beside WizardBar's bar.log, so "Open the log folder" shows both."""
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "wizard.log"
    handler = logging.handlers.RotatingFileHandler(target, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    return target


def prepare(home: Path, env: dict[str, str] | None = None) -> Settings:
    """Settings for the desktop service, after the provisioning import and a first knowledge-base sync."""
    home = home.resolve()
    added = ensure_env(home)
    settings = load_settings(env=env, home=home)
    log_to_file(home / "logs")
    if added:
        log.info("desktop settings added to %s: %s", home / ".env", ", ".join(added))
    offered = home / provisioning.FILENAME
    if offered.is_file():
        try:
            provision = provisioning.import_file(offered, settings.data_dir)
            log.info("imported provisioning %r: %d setting(s), %d secret(s)", provision.name, len(provision.settings),
                     len(provision.secrets))
        except (provisioning.ProvisionError, OSError) as error:
            raise ConfigError(f"{offered} could not be imported: {error}") from None
        settings = load_settings(env=env, home=home)
    source = kb_source(settings)
    if source:
        result = knowledge_sync.sync(source, settings.data_dir, proxy=settings.github_proxy, timeout=30)
        (log.info if result.ok else log.warning)("knowledge base at start-up: %s", result.message)
        settings = load_settings(env=env, home=home)
    settings.desktop = True
    return settings
