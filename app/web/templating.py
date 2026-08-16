"""The web app's Jinja environment.

Owned here, not in ``app.main``, so ``pages.py``/``fragments.py`` can import
``templates`` without a cycle. ``app.main`` has to import ``app.web`` (to
register its router) once that wiring lands; if ``pages.py`` then imported
``templates`` back out of ``app.main``, the import would only resolve if
``app.main``'s ``templates = Jinja2Templates(...)`` line happened to execute
*before* its own ``from app.web import ...`` line -- fragile to depend on
statement order in a file owned by a different band. A module neither side
depends on the internals of sidesteps that question rather than getting it
right by luck.

``main.py``'s current wiring (as landed) still builds its own
``Jinja2Templates`` at module level and documents that ``app.web.pages``
should import it from there -- written before this module existed. That
line is now dead weight: nothing renders through it once ``pages.py`` and
``fragments.py`` import from here instead. See the Task 19 report for the
one-line fix (replace that assignment with
``from app.web.templating import templates``).
"""

from __future__ import annotations

from hashlib import blake2b
from pathlib import Path

from veloce import Jinja2Templates

from app.web.intro_message import build_intro_message

#: This file is app/web/templating.py -- parent is app/web/, parent.parent
#: is app/, matching app.main's own BASE_DIR.
BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

#: Registered here, once, rather than pre-computed per row in every page
#: handler that renders a route (show_person, show_company): the message
#: only depends on data _chain.html already has in scope wherever a route
#: renders, so _intro_disclosure.html can just call it directly.
templates.env.globals["build_intro_message"] = build_intro_message


def _asset_digest(path: str) -> str:
    """Eight hex characters of the file's content hash.

    Deliberately uncached. The obvious optimisation -- memoise on
    ``(path, st_mtime_ns)`` -- has a hole: two writes inside the
    filesystem's timestamp resolution share an mtime, so the digest sticks
    while the bytes change. That is not hypothetical; it is what
    ``test_the_digest_changes_when_the_file_does`` caught on Windows.

    The failure it produces is precisely the one this whole function exists
    to prevent -- a changed file served under its old URL -- so paying for
    correctness is the right trade. Measured: 0.737 ms to hash all four of
    this app's assets (84 KB), against a ~500 ms database round trip on the
    same page. Revisit if the static payload grows by an order of magnitude.
    """
    return blake2b((STATIC_DIR / path).read_bytes(), digest_size=4).hexdigest()


def asset_url(path: str) -> str:
    """A ``/static`` URL carrying a digest of the file's contents.

    ``path`` is relative to the static directory (``"css/vouch.css"``), the
    same way it appears in the URL.

    Static assets are served with ``max-age=3600`` and no revalidation, so a
    plain ``/static/css/vouch.css`` keeps returning visitors on the previous
    stylesheet for up to an hour after a deploy -- the fix ships, the browser
    ignores it, and the page looks broken in exactly the situation where
    someone is watching. Keying the URL to the content means a changed file
    is a different URL and is fetched immediately, while an unchanged one
    stays cached for the full hour, which is the point of the header.

    Falls back to the bare path if the file is missing rather than raising:
    an asset that 404s should not also take the whole page down with it.
    """
    try:
        return f"/static/{path}?v={_asset_digest(path)}"
    except OSError:
        return f"/static/{path}"


templates.env.globals["asset_url"] = asset_url
