"""The company's GitHub Enterprise Server, where the knowledge-base repository lives.

Fixed by the owner (20 October 2026): the desktop sync, Settings' Test connection and docs.ps1 kb-publish / kb-check
talk only to this server, never to public github.com, and no setting, provisioning file or .env value changes it. The
app's own updates are different: they come from the public release of this repository on github.com."""
from __future__ import annotations

WEB = "https://github.sec.samsung.net"
API = f"{WEB}/api/v3"
