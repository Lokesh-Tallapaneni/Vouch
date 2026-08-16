// Attaches the CSRF double-submit token to every htmx request that needs one.
//
// CSRFMiddleware (app/main.py) validates every state-changing request
// against the `csrf_token` cookie it mints on every response, requiring the
// caller to echo it back as an `X-CSRF-Token` header or a `csrf_token` form
// field. Native <form> submissions on this site carry the field directly
// (see the hidden input in sign_in.html/sign_up.html/profile_edit.html);
// htmx has no built-in way to echo a cookie back as a header, so this is
// the one bit of hand-written JS the app needs -- registered once here
// rather than repeated on every hx-post/hx-put/hx-patch/hx-delete element,
// present or future (the sign-out button in _header.html is the first).
//
// `csrf_token` is deliberately not HttpOnly (see CSRFMiddleware's own
// docstring): the double-submit pattern requires exactly this kind of
// client-side read.
document.body.addEventListener("htmx:configRequest", function (event) {
  var match = document.cookie.match(/(?:^|; )csrf_token=([^;]*)/);
  if (match) {
    event.detail.headers["X-CSRF-Token"] = decodeURIComponent(match[1]);
  }
});
