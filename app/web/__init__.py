"""Server-rendered pages and htmx fragments.

Everything under `/` that returns HTML rather than JSON. See `router.py` for
the single combined router `app.main` includes, and `templating.py` for the
Jinja environment both `pages.py` and `fragments.py` render through.
"""

from __future__ import annotations
