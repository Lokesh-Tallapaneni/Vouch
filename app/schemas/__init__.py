"""API wire schemas.

``app/models/`` is the internal vocabulary the service layer speaks; this
package is the wire contract -- what Veloce renders into the OpenAPI document
and what request and response bodies actually are. A service never returns a
schema, and a route never returns a model; routes convert at the boundary
with ``Schema.model_validate(model, from_attributes=True)``. Keeping the two
separate means a field that must never leave the process (a password hash on
an account row) simply cannot, because the response schema never declares it.
"""

from __future__ import annotations
