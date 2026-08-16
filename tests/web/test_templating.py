"""Static assets are cache-busted by content digest.

Why this is worth a test rather than trusting the template: the failure is
invisible. Reverting `{{ asset_url('css/vouch.css') }}` to a plain
`/static/css/vouch.css` renders identically, passes every other test, and
only shows up as "my CSS fix didn't deploy" an hour later, on someone
else's machine, in front of an audience.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.web.templating import STATIC_DIR, asset_url


def test_asset_url_carries_a_digest_of_the_file_contents() -> None:
    url = asset_url("css/vouch.css")
    assert url.startswith("/static/css/vouch.css?v=")
    assert re.fullmatch(r"[0-9a-f]{8}", url.split("?v=")[1])


def test_the_digest_changes_when_the_file_does(tmp_path: Path) -> None:
    # The whole point of the digest is that editing a file changes the URL.
    # Exercised against a real file under the static directory rather than a
    # mock, because the thing that can break is the mtime-keyed cache: hash
    # the path alone and the first digest sticks for the life of the
    # process, which is precisely the bug this guards.
    scratch = STATIC_DIR / "css" / "_digest_probe.css"
    try:
        scratch.write_text("a{}", encoding="utf-8")
        first = asset_url("css/_digest_probe.css")
        scratch.write_text("b{color:red}", encoding="utf-8")
        second = asset_url("css/_digest_probe.css")
    finally:
        scratch.unlink(missing_ok=True)

    assert first != second


def test_a_missing_asset_degrades_to_a_plain_path() -> None:
    # A 404ing asset should not also take down every page that references
    # it -- a stylesheet that fails to load is a bad page, an exception is
    # no page at all.
    assert asset_url("css/does-not-exist.css") == "/static/css/does-not-exist.css"
