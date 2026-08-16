# Vouch

**A referral-path finder.** You are targeting someone at a company. Who in your
network can introduce you, through what chain of people, and how strong is each
link in that chain?

Backed by [CognoDB](https://console.cognodb.com) — a managed graph database
speaking openCypher over Bolt — and reached through the official Neo4j driver.

> 🚧 **In progress.** This README is filled in as the build lands. See
> [Setup](#setup) for what runs today.

---

## Why a graph database?

*(Full section to follow — the short version: the questions here are about
**weighted paths**, not rows. "Do I know anyone at Acme?" is set membership and
any database answers it. "**How** do I reach someone at Acme, and which route is
most likely to work?" demands the route itself, plus a confidence score computed
along that route. The route is the answer, not a byproduct of finding it.)*

---

## Setup

Dependencies are managed with [uv](https://docs.astral.sh/uv/), so the whole
environment is reproducible from the committed `uv.lock`.

```bash
# 1. Create a free (c0) CognoDB instance at console.cognodb.com/signup.
#    Copy the connection URI and password — the password is shown exactly once.

# 2. Configure.
cp .env.example .env      # then fill in COGNODB_URI, COGNODB_PASSWORD, JWT_SECRET

# 3. Install exactly the locked dependency set.
uv sync

# 4. Check the connection.
uv run python -c "from app.config import get_settings; from app.db.driver import Database; \
  db = Database.connect(get_settings()); print(db.check()); db.close()"
```

Generate a signing key for `JWT_SECRET` with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### Without uv

`uv` is not required. Export a pip-compatible lockfile and use a plain venv:

```bash
uv export --format requirements-txt --no-dev > requirements.txt
python -m venv .venv && .venv/bin/pip install -r requirements.txt
```

---

## Project layout

```
app/
├── main.py                 # application factory — wiring only
├── core/                   # cross-cutting concerns, no domain logic
│   ├── settings.py         # env → validated pydantic Settings, fail-fast at boot
│   ├── exceptions.py       # error taxonomy → HTTP status → user-visible state
│   ├── logging.py          # one place configures handlers, called from lifespan
│   └── lifespan.py         # builds the graph client on startup, closes on shutdown
├── db/
│   └── client.py           # pool config, sessions, managed transactions, probe
├── api/
│   ├── dependencies.py     # get_graph / get_settings → Annotated aliases
│   ├── health.py           # /health, /ready — deliberately unversioned
│   └── v1/
│       └── router.py       # /api/v1 — the version prefix, declared once
└── services/               # query results → domain models. No Cypher above here.
```

**Dependency direction is one-way:** `api → services → db`. Route handlers never
contain Cypher; `db/` never imports anything HTTP-shaped.

---

## Licence

MIT — see [LICENSE](LICENSE).
