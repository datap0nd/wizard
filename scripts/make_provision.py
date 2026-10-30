"""Make the provisioning file (wizard.provision) the owner hands out with WizardSetup.exe.

  uv run python scripts/make_provision.py company.env --name "ACME pilot" --out wizard.provision

`company.env` holds KEY=value lines, kept outside every Git repository (it has the knowledge-base token, the read-only
PostgreSQL password and Metronome's Wizard key), for example:

  WIZARD_KB_REPO=acme/wizard-content          the private knowledge-base repository
  WIZARD_KB_TOKEN=github_pat_...              fine-grained token: that repository only, Contents: read-only
  WIZARD_KB_PATH=                             folder inside the repository, if the content is not at its root
  WIZARD_PG_HOST=... WIZARD_PG_PORT=5432 WIZARD_PG_DATABASE=... WIZARD_PG_USER=wizard_ro WIZARD_PG_PASSWORD=...
  GOOGLE_CLOUD_PROJECT=...                    the organisation's Gemini project
  WIZARD_GOOGLE_DOMAINS=company.com           only company Google accounts may link for Gemini
  WIZARD_METRONOME_URL=http://10.0.0.5:8000   Metronome, for recurring extractions emailed as Flows of its Wizard user
  WIZARD_METRONOME_CLIENT_KEY=wizard-...      printed by scripts/metronome_link.py on the Metronome host PC

Put the output next to WizardSetup.exe: setup imports it, and Wizard deletes the plaintext copy after importing. Anyone
with the file has these credentials, so share it only inside the company."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for entry in ("services/api", "services/agent", "services/connectors", "services/checks", "services/documents", "vendor"):
    sys.path.insert(0, str(ROOT / entry))

from wizard_api.config import read_env_file  # noqa: E402
from wizard_api.provisioning import ProvisionError, is_secret, render  # noqa: E402


def build(values: dict[str, str], name: str) -> str:
    return render(values, name)  # the same checks Wizard applies when importing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path, help="KEY=value file with the company settings (never commit it)")
    parser.add_argument("--name", default="", help="a label shown in Wizard's checks, e.g. the company or pilot name")
    parser.add_argument("--out", type=Path, default=Path("wizard.provision"))
    args = parser.parse_args()
    values = read_env_file(args.source)
    if not values:
        print(f"{args.source} has no KEY=value lines.", file=sys.stderr)
        return 2
    try:
        text = build(values, args.name)
    except ProvisionError as error:
        print(f"Not a valid provisioning file: {error}", file=sys.stderr)
        return 2
    args.out.write_text(text, encoding="utf-8")
    secrets = sorted(k for k in values if values[k] and is_secret(k))
    plain = sorted(k for k in values if values[k] and not is_secret(k))
    print(f"Wrote {args.out}: {len(plain)} setting(s) ({', '.join(plain)}) and {len(secrets)} secret(s) ({', '.join(secrets)}).")
    if "WIZARD_KB_REPO" in values and not values.get("WIZARD_KB_TOKEN"):
        print("Warning: WIZARD_KB_REPO without WIZARD_KB_TOKEN: Wizard cannot read a private repository.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
