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
├── config.py      # env → validated pydantic Settings, fail-fast at boot
├── errors.py      # error taxonomy → HTTP status → user-visible state
└── db/
    └── driver.py  # pool config, lifecycle, managed transactions, readiness probe
```

Dependency direction is one-way: `routes → services → db.queries → driver`.
Routes never touch Cypher; `db/` never touches HTTP.

---

## Licence

MIT — see [LICENSE](LICENSE).
