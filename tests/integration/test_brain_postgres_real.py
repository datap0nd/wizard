"""The Brain page's news queries against a real PostgreSQL server (CI runs a PostgreSQL service; elsewhere BLOCKED): the
news table is found, its fixed queries run as written (counts, categories from an array column, weeks, the latest
articles), and the account only needs to read."""
from __future__ import annotations

import os
import secrets

import pytest

from wizard_api import brain
from wizard_connectors.pg import PgSettings
from wizard_connectors.postgres_query import PostgresQuery

HOST = os.environ.get("WIZARD_TEST_PG_HOST")
pytestmark = [pytest.mark.postgres,
              pytest.mark.skipif(not HOST, reason="BLOCKED: no PostgreSQL test server (WIZARD_TEST_PG_HOST, "
                                                  "WIZARD_TEST_PG_USER, WIZARD_TEST_PG_PASSWORD)")]


@pytest.fixture(scope="module")
def postgres():
    pg8000 = pytest.importorskip("pg8000.native", reason="BLOCKED: pg8000 is not installed")
    admin = pg8000.Connection(os.environ.get("WIZARD_TEST_PG_USER", "postgres"), host=HOST,
                              port=int(os.environ.get("WIZARD_TEST_PG_PORT", "5432")),
                              password=os.environ.get("WIZARD_TEST_PG_PASSWORD"), ssl_context=False)
    password = secrets.token_hex(12)
    for statement in [
        "DROP SCHEMA IF EXISTS brain_news CASCADE", "DROP ROLE IF EXISTS wizard_brain_reader",
        "CREATE SCHEMA brain_news",
        "CREATE TABLE brain_news.news (id serial PRIMARY KEY, headline text, topics text[], outlet text, link text, "
        "published_at timestamptz, created_at timestamptz DEFAULT now())",
        "INSERT INTO brain_news.news (headline, topics, outlet, link, published_at, created_at) VALUES "
        "('Rival cuts prices', ARRAY['Competitors', 'Pricing'], 'Wire', 'https://news.example/1', now() - interval '2 days', now() - interval '2 days'), "
        "('Operator launches 5G plans', ARRAY['Telecom'], 'Wire', 'https://news.example/2', now() - interval '1 hour', now() - interval '1 hour'), "
        "('Old story', ARRAY['Competitors'], 'Wire', 'ftp://old', now() - interval '40 days', now() - interval '40 days'), "
        "('No topic yet', NULL, NULL, NULL, NULL, now())",
        f"CREATE ROLE wizard_brain_reader LOGIN PASSWORD '{password}'",
        "GRANT USAGE ON SCHEMA brain_news TO wizard_brain_reader",
        "GRANT SELECT ON ALL TABLES IN SCHEMA brain_news TO wizard_brain_reader",
    ]:
        admin.run(statement)
    database = admin.run("SELECT current_database()")[0][0]
    yield PostgresQuery(PgSettings(HOST, int(os.environ.get("WIZARD_TEST_PG_PORT", "5432")), database, "wizard_brain_reader",
                                   password, "prefer", "test"))
    for statement in ["DROP SCHEMA brain_news CASCADE", "DROP OWNED BY wizard_brain_reader", "DROP ROLE wizard_brain_reader"]:
        admin.run(statement)
    admin.close()


def test_the_news_table_is_read_live(postgres):
    news = brain.read_news(postgres, "brain_news.news")
    assert news["status"] == "ok" and news["table"] == "brain_news.news"
    assert news["columns"] == {"title": "headline", "category": "topics", "date": "published_at", "added": "created_at",
                               "source": "outlet", "url": "link"}
    # Recency and weeks count by publication date (the row without one is in the total only).
    assert news["total"] == 4 and news["last_7_days"] == 2 and news["last_day"] == 1 and news["last_added"]
    assert {c["name"]: c["count"] for c in news["categories"]} == {"Competitors": 2, "Pricing": 1, "Telecom": 1}
    assert sum(w["count"] for w in news["weekly"]) == 3 and news["weekly"] == sorted(news["weekly"], key=lambda w: w["week"])
    titles = [item["title"] for item in news["latest"]]
    assert titles[:3] == ["Operator launches 5G plans", "Rival cuts prices", "Old story"] and titles[-1] == "No topic yet"
    assert news["latest"][1]["category"] == "Competitors, Pricing"
    assert news["latest"][2]["url"] is None, "only web links open from the page"


def test_the_news_table_is_found_by_name_and_the_database_counted(postgres):
    found = brain.find_news(postgres)
    assert found is not None and "news" in found.name
    counted = brain.read_database(postgres)
    assert counted["status"] == "ok" and counted["relations"] >= 1 and counted["schemas"] >= 1
