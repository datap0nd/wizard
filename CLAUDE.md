# CLAUDE.md

Read and follow [AGENTS.md](AGENTS.md). It holds the repository rules (agent-first design, read-only tools, per-user
Gemini identity, honest data modes, no corporate data in Git) and the verification commands.

Quick commands:

```bash
uv sync
uv run python scripts/verify_spec.py
uv run python -m pytest tests            # never the pytest.exe shim on Application-Control PCs
npm --prefix apps/web run typecheck && npm --prefix apps/web test
scripts/verify_all.sh --allow-blocked=live-parity
```
