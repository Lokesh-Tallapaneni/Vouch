"""Version 1 of the JSON API.

Every v1 endpoint hangs off this one router, so the version prefix is declared
in exactly one place. Adding a v2 later means a second router beside this one,
with v1 left serving its existing clients unchanged -- which is the entire
point of putting the version in the path rather than in a header or, worse,
nowhere.

Resource naming follows the usual REST conventions, and they are conventions
worth stating because they are what makes the surface predictable:

* Collections are plural nouns -- ``/people``, ``/companies``.
* A path segment identifies a resource; it never names an action. There is no
  ``/getPerson`` and no ``/findRoute``.
* Sub-resources hang off their parent -- ``/companies/{name}/insiders`` reads
  as "the insiders of this company", which is exactly the query it runs.
* Filters and options are query parameters, not path segments, because they are
  optional and unordered.

Note what is *not* here: ``/health`` and ``/ready`` are unversioned and live in
``app.api.health``. They are a contract with the platform, not with API
clients.
"""

from __future__ import annotations

from veloce import Router

from app.api.v1 import auth, companies, people

API_V1_PREFIX = "/api/v1"

router = Router(prefix=API_V1_PREFIX)

# `Router(prefix=...)` only applies its prefix to routes registered directly
# on that router via `@router.get(...)`/`@router.post(...)` -- it plays no
# part in `include_router`, which only combines the *explicit* `prefix=`
# argument with the child router's own (already-prefixed) tree. Since nothing
# is ever registered directly on this router, `API_V1_PREFIX` has to be passed
# explicitly at every `include_router` call below, or it silently never
# applies and every v1 route 404s at its un-prefixed path.
router.include_router(auth.router, prefix=API_V1_PREFIX)  # /api/v1/auth
router.include_router(people.router, prefix=API_V1_PREFIX)  # /api/v1/people
router.include_router(companies.router, prefix=API_V1_PREFIX)  # /api/v1/companies

# Remaining endpoint modules are included below as they land. Each owns one
# resource and registers its own child router with its own tag:
#
#   from app.api.v1 import introductions, network
#
#   router.include_router(introductions.router, prefix=API_V1_PREFIX)   # /api/v1/introductions
#   router.include_router(network.router, prefix=API_V1_PREFIX)         # /api/v1/network
