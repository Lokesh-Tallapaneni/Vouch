"""Every server-rendered route, combined into one router.

Mirrors app.api.v1.router: main.py includes exactly one router from this
package rather than reaching into app.web.pages and app.web.fragments
separately, so adding a third web module later is a one-line change here,
not a second edit to app.main -- which the standing instruction for this
task keeps off-limits anyway.

Unlike app.api.v1.router, no prefix is applied here: pages sit at the site
root (`/`, `/people/{id}`, ...) and fragments already carry their own
`/fragments` prefix, declared once in fragments.py. Nothing above this
module needs to know either detail.
"""

from __future__ import annotations

from veloce import Router

from app.web import fragments, pages

router = Router()
router.include_router(pages.router)
router.include_router(fragments.router)
