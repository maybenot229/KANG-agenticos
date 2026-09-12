"""The off-machine backup marker loader (ADR-034).

The claim under test: unlike `load_planner_triggers`'s fail-closed
`PlannerConfigError`, this loader never raises — an absent, malformed, or
partially-wrong `[backup]` section all read as "not configured yet"
(`None`), so a config typo here cannot take down `morning_plan`/
`deadline_sweep`/`backup.snapshot`'s own scheduling.
"""

from __future__ import annotations

from pathlib import Path

from kang.adapters.config.backup_config import (
    load_external_backup_marker,
    parse_external_backup_marker,
)


def test_a_configured_path_parses():
    toml_text = '[backup]\nexternal_marker_path = "D:\\\\Backups\\\\kang-marker"\n'
    assert parse_external_backup_marker(toml_text) == Path("D:\\Backups\\kang-marker")


def test_no_backup_section_at_all_is_unconfigured():
    assert parse_external_backup_marker('timezone = "Asia/Kuching"\n') is None


def test_an_empty_file_is_unconfigured():
    assert parse_external_backup_marker("") is None


def test_invalid_toml_is_unconfigured_not_a_raise():
    assert parse_external_backup_marker("this is not [valid toml") is None


def test_a_backup_section_missing_the_key_is_unconfigured():
    assert parse_external_backup_marker('[backup]\nother_key = "x"\n') is None


def test_a_non_string_value_is_unconfigured():
    assert parse_external_backup_marker("[backup]\nexternal_marker_path = 5\n") is None


def test_an_empty_string_value_is_unconfigured():
    assert parse_external_backup_marker('[backup]\nexternal_marker_path = ""\n') is None


def test_load_from_a_missing_file_is_unconfigured_not_a_raise(tmp_path):
    assert load_external_backup_marker(tmp_path / "no-such-kang.toml") is None


def test_load_from_a_real_file_reads_the_configured_path(tmp_path):
    path = tmp_path / "kang.toml"
    path.write_text(
        '[backup]\nexternal_marker_path = "D:\\\\Backups\\\\kang-marker"\n',
        encoding="utf-8",
    )
    assert load_external_backup_marker(path) == Path("D:\\Backups\\kang-marker")
