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
- **mypy** cannot run on this PC (its compiled `librt` module is blocked); it runs in CI on Linux. `verify_all.sh` reports
  it as BLOCKED locally rather than skipping it.

**Consequence.** Revisit when IT allowlists newer builds; record any change here.
