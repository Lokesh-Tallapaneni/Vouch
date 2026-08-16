# Migrations

Numbered, checksummed, applied in order, recorded as `(:_Migration)` nodes.

- Files are **immutable once applied**. Editing one aborts the runner with a
  checksum conflict — add a new migration instead.
- One statement per `;`. Each runs in its own transaction, because constraint
  and index creation cannot share a transaction with data writes.
- `IF NOT EXISTS` on every constraint and index, so a partially applied
  migration re-runs cleanly.

```bash
uv run python -m scripts.migrate --status
uv run python -m scripts.migrate --dry-run
uv run python -m scripts.migrate
```
