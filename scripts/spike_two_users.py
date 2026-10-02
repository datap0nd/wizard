"""Step 02 spike: prove two enterprise users run Gemini through Wizard with separate identity, state and tool calls.

What it does, for each of two Wizard users:
  1. checks the user's own Gemini sign-in exists inside their own home (never the operator's ~/.gemini)
  2. runs one real headless question through Wizard's chosen runtime (gemini-cli or code-assist) with SYNTHETIC tools
  3. records model, session id, tool calls, evidence ids, latency and the Google account linked to that user
Then it compares the two users: distinct homes, distinct credential files, no cross-user files, separate run traces.
Writes artifacts/step02-spike-<timestamp>.json and .md for the decision record (docs/decisions/).

Real run (on the intended host, after each user linked their own account in Wizard):
  uv run python scripts/spike_two_users.py --runtime gemini-cli --identities path/to/two-real-users.json \
      --user u-alice --user u-bob --data-dir D:/wizard-data
Offline harness check (no Google, fake model replies):
  uv run python scripts/spike_two_users.py --fake"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for sub in ("api", "agent", "connectors", "checks"):
    sys.path.insert(0, str(ROOT / "services" / sub))

import httpx  # noqa: E402
import uvicorn  # noqa: E402

from wizard_api.app import create_app  # noqa: E402
from wizard_api.config import load_settings  # noqa: E402

QUESTION = "Which sources can you use? Then read last quarter's marketing spend by market and tell me the largest."


def sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.is_file() else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runtime", choices=["gemini-cli", "code-assist"], default="gemini-cli")
    parser.add_argument("--user", action="append", default=[])
    parser.add_argument("--identities", default=str(ROOT / "fixtures" / "identities.json"))
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--fake", action="store_true", help="offline: fake model replies, test identities")
    args = parser.parse_args()
    users = args.user or ["u-ceo", "u-cfo"]
    if len(users) != 2 or users[0] == users[1]:
        parser.error("give exactly two different --user ids")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    data_dir = Path(args.data_dir or ROOT / "artifacts" / f"step02-data-{stamp}")
    env = {"WIZARD_DATA_DIR": str(data_dir), "WIZARD_PORT": str(args.port), "WIZARD_AGENT_RUNTIME": args.runtime,
           "WIZARD_IDENTITIES_FILE": args.identities}
    if args.fake:
        env.update({"WIZARD_AGENT_RUNTIME": "gemini-cli",
                    "WIZARD_GEMINI_FAKE_RESPONSES": str(ROOT / "fixtures" / "gemini_fake" / "ceo-two-tools.jsonl")})
    settings = load_settings(env=env, env_file=data_dir / "none.env")
    app = create_app(settings)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)

    results = []
    for user in users:
        client = httpx.Client(base_url=settings.internal_url, headers={"X-Wizard-Request": "1"}, timeout=60)
        client.post("/api/v1/session/login", json={"user_id": user}).raise_for_status()
        boot = client.get("/api/v1/bootstrap").json()
        started = time.monotonic()
        run_id = client.post("/api/v1/runs", json={"question": QUESTION}).json()["run_id"]
        while True:
            run = client.get(f"/api/v1/runs/{run_id}").json()
            if run["status"] in ("succeeded", "failed", "cancelled"):
                break
            time.sleep(0.5)
        home = settings.user_home(user)
        gemini_home = home / "gemini" / ".gemini"
        results.append({
            "user": user, "email": boot["identity"]["email"], "runtime": boot["runtime"],
            "gemini_account": boot["gemini_account"], "status": run["status"], "error": run.get("error_message"),
            "model_reported": run.get("model"), "session_id": run.get("session_id"),
            "latency_s": round(time.monotonic() - started, 1),
            "tools": [e["payload"]["name"] for e in run["events"] if e["type"] == "tool_finished"],
            "evidence": [e["id"] for e in run["evidence"]],
            "home": str(home), "credential_file_hash": sha(gemini_home / "gemini-credentials.json") or sha(gemini_home / "oauth_creds.json"),
            "session_files": sorted(p.name for p in (gemini_home / "tmp").rglob("*.json"))[:20] if (gemini_home / "tmp").exists() else [],
        })
    server.should_exit = True

    a, b = results
    checks = {
        "both_runs_succeeded": a["status"] == b["status"] == "succeeded",
        "distinct_homes": a["home"] != b["home"],
        "each_user_has_own_credentials": bool(a["credential_file_hash"] and b["credential_file_hash"]) or args.fake,
        "credentials_differ": (a["credential_file_hash"] != b["credential_file_hash"]) or args.fake,
        "distinct_sessions": a["session_id"] != b["session_id"],
        "linked_accounts_match_users": args.fake or all(
            (r["gemini_account"].get("google_email") or "").lower() == r["email"].lower() for r in results),
        "tools_called_for_each_user": bool(a["tools"]) and bool(b["tools"]),
        "operator_home_untouched": not any(str(Path.home() / ".gemini") in r["home"] for r in results),
    }
    report = {"generated_at": stamp, "mode": "offline-fake" if args.fake else "live", "runtime": args.runtime,
              "question": QUESTION, "checks": checks, "users": results,
              "not_proven_by_this_script": ["which account Google bills/attributes (confirm in the Google admin console)",
                                            "enterprise policy approval for this runtime", "browser sign-in from remote PCs"]}
    out = ROOT / "artifacts" / f"step02-spike-{stamp}"
    out.with_suffix(".json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = [f"# Step 02 two-user spike ({report['mode']}, {args.runtime}) — {stamp}", "",
             *[f"- {'PASS' if ok else 'FAIL'} {name}" for name, ok in checks.items()], "",
             *[f"- {r['user']} ({r['email']}): {r['status']}, model {r['model_reported']}, session {r['session_id']}, "
               f"{len(r['tools'])} tool calls, {r['latency_s']} s" for r in results], "",
             "Not proven here: " + "; ".join(report["not_proven_by_this_script"]) + "."]
    out.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
