// Bootstraps Swagger UI on /docs.
//
// Pulled out of an inline <script> block specifically because this app's
// CSP (script-src 'self') refuses to execute inline script at all -- see
// app/api/docs.py for the full story. This is otherwise the same
// SwaggerUIBundle(...) call Swagger UI's own upstream docs page embeds
// inline; the only change is that it lives in its own same-origin file so
// 'self' already covers it, with no CSP exception needed.
window.addEventListener("DOMContentLoaded", () => {
  window.ui = SwaggerUIBundle({
    url: "/openapi.json",
    dom_id: "#swagger-ui",
    presets: [SwaggerUIBundle.presets.apis],
    layout: "BaseLayout",
  });
});
