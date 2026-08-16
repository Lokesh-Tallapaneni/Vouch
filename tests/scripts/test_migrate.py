from __future__ import annotations

from pathlib import Path

import pytest

from scripts.migrate import (
    Migration,
    MigrationConflictError,
    checksum_of,
    discover_migrations,
    find_pending,
    split_statements,
)


def test_checksum_is_stable_for_identical_content() -> None:
    assert checksum_of("CREATE INDEX x;") == checksum_of("CREATE INDEX x;")


def test_checksum_changes_when_content_changes() -> None:
    assert checksum_of("CREATE INDEX x;") != checksum_of("CREATE INDEX y;")


def test_split_statements_drops_comments_and_blank_fragments() -> None:
    text = "// leading comment\nCREATE INDEX a;\n\nCREATE INDEX b;\n"
    assert split_statements(text) == ["CREATE INDEX a", "CREATE INDEX b"]


def test_discover_orders_migrations_by_numeric_prefix(tmp_path: Path) -> None:
    # Zero-padded case: lexicographic sort happens to agree with numeric sort
    # here, so this alone would pass even if the prefix were never parsed.
    padded = tmp_path / "padded"
    padded.mkdir()
    (padded / "0010_ten.cypher").write_text("RETURN 10;", encoding="utf-8")
    (padded / "0002_two.cypher").write_text("RETURN 2;", encoding="utf-8")
    assert [m.id for m in discover_migrations(padded)] == ["0002_two", "0010_ten"]

    # Mixed-width case: lexicographic sort puts "10_ten" before "2_two" (the
    # character '1' sorts before '2'), so this only passes if the numeric
    # prefix is actually parsed with int() rather than compared as a string.
    mixed = tmp_path / "mixed"
    mixed.mkdir()
    (mixed / "10_ten.cypher").write_text("RETURN 10;", encoding="utf-8")
    (mixed / "2_two.cypher").write_text("RETURN 2;", encoding="utf-8")
    assert [m.id for m in discover_migrations(mixed)] == ["2_two", "10_ten"]


def test_pending_excludes_already_applied_migrations() -> None:
    migration = Migration(
        id="0001_x", path=Path("0001_x.cypher"), statements=["RETURN 1"], checksum="abc"
    )
    assert find_pending([migration], {"0001_x": "abc"}) == []


def test_editing_an_applied_migration_is_rejected() -> None:
    migration = Migration(
        id="0001_x", path=Path("0001_x.cypher"), statements=["RETURN 2"], checksum="def"
    )
    with pytest.raises(MigrationConflictError, match="0001_x"):
        find_pending([migration], {"0001_x": "abc"})
