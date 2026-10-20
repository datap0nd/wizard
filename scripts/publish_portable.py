"""CI: publish the portable runtime release that the committed locks name, when it does not exist yet.

setup.ps1 installs the portable Python and every locked wheel from the GitHub release named in
portable_assets.lock.json. scripts/lock_portable.py makes and commits the locks; this publishes exactly those archives
(each fetched from its python.org or PyPI address and SHA-256 checked against the lock), so a lock change never leaves
work-PC installs without their release. Nothing is re-resolved, and an existing release is never touched.

  python scripts/publish_portable.py --target <commit sha>     (needs gh with a token that may create releases)"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_desktop_payload import ROOT, digest, fetch  # noqa: E402

REPOSITORY = "datap0nd/wizard"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", help="the commit the release's tag points at (default: the repository's default branch)")
    parser.add_argument("--repo", default=REPOSITORY)
    args = parser.parse_args()
    assets = json.loads((ROOT / "portable_assets.lock.json").read_text(encoding="utf-8"))
    for lock, key in (("runtime.lock.json", "runtime_lock_sha256"), ("dependencies.lock.json", "dependency_lock_sha256")):
        if digest(ROOT / lock) != assets[key]:
            print(f"{lock} does not match portable_assets.lock.json: run scripts/lock_portable.py and commit the locks")
            return 1
    tag = assets["release_tag"]
    if subprocess.run(["gh", "release", "view", tag, "--repo", args.repo], capture_output=True).returncode == 0:
        print(f"Release {tag} already exists; nothing to publish.")
        return 0
    runtime = json.loads((ROOT / "runtime.lock.json").read_text(encoding="utf-8"))
    packages = json.loads((ROOT / "dependencies.lock.json").read_text(encoding="utf-8"))["packages"]
    with tempfile.TemporaryDirectory() as scratch:
        cache = Path(scratch)
        files = [str(fetch(item, tag, cache)) for item in [runtime, *packages]]
        command = ["gh", "release", "create", tag, "--repo", args.repo, "--title", f"Portable runtime {tag}",
                   "--notes", "Portable Python and locked wheels for work-PC installs (setup.ps1). Do not delete.",
                   "--latest=false", *(["--target", args.target] if args.target else []), *files]
        subprocess.run(command, check=True)
    print(f"Published {len(files)} archives to {args.repo} release {tag}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
