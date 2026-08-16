"""Self-hosted /docs and /redoc, replacing Veloce's own CDN-backed pages.

Veloce's built-in Swagger UI / ReDoc routes (``veloce.contrib.openapi``)
pull swagger-ui.min.css / swagger-ui-bundle.min.js from cdnjs.cloudflare.com,
redoc.standalone.js from unpkg.com, and bootstrap Swagger UI with an inline
``<script>`` block. This app's CSP -- ``default-src 'self'``, no external
host, no ``unsafe-inline`` (see ``app.main``) -- blocks all three outright.
The page still returned 200 (the HTML shipped fine); the browser refused
every asset it needed to actually draw anything, so ``/docs`` rendered as a
blank white screen. No status-code check or ``curl`` run could ever have
caught that -- only a browser opening the page and reading its console.

The fix is not to weaken the CSP for this one page. It's the same move
already made for htmx and the webfonts: vendor the assets and serve them
same-origin, so ``'self'`` already covers them with no policy change at all.
The vendored files at ``app/static/vendor/`` are the *exact* bytes
``veloce.contrib.openapi`` itself pins by version and Subresource Integrity
hash (``_SWAGGER_UI_VERSION``/``_REDOC_VERSION`` below mirror its constants)
-- downloaded and verified against those hashes before being committed, so
this trusts nothing veloce's own maintainers didn't already vet. The one
piece that cannot simply be re-hosted as a static file is the inline
``SwaggerUIBundle(...)`` bootstrap call itself: that lives in
``app/static/vendor/docs-init.js`` instead, since ``'self'`` permits an
external script file but never an inline one.

Swagger UI's stylesheet is a plain, fully static file, so vendoring it was
the whole fix. ReDoc is not: it renders through a bundled copy of
styled-components, which injects ``<style>`` tags into ``<head>`` at
*runtime* to apply its component CSS -- confirmed by reading the vendored
bundle itself, not assumed. Verified live in a browser that vendoring alone
was not enough: the page still crashed, and network logs showed no request
for ``openapi_url`` was ever made -- the CSP violation from the blocked
runtime style injection threw during React's very first mount, before
ReDoc got anywhere near fetching the spec. See :func:`register_docs_routes`
for the per-request CSP nonce that actually fixes this -- the standard
CSP Level 3 mechanism for exactly this situation, and not a policy
weakening: unlike ``unsafe-inline`` it trusts nothing unconditionally, and
unlike a host allowlist it is not a fixed, reusable value.

Wire this in by passing ``docs_url=None, redoc_url=None`` to ``Veloce(...)``
in ``app.main`` (so the framework's own routes never register) and calling
:func:`register_docs_routes` afterward. ``openapi_url`` is untouched and
keeps serving ``/openapi.json`` regardless -- Veloce registers that route
whenever ``openapi_url`` is truthy, independent of ``docs_url``/``redoc_url``
(see ``veloce/app/openapi.py``'s ``_setup_openapi``).
"""

from __future__ import annotations

import html
import secrets

from veloce import HTMLResponse, Veloce

#: Mirror veloce.contrib.openapi's own pins -- documentation of which exact
#: build app/static/vendor/'s files are, not something read at runtime. Bump
#: together with the vendored files (and re-verify their SHA hashes against
#: veloce's own _SWAGGER_UI_CSS_INTEGRITY / _SWAGGER_UI_JS_INTEGRITY /
#: _REDOC_JS_INTEGRITY constants) if the version ever changes.
_SWAGGER_UI_VERSION = "5.18.2"
_REDOC_VERSION = "2.1.5"

_SWAGGER_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>{title} - Swagger UI</title>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="stylesheet" href="/static/vendor/swagger-ui.min.css">
</head>
<body>
    <div id="swagger-ui"></div>
    <script src="/static/vendor/swagger-ui-bundle.min.js"></script>
    <script src="/static/vendor/docs-init.js"></script>
</body>
</html>"""

#: `redoc-reset.css` is its own file for the same reason as everything else
#: here -- a bare `<style>body{{margin:0}}</style>` is inline, and
#: style-src 'self' blocks it exactly like a CDN host or a bootstrap
#: script. `<div id="redoc-container">` replaces the `<redoc spec-url="...">`
#: auto-init custom element ReDoc's own docs recommend: auto-init has no
#: attribute for passing a nonce through, so redoc-init.js calls
#: `Redoc.init()` explicitly instead (see that file).
_REDOC_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>{title} - ReDoc</title>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="stylesheet" href="/static/vendor/redoc-reset.css">
</head>
<body>
    <div id="redoc-container"></div>
    <script src="/static/vendor/redoc.standalone.js"></script>
    <script
      src="/static/vendor/redoc-init.js"
      data-openapi-url="{openapi_url}"
      data-nonce="{nonce}"
    ></script>
</body>
</html>"""


def register_docs_routes(app: Veloce, *, openapi_url: str = "/openapi.json") -> None:
    """Register same-origin /docs and /redoc pages on `app`.

    Call with `Veloce(docs_url=None, redoc_url=None, ...)` so this replaces
    the framework's own CDN-backed routes rather than duplicating them.
    """

    @app.get("/docs", tags=["openapi"], name="swagger_ui", include_in_schema=False)
    async def swagger_ui() -> HTMLResponse:
        return HTMLResponse(_SWAGGER_HTML.format(title=html.escape(app.title)))

    @app.get("/redoc", tags=["openapi"], name="redoc_ui", include_in_schema=False)
    async def redoc_ui() -> HTMLResponse:
        # Cryptographically random per request (16 bytes -> ~128 bits,
        # secrets.token_urlsafe's usual web-token size) -- an attacker who
        # cannot predict this value cannot forge a matching inline
        # <style nonce="..."> element, which is the entire security
        # property a CSP nonce is supposed to provide. A fixed value baked
        # into the template would not have that property; it would just be
        # unsafe-inline wearing a nonce-shaped disguise.
        nonce = secrets.token_urlsafe(16)
        page = _REDOC_HTML.format(
            title=html.escape(app.title),
            openapi_url=html.escape(openapi_url),
            nonce=html.escape(nonce, quote=True),
        )
        response = HTMLResponse(page)
        # Set directly on this response rather than touching app.main's
        # CSPMiddleware policy -- CSPMiddleware only fills in a header the
        # route hasn't already set (see its own header_present check), so
        # this is scoped to the /redoc response alone; the sitewide default
        # policy every other page gets is untouched. Mirrors that policy
        # (see app.main) with two additions, both verified live in a
        # browser to be exactly what ReDoc's search feature needs and
        # nothing more:
        #
        # - The nonce source on style-src, as above.
        # - `worker-src 'self' blob:` -- ReDoc runs its full-text search
        #   index in a Web Worker constructed from a `blob:` URL (code the
        #   page itself generated client-side, not a third party's), which
        #   `script-src` alone does not cover as a fallback for `blob:`
        #   sources. This is not a host being trusted; blob: workers can
        #   only ever run script this same page already served under
        #   'self', so there is nothing new being granted access here.
        response.headers["content-security-policy"] = (
            "default-src 'self'; script-src 'self'; "
            f"style-src 'self' 'nonce-{nonce}'; img-src 'self' data:; "
            "worker-src 'self' blob:"
        )
        return response
