"""Fail if tracked or new files contain credentials, tokens, corporate exports or blocked documents.

A small, dependency-free scan suitable for an internal CI runner. The only allowed match is the published installed-app
OAuth client of the open-source Gemini CLI, which is public by design (see services/agent/wizard_agent/google_oauth.py)."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "google_api_key": re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    "google_oauth_access_token": re.compile(r"ya29\.[0-9A-Za-z_\-]{20,}"),
    "google_refresh_token": re.compile(r"1//0[0-9A-Za-z_\-]{30,}"),
    "oauth_client_secret": re.compile(r"GOCSPX-[0-9A-Za-z_\-]{20,}"),
    "private_key": re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "github_token": re.compile(r"gh[pousr]_[0-9A-Za-z]{30,}"),
    "aws_key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "password_assignment": re.compile(r"(?i)(password|passwd|pwd)\s*[:=]\s*['\"][^'\"\s]{6,}['\"]"),
    "mstr_auth_token": re.compile(r"X-MSTR-AuthToken:\s*[0-9a-z]{20,}"),
}
ALLOW = {("oauth_client_secret", "services/agent/wizard_agent/google_oauth.py")}
BLOCKED_SUFFIXES = (".docx", ".xlsx", ".xls", ".pptx", ".pbix", ".parquet")
SKIP_DIRS = {".git", ".venv", "node_modules", ".tools", "var", "artifacts", "dist", "__pycache__", ".mypy_cache", ".ruff_cache"}


def candidate_files() -> list[Path]:
    try:
        listed = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                                capture_output=True, text=True, check=True).stdout.splitlines()
        return [ROOT / name for name in listed]
    except (OSError, subprocess.CalledProcessError):
        return [p for p in ROOT.rglob("*") if p.is_file() and not SKIP_DIRS.intersection(p.relative_to(ROOT).parts)]


def main() -> int:
    problems = []
    for path in candidate_files():
        rel = path.relative_to(ROOT).as_posix()
        if SKIP_DIRS.intersection(Path(rel).parts) or not path.is_file():
            continue
        if path.suffix.lower() in BLOCKED_SUFFIXES:
            problems.append(f"{rel}: corporate document/export types must not be committed")
            continue
        if path.stat().st_size > 2_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for name, pattern in PATTERNS.items():
            if (name, rel) in ALLOW:
                continue
            for match in pattern.finditer(text):
                if rel.startswith("tests/") and name in ("google_oauth_access_token", "google_refresh_token", "password_assignment"):
                    continue  # tests use obviously fake token shapes such as ya29.x / 1//r
                problems.append(f"{rel}:{text[:match.start()].count(chr(10)) + 1}: possible {name}")
    if problems:
        print("Secret scan failed:\n  " + "\n  ".join(problems))
        return 1
    print("Secret scan clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
