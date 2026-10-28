"""The Brain page's data (/api/v1/brain, /api/v1/brain/live): the knowledge map is read from the loaded notes, links and
catalogs; the news table is found by name and read with fixed queries, each in its own read-only transaction that is
rolled back, only for people who may read the whole database."""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tests.helpers import login, make_settings
from tests.unit.test_postgres_query import SETTINGS

from wizard_api import brain
from wizard_api.app import create_app
from wizard_connectors.fixture_source import SourceError
from wizard_connectors.knowledge import KnowledgeBase, Note
from wizard_connectors.postgres_query import PostgresQuery

CATALOG = [  # schema, relation, column, type: what the catalog query returns
    ("public", "news", "id", "integer"), ("public", "news", "headline", "text"), ("public", "news", "category", "text"),
    ("public", "news", "source", "character varying(200)"), ("public", "news", "link", "text"),
    ("public", "news", "summary", "text"), ("public", "news", "country", "text"),
    ("public", "news", "published_at", "timestamp with time zone"), ("public", "news", "created_at", "timestamp without time zone"),
    ("ops", "news_staging", "title", "text"), ("ops", "news_staging", "raw", "jsonb"),
]


def note(note_id: str, area: str, tags: tuple[str, ...], **extra: Any) -> Note:
    return Note(id=note_id, title=note_id.replace("-", " ").title(), status=extra.pop("status", "DRAFT_UNSIGNED"),
                owner="TBD", tags=tags, body=extra.pop("body", "Lead."), path=f"knowledge/{area}/{note_id}.md", **extra)


class NewsSession:
    """A PostgreSQL session that answers the Brain page's queries from canned rows and records every statement."""

    log: list[str] = []

    def __init__(self, catalog: list[tuple[str, str, str, str]] | None = None) -> None:
        self.catalog = CATALOG if catalog is None else catalog
        self.closed = False

    def rows(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        self.log.append(sql)
        return []

    def query(self, sql: str) -> tuple[list[dict[str, Any]], list[list[Any]]]:
        self.log.append(sql)
        def answer(names: list[str], rows: list[list[Any]]) -> tuple[list[dict[str, Any]], list[list[Any]]]:
            return [{"name": n, "type_oid": 25} for n in names], rows
        if "pg_catalog.pg_attribute" in sql:
            return answer(["schema", "name", "column", "type"], [list(r) for r in self.catalog])
        if "pg_catalog.pg_database" in sql:
            return answer(["datname"], [])
        if "count(DISTINCT schema)" in sql:
            return answer(["relations", "schemas"], [[412, 9]])
        if "AS last_7_days" in sql:
            return answer(["total", "first", "last", "last_added", "last_7_days", "last_day"],
                          [[1512, dt.datetime(2026, 5, 31, 17, 50), dt.datetime(2026, 10, 28, 8, 0), dt.datetime(2026, 10, 28, 8, 5), 90, 12]])
        if "GROUP BY 1 ORDER BY 2 DESC, 1" in sql:
            return answer(["name", "count"], [["Competitors", 342], ["Smartphones", 285], [None, 3]])
        if "date_trunc('week'" in sql:
            return answer(["week", "count"], [[dt.date(2026, 10, 26), 40], [dt.date(2026, 10, 19), 61]])
        if "AS title" in sql:
            return answer(["title", "category", "source", "url", "summary", "market", "date"],
                          [["Rival launches a foldable", "Competitors", "Wire", "https://news.example/1", "Short.", "AE", dt.datetime(2026, 10, 28, 8)],
                           ["Odd link", "Smartphones", "Wire", "javascript:alert(1)", None, "SA", dt.datetime(2026, 10, 27, 8)]])
        raise AssertionError(f"unexpected query: {sql}")

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def postgres() -> PostgresQuery:
    NewsSession.log = []
    return PostgresQuery(SETTINGS, connect=lambda s, d: NewsSession())


def test_the_map_counts_notes_links_terms_and_what_each_system_is_documented_by():
    kb = KnowledgeBase([
        note("platform-gscm", "platforms", ("gscm", "sell-in", "stock"), type="platform"),
        note("bi-sell-in-mv", "datasets", ("sell-in", "weekly"), type="dataset", related=("sell-in", "missing-note")),
        note("sell-in", "metrics", ("sell-in", "stock", "weekly"), type="metric", status="SIGNED", reviewed="2026-10-01"),
        note("sales-terms", "glossary", ("terms",), type="glossary", reviewed="2026-10-02",
             body="Terms.\n\n- **GSCM**: Global Supply Chain Management.\n- **SI**: sell-in."),
    ])
    systems = [{"id": "gscm", "name": "GSCM", "kind": "portal"}, {"id": "postgresql", "name": "AI Team Database", "kind": "database"},
               {"id": "knowledge", "name": "Knowledge base", "kind": "knowledge"}]
    found = brain.knowledge_map(kb, systems, {"gscm": 12}, "company")
    assert [a["id"] for a in found["areas"]] == ["platforms", "datasets", "metrics", "glossary"], "the standard's order"
    assert found["areas"][1]["name"] == "Data dictionary"
    by_id = {n["id"]: n for n in found["notes"]}
    assert by_id["sell-in"]["stage"] == "SIGNED" and by_id["sales-terms"]["stage"] == "EXPERT_CHECKED"
    assert by_id["bi-sell-in-mv"]["stage"] == "DRAFT" and by_id["sales-terms"]["terms"] == 2
    links = {(link["source"], link["target"]): link["kind"] for link in found["links"]}
    assert links[("bi-sell-in-mv", "sell-in")] == "related", "a note's own link, to a note that exists"
    assert links[("platform-gscm", "sell-in")] == "shared", "two tags in common"
    assert not any("missing-note" in pair for pair in links)
    documented = {s["id"]: s["documented_by"] for s in found["systems"]}
    assert documented == {"gscm": ["platform-gscm"], "postgresql": ["bi-sell-in-mv"], "knowledge": []}
    assert found["systems"][0]["reports"] == 12 and found["systems"][1]["reports"] is None
    assert found["counts"] == {"notes": 4, "areas": 4, "links": len(links), "related": 1, "glossary_terms": 2, "datasets": 1,
                               "metrics": 1, "signed": 1, "expert_checked": 1, "reports": 12, "systems": 3}


def test_news_columns_are_matched_by_name_and_dates_must_be_dates():
    columns, arrays = brain.match_columns([("headline", "text"), ("topics", "text[]"), ("date", "text"),
                                           ("inserted_at", "timestamp with time zone"), ("article_url", "text"),
                                           ("source_url", "text"), ("body", "text")])
    assert columns == {"title": "headline", "category": "topics", "date": "inserted_at", "added": "inserted_at",
                       "url": "article_url", "summary": "body"}, "a text 'date' is not a date; the insert time stands in"
    assert arrays == frozenset({"category"})
    contains, _ = brain.match_columns([("news_headline", "text"), ("article_category", "text"), ("title_id", "integer")])
    assert contains["title"] in ("news_headline", "title_id") and contains["category"] == "article_category"


def test_the_table_called_news_wins_and_a_table_needs_a_title():
    chosen = brain.pick_table([list(r) for r in CATALOG], "meto_db")
    assert chosen and (chosen.schema, chosen.name, chosen.database) == ("public", "news", "meto_db")
    assert chosen.columns["title"] == "headline" and chosen.columns["date"] == "published_at" and chosen.columns["added"] == "created_at"
    assert brain.pick_table([("ops", "news_raw", "payload", "jsonb")], "meto_db") is None


def test_news_queries_quote_names_and_unnest_array_categories():
    table = brain.NewsTable("db", "My Schema", "news", {"title": "Title", "category": "tags", "date": "published"}, frozenset({"category"}))
    queries = brain.news_queries(table)
    assert queries["summary"].endswith('FROM "My Schema".news')
    assert 'unnest(t."tags")' in queries["categories"]
    assert 'left(array_to_string("tags", \', \'), 160) AS category' in queries["latest"] and 'ORDER BY "published" DESC NULLS LAST' in queries["latest"]
    undated = brain.news_queries(brain.NewsTable("db", "public", "news", {"title": "title"}, frozenset()))
    assert set(undated) == {"summary", "latest"} and "ORDER BY" not in undated["latest"]


def test_reading_the_news_runs_each_query_read_only_and_rolled_back(postgres):
    news = brain.read_news(postgres)
    assert news["status"] == "ok" and news["table"] == "public.news" and news["total"] == 1512 and news["last_7_days"] == 90
    assert news["categories"][-1] == {"name": "Uncategorised", "count": 3}
    assert [w["week"] for w in news["weekly"]] == ["2026-10-19", "2026-10-26"], "oldest first"
    assert news["latest"][0]["url"] == "https://news.example/1" and news["latest"][1]["url"] is None, "only web links"
    assert news["data_mode"] == "LIVE" and len(news["queries"]) == 4
    sent = NewsSession.log
    assert sent.count("START TRANSACTION READ ONLY") == sent.count("ROLLBACK") == 5, "the catalog lookup and four queries"
    assert all(s.startswith("SELECT * FROM (") for s in sent if s not in ("START TRANSACTION READ ONLY", "ROLLBACK"))
    assert all("insert" not in s.lower() and "update " not in s.lower() for s in sent)


def test_a_configured_table_is_checked_and_a_missing_one_is_explained(postgres):
    with pytest.raises(SourceError, match="WIZARD_NEWS_TABLE"):
        brain.read_news(postgres, "news; DROP TABLE x")
    with pytest.raises(SourceError, match="WIZARD_NEWS_DATABASE"):
        brain.read_news(postgres, None, "db name")
    brain.read_news(postgres, "public.news")
    assert any("lower(c.relname) = lower('news') AND lower(n.nspname) = lower('public')" in s for s in NewsSession.log)
    empty = PostgresQuery(SETTINGS, connect=lambda s, d: NewsSession(catalog=[]))
    missing = brain.read_news(empty)
    assert missing["status"] == "not_found" and "WIZARD_NEWS_TABLE" in missing["message"]


def test_the_server_is_read_at_most_once_a_while_and_errors_are_shown():
    calls: list[int] = []
    cache = brain.LiveCache(seconds=60)
    first = cache.get("k", lambda: calls.append(1) or {"status": "ok"})
    assert cache.get("k", lambda: calls.append(1) or {"status": "ok"}) is first and calls == [1]
    def broken() -> dict[str, Any]:
        raise SourceError("source_unavailable", "PostgreSQL is not reachable: timeout")
    assert cache.get("other", broken) == {"status": "error", "message": "PostgreSQL is not reachable: timeout",
                                         "read_at": cache.get("other", broken)["read_at"]}


def test_the_brain_api_shows_what_this_person_may_see(tmp_path: Path):
    with TestClient(create_app(make_settings(tmp_path))) as client:
        assert client.get("/api/v1/brain").status_code == 401
        login(client, "u-ceo")
        found = client.get("/api/v1/brain").json()
        assert found["content"] == "examples" and found["counts"]["notes"] == len(found["notes"]) > 0
        assert {s["id"] for s in found["systems"]} >= {"asap", "gscm", "nerp", "knowledge"}
        assert found["counts"]["reports"] > 0 and "repo" not in str(found.get("knowledge_synced_at"))
        assert client.get("/api/v1/brain/live").json()["news"]["status"] == "not_configured"


def test_only_people_who_may_read_the_whole_database_see_it_live(tmp_path: Path, postgres):
    settings = make_settings(tmp_path, WIZARD_PG_HOST="db.corp", WIZARD_PG_USER="reader", WIZARD_LOCAL_USER_EMAIL="o@corp.test")
    with TestClient(create_app(settings)) as client:
        client.app.state.manager.services.postgres = postgres
        login(client, "u-ceo")
        assert client.get("/api/v1/brain/live").json()["news"]["status"] == "not_allowed"
        login(client, "local-owner")
        live = client.get("/api/v1/brain/live").json()
        assert live["database"] == {"status": "ok", "database": "meto_db", "relations": 412, "schemas": 9, "data_mode": "LIVE",
                                    "read_at": live["database"]["read_at"]}
        assert live["news"]["status"] == "ok" and live["news"]["total"] == 1512 and live["name"] == "AI Team Database"
        sent = len(NewsSession.log)
        client.get("/api/v1/brain/live")
        assert len(NewsSession.log) == sent, "read again only after a while"
