"""CP6 — ``ant memory search`` CLI — filter and limit tests (Phase 7).

Tests 1–15: help output, empty result, all filters (type/source/confidence/task/tag),
combined filters, default/explicit/invalid limits, enum validation, human output safety.
"""

from __future__ import annotations

from pathlib import Path

from ant_orchestrator.cli.main import app
from ant_orchestrator.core.domain.enums import ConfidenceLevel, MemoryType
from tests.support.cli_phase7_memory_helpers import (  # noqa: F401  (nest is a fixture)
    cli,
    db,
    make_record,
    make_task,
    nest,
    repo,
)

# --- 1. memory --help has search ---


def test_memory_help_has_search(nest: Path) -> None:  # noqa: F811
    result = cli.invoke(app, ["memory", "--help"])
    assert result.exit_code == 0
    assert "search" in result.output


# --- 2. Empty memory → exit 0 ---


def test_empty_memory_exits_zero(nest: Path) -> None:  # noqa: F811
    result = cli.invoke(app, ["memory", "search", "--path", str(nest)])
    assert result.exit_code == 0


# --- 3. Type filter ---


def test_type_filter(nest: Path) -> None:  # noqa: F811
    r = repo(nest)
    r.append(make_record("m1", memory_type=MemoryType.PROJECT_FACT))
    r.append(make_record("m2", memory_type=MemoryType.TECHNICAL_DECISION))
    result = cli.invoke(app, ["memory", "search", "--type", "project_fact", "--path", str(nest)])
    assert result.exit_code == 0
    assert "m1" in result.output
    assert "m2" not in result.output


# --- 4. Source exact/case-sensitive ---


def test_source_exact_case_sensitive(nest: Path) -> None:  # noqa: F811
    r = repo(nest)
    r.append(make_record("m1", source="user"))
    r.append(make_record("m2", source="User"))
    r.append(make_record("m3", source="system"))
    result = cli.invoke(app, ["memory", "search", "--source", "user", "--path", str(nest)])
    assert result.exit_code == 0
    assert "m1" in result.output
    assert "m2" not in result.output
    assert "m3" not in result.output


# --- 5. Confidence filter ---


def test_confidence_filter(nest: Path) -> None:  # noqa: F811
    r = repo(nest)
    r.append(make_record("m-high", confidence=ConfidenceLevel.HIGH))
    r.append(make_record("m-low", confidence=ConfidenceLevel.LOW))
    result = cli.invoke(app, ["memory", "search", "--confidence", "high", "--path", str(nest)])
    assert result.exit_code == 0
    assert "m-high" in result.output
    assert "m-low" not in result.output


# --- 6. Task filter ---


def test_task_filter(nest: Path) -> None:  # noqa: F811
    d = db(nest)
    tid = make_task("TASK-A", d)
    r = repo(nest)
    r.append(make_record("m-task", task_id=tid))
    r.append(make_record("m-notask"))
    result = cli.invoke(app, ["memory", "search", "--task", "TASK-A", "--path", str(nest)])
    assert result.exit_code == 0
    assert "m-task" in result.output
    assert "m-notask" not in result.output


# --- 7. Repeated --tag ANY semantics ---


def test_repeated_tag_any_semantics(nest: Path) -> None:  # noqa: F811
    r = repo(nest)
    r.append(make_record("m-foo", tags=("foo",)))
    r.append(make_record("m-bar", tags=("bar",)))
    r.append(make_record("m-baz", tags=("baz",)))
    result = cli.invoke(
        app,
        ["memory", "search", "--tag", "foo", "--tag", "bar", "--path", str(nest)],
    )
    assert result.exit_code == 0
    assert "m-foo" in result.output
    assert "m-bar" in result.output
    assert "m-baz" not in result.output


# --- 8. Combined filters ---


def test_combined_filters(nest: Path) -> None:  # noqa: F811
    r = repo(nest)
    r.append(make_record("m-match", memory_type=MemoryType.PROJECT_FACT, source="user"))
    r.append(make_record("m-type-only", memory_type=MemoryType.PROJECT_FACT, source="bot"))
    r.append(make_record("m-src-only", memory_type=MemoryType.TECHNICAL_DECISION, source="user"))
    result = cli.invoke(
        app,
        ["memory", "search", "--type", "project_fact", "--source", "user", "--path", str(nest)],
    )
    assert result.exit_code == 0
    assert "m-match" in result.output
    assert "m-type-only" not in result.output
    assert "m-src-only" not in result.output


# --- 9–10. Limits ---


def test_default_limit_applied(nest: Path) -> None:  # noqa: F811
    import json

    from ant_orchestrator.config.constants import MEMORY_DEFAULT_LIMIT

    r = repo(nest)
    for i in range(25):
        r.append(make_record(f"m{i:03d}", offset=i))
    result = cli.invoke(app, ["memory", "search", "--json", "--path", str(nest)])
    payload = json.loads(result.output)
    assert payload["resolved_limit"] == MEMORY_DEFAULT_LIMIT
    assert payload["returned_count"] <= MEMORY_DEFAULT_LIMIT


def test_explicit_limit(nest: Path) -> None:  # noqa: F811
    import json

    r = repo(nest)
    for i in range(10):
        r.append(make_record(f"m{i:02d}", offset=i))
    result = cli.invoke(app, ["memory", "search", "--limit", "3", "--json", "--path", str(nest)])
    payload = json.loads(result.output)
    assert payload["returned_count"] == 3


# --- 11. Invalid limits → usage exit ---


def test_limit_zero_exits_usage(nest: Path) -> None:  # noqa: F811
    result = cli.invoke(app, ["memory", "search", "--limit", "0", "--path", str(nest)])
    assert result.exit_code == 2


def test_negative_limit_exits_usage(nest: Path) -> None:  # noqa: F811
    result = cli.invoke(app, ["memory", "search", "--limit", "-5", "--path", str(nest)])
    assert result.exit_code == 2


def test_over_max_limit_exits_usage(nest: Path) -> None:  # noqa: F811
    result = cli.invoke(app, ["memory", "search", "--limit", "999", "--path", str(nest)])
    assert result.exit_code == 2


# --- 12–13. Invalid enum values → usage exit ---


def test_invalid_type_exits_usage(nest: Path) -> None:  # noqa: F811
    result = cli.invoke(app, ["memory", "search", "--type", "not_a_type", "--path", str(nest)])
    assert result.exit_code == 2


def test_invalid_confidence_exits_usage(nest: Path) -> None:  # noqa: F811
    result = cli.invoke(
        app, ["memory", "search", "--confidence", "SUPER_HIGH", "--path", str(nest)]
    )
    assert result.exit_code == 2


# --- 14. Empty task ID → no crash ---


def test_invalid_task_id_format(nest: Path) -> None:  # noqa: F811
    result = cli.invoke(app, ["memory", "search", "--task", "", "--path", str(nest)])
    assert result.exit_code in (0, 2)


# --- 15. Human output does not contain summary/content ---


def test_human_output_no_summary_content(nest: Path) -> None:  # noqa: F811
    r = repo(nest)
    r.append(make_record("m-secret", summary="SECRET CONTENT SHOULD NOT APPEAR"))
    result = cli.invoke(app, ["memory", "search", "--path", str(nest)])
    assert result.exit_code == 0
    assert "SECRET CONTENT SHOULD NOT APPEAR" not in result.output
