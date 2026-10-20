"""A small fake portal for the portal-browser tests, shaped like a report portal: folders, a report list drawn with
clickable <div>s, a prompt form, a report table and an ARIA grid, a sign-in page, and the things Wizard must refuse or stop
(an export button, a download link, a link to another host, a password field, a SQL editor, a pop-up).

Run it to try the click preview by hand (synthetic data only):
    uv run python -m tests.portal_site 8790
    WIZARD_PORTAL_DEMO=http://127.0.0.1:8790/ in .env, then ask Wizard to look something up on the DEMO portal."""
from __future__ import annotations

import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

STYLE = """<style>body{font-family:sans-serif;margin:24px} .item{cursor:pointer;padding:6px;border:1px solid #ccc;margin:4px;
width:300px} table{border-collapse:collapse} td,th{border:1px solid #999;padding:4px 8px}</style>"""


def page(title: str, body: str) -> bytes:
    return f"<!doctype html><html><head><title>{title}</title>{STYLE}</head><body><h1>{title}</h1>{body}</body></html>".encode()


class Site:
    def __init__(self) -> None:
        self.requests: list[str] = []
        self.other_host_hits: list[str] = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.handler())
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}/"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> Site:
        self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.server.shutdown()
        self.server.server_close()

    def handler(self) -> type[BaseHTTPRequestHandler]:
        site = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_: object) -> None:
                pass

            def send(self, body: bytes, status: int = 200, headers: dict[str, str] | None = None) -> None:
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:  # noqa: N802
                site.requests.append("POST " + self.path)
                self.send(page("Saved", "<p>Something was changed.</p>"))

            def do_GET(self) -> None:  # noqa: N802
                url = urlsplit(self.path)
                site.requests.append("GET " + self.path)
                if self.headers.get("Host", "").split(":")[0] != "127.0.0.1":
                    site.other_host_hits.append(self.path)
                query = parse_qs(url.query)
                routes = {
                    "/": lambda: page("Reports home", (
                        '<a href="/folder/sell-in">Sell-in reports</a> <a href="/folder/share">Market share</a> '
                        '<button onclick="fetch(\'/saved\', {method: \'POST\'})">Export all</button> '
                        '<a href="/files/all.csv" download>Get CSV</a> '
                        f'<a href="http://localhost:{site.port}/elsewhere">Partner site</a> '
                        '<a href="/popup" target="_blank">Open in new tab</a> '
                        '<button onclick="alert(\'hello\')">Say hello</button>'
                        '<p>' + " ".join(["Plenty of text."] * 5) + '</p>')),
                    "/folder/sell-in": lambda: page("Sell-in reports", (
                        '<div class="item" onclick="location.href=\'/report/sell-in-monthly\'">Sell-in by model and month</div>'
                        '<div class="item" onclick="location.href=\'/report/grid\'">Channel stock grid</div>'
                        '<form action="/search" method="get"><input name="q" aria-label="Search reports">'
                        '<select name="market" aria-label="Market"><option>SA</option><option>AE</option></select></form>'
                        '<input type="password" name="pin" aria-label="PIN" style="display:none">'
                        '<textarea class="ace_editor" aria-label="SQL"></textarea>')),
                    "/search": lambda: page("Search results", f'<p>Results for {query.get("q", [""])[0]} in '
                                                              f'{query.get("market", [""])[0]}</p>'
                                                              '<a href="/report/sell-in-monthly">Sell-in by model and month</a>'),
                    "/report/sell-in-monthly": lambda: page("Sell-in by model and month", (
                        '<table aria-label="Sell-in"><thead><tr><th>Market</th><th>Model</th><th>Month</th>'
                        '<th>Sell-in units</th><th>Share</th></tr></thead><tbody>'
                        '<tr><td>SA</td><td>Model A</td><td>2026-07</td><td>1,234</td><td>12.5%</td></tr>'
                        '<tr><td>SA</td><td>Model B</td><td>2026-07</td><td>(56)</td><td>3%</td></tr>'
                        '<tr><td>AE</td><td>Model A</td><td>2026-07</td><td>2,000</td><td>-</td></tr>'
                        '</tbody></table>')),
                    "/report/grid": lambda: page("Channel stock grid", (
                        '<div role="grid" aria-label="Channel stock" aria-rowcount="40">'
                        '<div role="row"><span role="columnheader">Market</span><span role="columnheader">Units</span></div>'
                        '<div role="row"><span role="gridcell">SA</span><span role="gridcell">10</span></div>'
                        '<div role="row"><span role="gridcell">AE</span><span role="gridcell">20</span></div></div>')),
                    "/popup": lambda: page("Pop-up report", "<p>Opened in a new tab.</p>"),
                    "/login": lambda: page("Sign in", '<form><input name="user"><input type="password" name="pw"></form>'),
                }
                signed_in = "sid=demo" in (self.headers.get("Cookie") or "")
                if url.path == "/private":
                    self.send(b"", 302, {"Location": "/login"})
                elif url.path == "/session":  # a portal session in a session cookie (no expiry), as many portals keep it
                    self.send(page("Signed in", "<p>Welcome.</p>"), 200, {"Set-Cookie": "sid=demo; Path=/"})
                elif url.path == "/members":
                    self.send(page("Members area", "<p>Only signed-in people see this.</p>") if signed_in else b"", 200 if signed_in
                              else 302, {} if signed_in else {"Location": "/login"})
                elif url.path in routes:
                    self.send(routes[url.path]())
                elif url.path.startswith("/files/"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/csv")
                    self.send_header("Content-Disposition", "attachment; filename=all.csv")
                    self.end_headers()
                    self.wfile.write(b"a,b\n1,2\n")
                else:
                    self.send(page("Not found", ""), 404)

        return Handler


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8790
    site = Site()
    site.server.server_close()
    site.server = ThreadingHTTPServer(("127.0.0.1", port), site.handler())
    site.port, site.url = port, f"http://127.0.0.1:{port}/"
    print(f"Demo portal on {site.url} (Ctrl+C to stop)")
    site.server.serve_forever()
