// Copies the pre-written intro message next to whichever "Copy" button was
// clicked. Found via DOM traversal (closest .intro, then its own textarea),
// not an id -- one page can carry many of these (one per route), and this
// needs no per-instance unique id to find the right one.
//
// navigator.clipboard needs no CSP exception, but the click handler itself
// has to live here, in an external file: script-src 'self' blocks inline
// script and inline event-handler attributes alike -- the same trap that
// silently broke sign-out's hx-on earlier (see _header.html). Delegated on
// document.body, same pattern as csrf.js, so buttons added later (e.g. a
// fresh company page) are covered without re-registering anything.
document.body.addEventListener("click", function (event) {
  var button = event.target.closest(".intro__copy");
  if (!button) return;
  var textarea = button.closest(".intro").querySelector(".intro__message");
  navigator.clipboard.writeText(textarea.value).then(function () {
    var original = button.textContent;
    button.textContent = "Copied";
    button.disabled = true;
    setTimeout(function () {
      button.textContent = original;
      button.disabled = false;
    }, 1500);
  });
});
