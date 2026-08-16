"""Domain view models.

Pure pydantic, no database and no framework dependency. Everything downstream
of the graph layer -- services, routes, templates -- imports its vocabulary
from here, so a change to what a "person" or a "route" looks like happens in
one place instead of leaking into every consumer independently.
"""

from __future__ import annotations
