"""Shared DDL helpers for schema v1/v2 (single source of truth for CHECK clauses).

Lives in its own module so both ``schema`` (the composed v2 authority) and
``schema_workflow`` (Phase 4 fragments) can import the helpers without a cycle.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum

CODE_MAX_VERSION = 3
MIGRATIONS_TABLE = "schema_migrations"


def enum_values(enum_cls: type[Enum]) -> str:
    """Render all member values as a SQL value list: ``'a', 'b'``."""
    return ", ".join(f"'{member.value}'" for member in enum_cls.__members__.values())


def check_in(column: str, enum_cls: type[Enum], *, nullable: bool = False) -> str:
    """Build a ``column IN (...)`` CHECK clause from an enum (optionally nullable)."""
    clause = f"{column} IN ({enum_values(enum_cls)})"
    return f"({column} IS NULL OR {clause})" if nullable else clause


def members_list(members: Iterable[Enum]) -> str:
    """Render an explicit subset of members as a SQL value list."""
    return ", ".join(f"'{member.value}'" for member in members)


def check_in_members(column: str, members: Iterable[Enum]) -> str:
    """Build a ``column IN (...)`` CHECK clause from an explicit member subset."""
    return f"{column} IN ({members_list(members)})"
