// Bootstraps ReDoc on /redoc via its explicit Redoc.init() API rather than
// the `<redoc spec-url="...">` auto-init custom element, specifically so a
// per-request CSP nonce (see app/api/docs.py) can be threaded through to
// ReDoc's styled-components style injection -- the auto-init element has no
// attribute for that.
//
// The nonce and spec URL arrive as data-* attributes on this <script> tag
// itself -- a plain HTML attribute value, not an inline script body, so
// CSP's script-src restriction never applies to it -- which is what lets
// this file stay a static, non-templated vendored asset even though the
// nonce changes on every request.
const script = document.currentScript;
Redoc.init(
  script.dataset.openapiUrl,
  { nonce: script.dataset.nonce },
  document.getElementById("redoc-container"),
);
