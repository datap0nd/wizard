# 2026-10-02 — Development dependency constraints

**Owner:** builder. **Status:** applied.

**Context.** The development PC enforces Windows Application Control, which blocks some unsigned native binaries.

**Decisions.**
- **No Python MCP SDK.** `mcp` pulls `cryptography`, which has no Windows-ARM wheel here, and its Rust build is blocked.
  The MCP stdio server (`wizard_connectors/mcp_shim.py`) is a small JSON-RPC implementation over stdlib + httpx, tested
  with a JSON-RPC client and with the real Gemini CLI as MCP client. It also means one fewer dependency to approve.
- **lightningcss pinned to 1.32.0** via npm `overrides`: the 1.33.0 native binary used by Vite is blocked; 1.32.0 is allowed.
- **TypeScript 5.9.3** (B2B's version) instead of the native TypeScript 7 compiler.
- **pytest via `python -m pytest`** with the tmpdir plugin disabled (`-p no:tmpdir`): the `pytest.exe` shim is blocked
  and pytest's temp-dir symlinks are disabled by policy. Tests use a plain temporary-directory fixture.
- **mypy**: the compiled wheel is blocked on this PC. A source build (`uv pip install --no-binary mypy mypy==2.4.0`) runs
  locally; a fresh `uv sync` may reinstall the blocked wheel, in which case `verify_all.sh` reports types as BLOCKED
  (never skipped). CI on Linux always runs it.
- **2026-10-05: Smart App Control turned On on the development laptop.**
  - **Now blocked:** `uv.exe` and the arm64 `pydantic_core` DLL, in both the project venv and the system Python. Windows
    switches Smart App Control from evaluation mode to On by itself. The security setting stays unchanged.
  - **Still running:** the portable amd64 runtime the work PC uses (python.org embeddable zip plus the locked wheels),
    `ruff`, node and git.
  - **Portable runtime:** `scripts/lock_portable.py` now needs only `python -m pip` (no uv) and keeps existing pins as
    constraints.
  - **Local tests:** run with that portable runtime plus pure-Python pytest wheels. Two contract tests start the shim
    with `-m` from a working directory, which the embeddable Python ignores by design, so they only run in CI.
  - **CI is the type gate:** mypy runs there.

**Consequence.** Revisit when IT allowlists newer builds; record any change here.
