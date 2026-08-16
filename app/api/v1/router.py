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

API_V1_PREFIX = "/api/v1"

router = Router(prefix=API_V1_PREFIX)

# Endpoint modules are included below as they land. Each owns one resource and
# registers its own child router with its own tag:
#
#   from app.api.v1 import companies, introductions, network, people
#
#   router.include_router(people.router)          # /api/v1/people
#   router.include_router(companies.router)       # /api/v1/companies
#   router.include_router(introductions.router)   # /api/v1/introductions
#   router.include_router(network.router)         # /api/v1/network
