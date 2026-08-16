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

from pathlib import Path

from veloce import Jinja2Templates

#: This file is app/web/templating.py -- parent is app/web/, parent.parent
#: is app/, matching app.main's own BASE_DIR.
BASE_DIR = Path(__file__).resolve().parent.parent

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
