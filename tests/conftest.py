from __future__ import annotations

import shutil
import tempfile
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tests.helpers import TEST_TMP, MemoryRecorder, free_port, make_settings

from wizard_api.app import create_app
from wizard_connectors.entitlements import Identity, IdentityDirectory
from wizard_connectors.paths import FIXTURES
from wizard_connectors.tools import Services, ToolContext, ToolRegistry, build_registry, build_services


@pytest.fixture
def tmp_path() -> Iterator[Path]:
    """Plain temporary directory (pytest's tmpdir plugin is disabled: it needs symlinks, which some Windows policies block)."""
    TEST_TMP.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix="t-", dir=TEST_TMP))
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(scope="session")
def services() -> Services:
    return build_services()


@pytest.fixture(scope="session")
def registry(services: Services) -> ToolRegistry:
    return build_registry(services)


@pytest.fixture(scope="session")
def identities() -> IdentityDirectory:
    return IdentityDirectory.load(FIXTURES / "identities.json")


@pytest.fixture
def context(services: Services, identities: IdentityDirectory) -> Callable[[str], ToolContext]:
    def make(user_id: str = "u-ceo") -> ToolContext:
        identity = identities.get(user_id)
        assert isinstance(identity, Identity)
        return ToolContext(identity=identity, run_id="run_test", recorder=MemoryRecorder(), services=services)
    return make


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(make_settings(tmp_path))) as test_client:
        yield test_client


@pytest.fixture
def live_server(tmp_path: Path) -> Iterator[Callable[..., Any]]:
    """Start Wizard on a real loopback port (needed when a child process - MCP shim, Gemini CLI - calls back in)."""
    import threading

    import uvicorn
    servers: list[Any] = []

    def start(**overrides: str) -> Any:
        port = free_port()
        settings = make_settings(tmp_path, WIZARD_PORT=str(port), **overrides)
        app = create_app(settings)
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        threading.Thread(target=server.run, daemon=True).start()
        deadline = time.time() + 20
        while not server.started and time.time() < deadline:
            time.sleep(0.05)
        servers.append(server)
        app.state.base_url = f"http://127.0.0.1:{port}"
        return app

    yield start
    for server in servers:
        server.should_exit = True
