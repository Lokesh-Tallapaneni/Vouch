"""The pre-written intro-request message under each route.

Rendered entirely from data the page already has -- no backend, no new
endpoint, no write. Registered as a Jinja global (see app.web.templating)
so _intro_disclosure.html can call it directly rather than every page
handler pre-computing one message per row before render.

Without an action, a route is a picture of a graph query, not something
that does a job -- this is the action: a message the viewer can copy and
send, not a form that writes anywhere.
"""

from __future__ import annotations

from app.models.referral import IntroductionRoute

#: A phrase a real person would say, not the stored context spelling.
#: Deliberately not exhaustive of every string the graph could contain --
#: the fallback below turns any unrecognised context into the same
#: hyphen-free form _chain.html already uses for display, so a new context
#: value added later degrades to something readable rather than raising.
_RELATIONSHIP_PHRASES = {
    "team": "you're on the same team",
    "project": "you worked together on a project",
    "former-colleague": "you used to work together",
}


def _relationship_phrase(context: str) -> str:
    return _RELATIONSHIP_PHRASES.get(
        context, f"you know each other from {context.replace('-', ' ')}"
    )


def build_intro_message(
    route: IntroductionRoute, target_name: str, target_title: str = "", company: str = ""
) -> str:
    """The message this route's disclosure pre-fills, addressed to the
    *first* hop -- they're who you'd actually message, not the target.

    What it asks for depends on the route's length:

    - One hop: the first hop already *is* the target, so this is a direct
      reach-out ("we're already connected"), not an introduction request --
      there's no one in between to ask for one.
    - Two or more hops: asks the first hop specifically to introduce the
      viewer to the *second* hop, not the whole chain at once -- that is
      the person the first hop can actually vouch for, and the relationship
      phrase used (see _relationship_phrase) describes *their* connection
      (hop_details[1].context), not how the viewer knows the first hop.

    Returns "" for a route with no hops -- nothing to ask anyone about.
    """
    if not route.hop_details:
        return ""

    first = route.hop_details[0]
    ask_person = first.to_name
    title_part = f" ({target_title})" if target_title else ""
    company_part = f" at {company}" if company else ""

    if len(route.hop_details) == 1:
        relationship = _relationship_phrase(first.context)
        body = (
            f"I'm hoping to connect with people{company_part}, and saw we're "
            f"already connected — {relationship}."
        )
        ask = "Would you be up for a quick chat"
    else:
        next_person = route.hop_details[1].to_name
        relationship = _relationship_phrase(route.hop_details[1].context)
        # A two-hop route's "next stop" *is* the target -- naming them
        # twice ("get in front of Lucas Bhat ... you know Lucas Bhat")
        # reads as a mistake, not emphasis. Caught by actually opening the
        # disclosure in a browser, not by the unit tests, which never
        # render the sentence as a whole.
        who = "them" if next_person == target_name else next_person
        body = (
            f"I'm hoping to get in front of {target_name}{title_part}{company_part} "
            f"and noticed you know {who} — {relationship}."
        )
        ask = "Would you be willing to introduce us"

    return (
        f"Hi {ask_person},\n\n"
        f"{body}\n\n"
        f"{ask}? Happy to send a short blurb you can forward on.\n\n"
        "Thanks!"
    )
