"""Run the draft evaluation cases against a live Wizard runtime and write a review sheet for a human reviewer.

  uv run python scripts/run_evals.py --runtime gemini-cli [--only ceo-01,pl-01] [--data-dir D:/wizard-eval]

Each case runs as its test identity in a fresh conversation (follow-ups reuse the previous case's conversation). The
script records the answer, the tool trace, sources, evidence, latency and check status, and flags heuristics (missing
citations, missing expected terms, forbidden claims). Flags are hints, not verdicts: the owner reviews answer quality
and records failures in docs/eval-log.md. Do not add rules to the agent to satisfy a flag (plan, Step 07)."""
from __future__ import annotations

import argparse
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


def flags(case: dict, run: dict) -> list[str]:
    answer = (run.get("answer") or "").lower()
    out = []
    if run["status"] != "succeeded":
        return [f"run {run['status']}: {run.get('error_code')}"]
    if case["expect"]["cites_evidence"] and "[e" not in answer:
        out.append("no evidence citation")
    out += [f"missing '{m}'" for m in case["expect"]["mentions"] if m.lower() not in answer]
    out += [f"forbidden claim '{m}'" for m in case["expect"]["must_not_claim"] if m.lower() in answer]
    used = {e["system"] for e in run.get("evidence", [])}
    out += [f"did not consult {s.upper()}" for s in case["expect"]["sources"] if s not in used]
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runtime", choices=["gemini-cli", "code-assist", "replay"], default="gemini-cli")
    parser.add_argument("--only", default="")
    parser.add_argument("--data-dir")
    parser.add_argument("--port", type=int, default=8791)
    args = parser.parse_args()
    cases = json.loads((ROOT / "tests" / "evals" / "cases.json").read_text(encoding="utf-8"))["cases"]
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    data_dir = Path(args.data_dir or ROOT / "var")
    settings = load_settings(env={"WIZARD_DATA_DIR": str(data_dir), "WIZARD_PORT": str(args.port), "WIZARD_AGENT_RUNTIME": args.runtime})
    app = create_app(settings)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    results, conversation = [], {}
    for case in cases:
        client = httpx.Client(base_url=settings.internal_url, headers={"X-Wizard-Request": "1"}, timeout=60)
        client.post("/api/v1/session/login", json={"user_id": case["identity"]}).raise_for_status()
        body = {"question": case["prompt"]}
        if case["kind"] == "follow-up" and case["identity"] in conversation:
            body["conversation_id"] = conversation[case["identity"]]
        started = time.monotonic()
        response = client.post("/api/v1/runs", json=body)
        if response.status_code != 200:
            results.append({"case": case, "run": {"status": "rejected", "error_code": response.text}, "flags": ["not started"]})
            continue
        run_id = response.json()["run_id"]
        while (run := client.get(f"/api/v1/runs/{run_id}").json())["status"] not in ("succeeded", "failed", "cancelled"):
            time.sleep(0.5)
        conversation[case["identity"]] = run["conversation_id"]
        tools = [e["payload"]["name"] for e in run["events"] if e["type"] == "tool_finished"]
        results.append({"case": case, "latency_s": round(time.monotonic() - started, 1), "tools": tools,
                        "run": {k: run.get(k) for k in ("id", "status", "error_code", "answer", "model", "check_status", "data_mode", "report_id")}
                        | {"evidence": run["evidence"]}, "flags": flags(case, run)})
        print(f"{case['id']}: {run['status']} · {len(tools)} tools · {results[-1]['latency_s']} s · flags: {results[-1]['flags'] or 'none'}")
    server.should_exit = True
    out = ROOT / "artifacts" / "evals"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"evals-{stamp}.json").write_text(json.dumps({"runtime": args.runtime, "model": settings.model, "results": results},
                                                        indent=2, default=str), encoding="utf-8")
    sheet = [f"# Evaluation review sheet — {stamp} ({args.runtime}, {settings.model})", "",
             "Reviewer: fill Verdict (correct / partly / wrong) and Failure category per docs/eval-log.md.", "",
             "| Case | Status | Tools | Latency | Flags | Verdict | Failure category |", "|---|---|---|---|---|---|---|"]
    sheet += [f"| {r['case']['id']} | {r['run']['status']} | {len(r.get('tools', []))} | {r.get('latency_s', '-')} s | "
              f"{'; '.join(r['flags']) or '—'} | | |" for r in results]
    (out / f"evals-{stamp}.md").write_text("\n".join(sheet) + "\n", encoding="utf-8")
    print(f"Wrote artifacts/evals/evals-{stamp}.json and .md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
