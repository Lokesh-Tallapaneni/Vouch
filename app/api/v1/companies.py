"""Company endpoints."""

from __future__ import annotations

from veloce import Router

from app.api.dependencies import SearchServiceDep
from app.schemas.common import ERROR_RESPONSES

router = Router(prefix="/companies", tags=["companies"])


@router.get(
    "",
    response_model=list[str],
    summary="Search companies by name prefix",
    response_description="Matching company names, alphabetical.",
    responses=ERROR_RESPONSES,
)
async def list_companies(search: SearchServiceDep, q: str = "", limit: int = 8) -> list[str]:
    """Typeahead over company names."""
    return await search.search_companies(q, limit=limit)
