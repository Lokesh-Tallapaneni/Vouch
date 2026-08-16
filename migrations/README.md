# Migrations

Numbered, checksummed, applied in order, recorded as `(:_Migration)` nodes.

- Files are **immutable once applied**. Editing one aborts the runner with a
  checksum conflict — add a new migration instead.
- One statement per `;`. Each runs in its own transaction, because constraint
  and index creation cannot share a transaction with data writes.
- `IF NOT EXISTS` on every constraint and index, so a partially applied
  migration re-runs cleanly.
- **Statement splitting is naive**: the runner splits a file on a bare `;`,
  so a semicolon inside a string literal or a Cypher map would be mistaken
  for a statement boundary. This fails loudly server-side (a syntax error on
  the truncated fragment) rather than corrupting anything, and no current
  migration contains such a semicolon. If you ever need one, keep that
  statement alone in its own file, or rephrase to avoid the literal
  semicolon — don't rely on the splitter to see through it.

```bash
uv run python -m scripts.migrate --status
uv run python -m scripts.migrate --dry-run
uv run python -m scripts.migrate
```
