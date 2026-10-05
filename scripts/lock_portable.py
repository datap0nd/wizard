"""Maintainer tool: pin the portable Windows runtime for work-PC installs and publish it as a GitHub release.

Work PCs get no pip, no PyPI and no Node build. setup.ps1 downloads, from this repository's GitHub release:
  - the official Python embeddable zip (runtime.lock.json)
  - every runtime wheel for CPython 3.13 / Windows x64 (dependencies.lock.json)
and verifies each SHA-256 before use (same model as the B2B installer).

  python scripts/lock_portable.py            # resolve, download, hash, write the three lock files
  python scripts/lock_portable.py --publish  # also create the GitHub release with the archives

Needs only a Python with pip (no uv, no compiled packages), so it runs on PCs where Application Control blocks
unsigned binaries. Existing pins are kept as constraints: adding a dependency never silently upgrades the others
(pass --upgrade to re-resolve everything). Re-run after changing runtime dependencies in pyproject.toml, then commit the
lock files."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "artifacts" / "portable"
REPOSITORY = "datap0nd/wizard"
PYTHON_VERSION = "3.13.15"
PYTHON_ZIP = f"python-{PYTHON_VERSION}-embed-amd64.zip"
PYTHON_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/{PYTHON_ZIP}"


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


PLATFORM = ["--platform", "win_amd64", "--python-version", "3.13", "--implementation", "cp", "--abi", "cp313",
            "--abi", "abi3", "--abi", "none", "--only-binary=:all:"]


def pip(*args: str) -> None:
    subprocess.run([sys.executable, "-m", "pip", *args, "--disable-pip-version-check"], check=True, cwd=ROOT)


def resolve(upgrade: bool) -> list[tuple[str, str]]:
    """Pins for CPython 3.13 / Windows x64, resolved by pip for that target (not for this machine)."""
    requirements = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    with tempfile.TemporaryDirectory() as scratch:
        constraints = Path(scratch) / "constraints.txt"
        current = ROOT / "dependencies.lock.json"
        pinned = [] if upgrade or not current.is_file() else json.loads(current.read_text(encoding="utf-8"))["packages"]
        constraints.write_text("".join(f"{p['name']}=={p['version']}\n" for p in pinned), encoding="utf-8")
        report = Path(scratch) / "report.json"
        pip("install", "--dry-run", "--ignore-installed", "--quiet", "--report", str(report), "--target",
            str(Path(scratch) / "target"), *PLATFORM, "-c", str(constraints), *requirements)
        installs = json.loads(report.read_text(encoding="utf-8"))["install"]
    return sorted((i["metadata"]["name"], i["metadata"]["version"]) for i in installs)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--upgrade", action="store_true", help="re-resolve every pin instead of keeping current ones")
    args = parser.parse_args()
    pins = resolve(args.upgrade)
    wheels = WORK / "wheels"
    shutil.rmtree(WORK, ignore_errors=True)
    wheels.mkdir(parents=True)

    packages = []
    for name, version in pins:
        pip("download", f"{name}=={version}", "--no-deps", *PLATFORM, "-d", str(wheels), "-q")
    for wheel in sorted(wheels.glob("*.whl")):
        project = wheel.name.split("-")[0]
        version = wheel.name.split("-")[1]
        url = ""
        try:
            with urllib.request.urlopen(f"https://pypi.org/pypi/{project}/{version}/json", timeout=60) as response:
                url = next(u["url"] for u in json.load(response)["urls"] if u["filename"] == wheel.name)
        except (OSError, StopIteration, KeyError):
            pass
        packages.append({"name": project.replace("_", "-").lower(), "version": version, "filename": wheel.name, "url": url,
                         "sha256": sha256(wheel)})

    python_zip = WORK / PYTHON_ZIP
    urllib.request.urlretrieve(PYTHON_URL, python_zip)  # noqa: S310 - fixed python.org URL
    runtime = {"version": PYTHON_VERSION, "filename": PYTHON_ZIP, "url": PYTHON_URL, "sha256": sha256(python_zip)}

    dependencies = {"format": 2, "platform": "win_amd64", "python_tag": "cp313", "packages": packages}
    (ROOT / "runtime.lock.json").write_text(json.dumps(runtime, indent=2) + "\n", encoding="utf-8", newline="\n")
    (ROOT / "dependencies.lock.json").write_text(json.dumps(dependencies, indent=2) + "\n", encoding="utf-8", newline="\n")
    runtime_hash = sha256(ROOT / "runtime.lock.json")
    dependency_hash = sha256(ROOT / "dependencies.lock.json")
    tag = "portable-cp313-win_amd64-" + hashlib.sha256((runtime_hash + dependency_hash).encode()).hexdigest()[:20]
    assets = {"format": 1, "release_tag": tag, "dependency_lock_sha256": dependency_hash, "runtime_lock_sha256": runtime_hash}
    (ROOT / "portable_assets.lock.json").write_text(json.dumps(assets, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"Locked Python {PYTHON_VERSION} and {len(packages)} wheels; release tag {tag}.")

    if args.publish:
        exists = subprocess.run(["gh", "release", "view", tag, "--repo", REPOSITORY], capture_output=True).returncode == 0
        if exists:
            print(f"Release {tag} already exists; nothing to publish.")
        else:
            files = [str(python_zip), *[str(w) for w in sorted(wheels.glob("*.whl"))]]
            subprocess.run(["gh", "release", "create", tag, "--repo", REPOSITORY, "--title", f"Portable runtime {tag}",
                            "--notes", "Portable Python and locked wheels for work-PC installs (setup.ps1). Do not delete.",
                            "--latest=false", *files], check=True)
            print(f"Published {len(files)} archives to {REPOSITORY} release {tag}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
