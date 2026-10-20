"""Assemble what WizardSetup.exe installs (CI runs this on Windows before Inno Setup; it also runs anywhere for a check).

  python scripts/build_desktop_payload.py --out artifacts/desktop/payload [--commit <sha>]

Layout under --out (the installer copies bar\\, app\\ and runtime\\ into %LOCALAPPDATA%\\Programs\\Wizard):
  app\\              this repository's runtime files (services, run.py, the built web app, fixtures, contracts...) with
                    the locked libraries unpacked into app\\vendor (scripts/vendor_dependencies.py, as setup.ps1 does)
  runtime\\python\\   python.org's embeddable CPython from runtime.lock.json
  bar\\              WizardBar.exe and WebView2 (built separately by `dotnet build -o <out>\\bar`)

Every archive is the one the locks pin, SHA-256 checked: from this repository's portable release (the same files
setup.ps1 installs), else from its upstream URL. Standard library only. The payload carries no credentials: company
settings arrive separately in wizard.provision."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASES = "https://github.com/datap0nd/wizard/releases/download"
# Not needed to run Wizard on a PC: tests, sources of the built web app, the desktop app's own sources, CI files.
EXCLUDED = ("tests/", "docs/", "apps/desktop/", "apps/web/src/", "apps/web/e2e/", "apps/web/scripts/", ".github/", "artifacts/",
            "workpc/", "installer/", ".claude/")
EXCLUDED_FILES = ("apps/web/package.json", "apps/web/package-lock.json", "apps/web/index.html", "apps/web/tsconfig.json",
                  "apps/web/vite.config.ts", "apps/web/playwright.config.ts", "uv.lock")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fetch(item: dict, release_tag: str, cache: Path) -> Path:
    name = item["filename"]
    if Path(name).name != name:
        raise ValueError(f"invalid file name in lock: {name}")
    target = cache / name
    if target.is_file() and digest(target) == item["sha256"]:
        return target
    for url in (f"{RELEASES}/{release_tag}/{name}", item.get("url")):
        if not url:
            continue
        try:
            with urllib.request.urlopen(url, timeout=300) as response, target.open("wb") as output:  # noqa: S310 - pinned hosts
                shutil.copyfileobj(response, output)
        except OSError as error:
            print(f"  {name}: {url} failed ({error})", flush=True)
            continue
        if digest(target) == item["sha256"]:
            print(f"  {name} from {url.split('/')[2]}", flush=True)
            return target
        print(f"  {name}: checksum mismatch from {url}", flush=True)
    raise ValueError(f"could not download {name} with the locked checksum")


def source_files() -> list[str]:
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout.decode("utf-8")
    files = [f for f in listed.split("\0") if f]
    return [f for f in files if not f.startswith(EXCLUDED) and f not in EXCLUDED_FILES and (ROOT / f).is_file()]


def build(out: Path, cache: Path, commit: str | None) -> dict:
    out = out.resolve()
    for part in ("app", "runtime"):
        shutil.rmtree(out / part, ignore_errors=True)
    cache.mkdir(parents=True, exist_ok=True)
    files = source_files()
    for relative in files:
        target = out / "app" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    print(f"app: {len(files)} files", flush=True)

    assets = json.loads((ROOT / "portable_assets.lock.json").read_text(encoding="utf-8"))
    for lock, key in (("runtime.lock.json", "runtime_lock_sha256"), ("dependencies.lock.json", "dependency_lock_sha256")):
        if digest(ROOT / lock).upper() != assets[key].upper():
            raise ValueError(f"{lock} does not match portable_assets.lock.json")
    runtime = json.loads((ROOT / "runtime.lock.json").read_text(encoding="utf-8"))
    python_zip = fetch(runtime, assets["release_tag"], cache)
    python_dir = out / "runtime" / "python"
    with zipfile.ZipFile(python_zip) as bundle:
        for member in bundle.namelist():
            if member.startswith(("/", "\\")) or ".." in Path(member).parts:
                raise ValueError(f"unsafe path in {python_zip.name}: {member}")
        bundle.extractall(python_dir)
    print(f"runtime: Python {runtime['version']} embeddable", flush=True)

    dependencies = json.loads((ROOT / "dependencies.lock.json").read_text(encoding="utf-8"))
    for package in dependencies["packages"]:
        fetch(package, assets["release_tag"], cache)
    sys.path.insert(0, str(ROOT / "scripts"))
    from vendor_dependencies import vendor
    vendor(cache, cache / "store", out / "app" / "vendor", ROOT / "dependencies.lock.json")

    record = {"commit": commit or "local", "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
              "python": runtime["version"], "packages": len(dependencies["packages"]), "files": len(files)}
    (out / "app" / "BUILD.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    for required in ("app/run.py", "app/apps/web/dist/index.html", "app/fixtures/identities.json", "runtime/python/python.exe",
                     "app/vendor/fastapi/__init__.py", "app/vendor/uvicorn/__init__.py"):
        if not (out / required).is_file():
            raise ValueError(f"payload is missing {required}")
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts" / "desktop" / "payload")
    parser.add_argument("--cache", type=Path, default=ROOT / "artifacts" / "desktop" / "downloads")
    parser.add_argument("--commit", default=None)
    args = parser.parse_args()
    try:
        record = build(args.out, args.cache, args.commit)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"Payload build failed: {error}", file=sys.stderr)
        return 1
    print(f"Payload ready in {args.out}: {json.dumps(record)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
