"""Check a wizard-content folder before Wizard loads it (same rules the API applies at start-up).

  uv run python scripts/validate_content.py D:/wizard-content

Exit 0 when there are no errors (warnings are listed for owner review), 1 otherwise."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "connectors"))

from wizard_connectors.content import errors, validate_content  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    root = Path(sys.argv[1]).resolve()
    problems = validate_content(root)
    for problem in problems:
        print(problem)
    failed = errors(problems)
    reports = sum(1 for _ in (root / "contracts" / "sources").glob("*.json")) if (root / "contracts" / "sources").is_dir() else 0
    print(f"{'FAILED' if failed else 'OK'}: {reports} catalog file(s), {len(failed)} error(s), {len(problems) - len(failed)} warning(s).")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
