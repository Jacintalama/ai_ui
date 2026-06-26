"""Tests for migration 028: default Remotion animation preset on video jobs."""
import pathlib

_MIGRATION_FILE = (
    pathlib.Path(__file__).parent.parent / "migrations" / "028_video_animation_preset.sql"
)


def test_migration_file_adds_animation_preset_and_remotion_default():
    assert _MIGRATION_FILE.exists(), f"Migration file not found: {_MIGRATION_FILE}"
    sql = _MIGRATION_FILE.read_text()
    assert "animation_preset" in sql
    assert "cursor_click" in sql
    assert "ALTER COLUMN render_mode SET DEFAULT 'remotion'" in sql
