from __future__ import annotations

import httpx
import pytest

from wizard_connectors.asap_library import AsapError, LibraryClient, normalise_grid

V2_RESULT = {
    "definition": {"grid": {
        "rows": [{"name": "Market", "elements": [{"formValues": ["SA"]}, {"formValues": ["AE"]}]},
                 {"name": "Quarter", "elements": [{"formValues": ["2026-Q3"]}]}],
        "columns": [{"type": "templateMetrics", "elements": [{"name": "Sell-out"}, {"name": "Share %"}]}]}},
    "data": {"paging": {"total": 2}, "headers": {"rows": [[0, 0], [1, 0]]}, "metricValues": {"raw": [[452000, 32.0], [205000, 27.2]]}},
}


def test_normalise_v2_grid():
    grid = normalise_grid(V2_RESULT)
    assert grid.columns == ["Market", "Quarter", "Sell-out", "Share %"]
    assert grid.rows == [["SA", "2026-Q3", 452000, 32.0], ["AE", "2026-Q3", 205000, 27.2]]
    assert grid.total_rows == 2


def test_library_client_request_shapes():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.headers.get("X-MSTR-ProjectID")))
        if request.url.path.endswith("/api/auth/delegate"):
            return httpx.Response(204, headers={"X-MSTR-AuthToken": "t"})
        if request.url.path.endswith("/instances") and request.method == "POST":
            return httpx.Response(200, json={"instanceId": "i1", "status": 2})
        return httpx.Response(200, json=V2_RESULT)

    client = LibraryClient("https://asap.example.invalid/MicroStrategyLibrary", "P1", transport=httpx.MockTransport(handler))
    client.login_delegated("identity-token")
    grid = client.read_rows("R1", [{"key": "market", "answers": ["SA"]}])
    assert grid.rows[0][0] == "SA"
    assert ("PUT", "/MicroStrategyLibrary/api/reports/R1/instances/i1/prompts/answers", "P1") in seen
    assert all(method != "DELETE" for method, _, _ in seen)


def test_library_client_refuses_plain_http_and_maps_denials():
    with pytest.raises(AsapError):
        LibraryClient("http://asap.example.invalid", "P1")
    client = LibraryClient("https://asap.example.invalid", "P1", transport=httpx.MockTransport(lambda r: httpx.Response(403)))
    client.token = "t"
    with pytest.raises(AsapError) as error:
        client.folder("F1")
    assert error.value.code == "not_permitted"


def test_knowledge_notes_are_unsigned_drafts_and_searchable(services):
    notes = services.knowledge.notes
    assert notes and all(n.status in ("DRAFT_UNSIGNED", "SIGNED") for n in notes)
    assert services.knowledge.search("ROI return marketing")[0].id == "investment-efficiency-proxy"
    assert services.knowledge.search("smart switch coverage")[0].id == "observed-switchers"


def test_catalog_importer_drafts_navigation_only_contract():
    from scripts.import_asap_catalog import build

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/folders/ROOT"):
            return httpx.Response(200, json=[{"id": "SUB", "name": "Consumer", "type": 8},
                                             {"id": "D1", "name": "Exec dossier", "type": 55}])
        if path.endswith("/folders/SUB"):
            return httpx.Response(200, json=[{"id": "R1", "name": "Smart Switch by origin", "type": 3}])
        if path.endswith("/v2/reports/R1"):
            return httpx.Response(200, json={"definition": {"availableObjects": {
                "attributes": [{"name": "Market"}, {"name": "Origin Brand"}], "metrics": [{"name": "Transfers"}]}}})
        return httpx.Response(404)

    client = LibraryClient("https://asap.example.invalid/Library", "P1", transport=httpx.MockTransport(handler))
    client.token = "t"
    draft = build(client, [("ROOT", "Shared Reports")])
    assert draft["draft"] is True and [f["name"] for f in draft["folders"]] == ["Shared Reports", "Consumer"]
    report = next(r for r in draft["reports"] if r["name"] == "Smart Switch by origin")
    assert report["row_access"] == "NAVIGATION_ONLY" and report["file"] is None
    assert [d["key"] for d in report["dimensions"]] == ["market", "origin_brand"]
    assert report["measures"] == [{"key": "transfers", "label": "Transfers", "type": "number", "aggregation": "none"}]
    assert next(r for r in draft["reports"] if r["name"] == "Exec dossier")["type"] == "dossier"


def test_platform_guides_are_reachable_through_tools(registry, context):
    sources = registry.execute("wizard_list_sources", {}, context("u-ceo")).data["sources"]
    assert all(s["platform_guide"] and s["how_to_navigate"].startswith(s["system"]) for s in sources)
    found = registry.execute("wizard_lookup_definitions", {"query": "ASAP platform dossier prompts"}, context()).data
    assert found["definitions"][0]["id"] == "platform-asap"
