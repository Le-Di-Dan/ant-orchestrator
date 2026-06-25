"""Execution boundary — bounded side-effect adapters (ADR-0006).

Holds bounded subprocess and filesystem adapters that enforce security policies
from ``security/``. ``subprocess`` is confined to ``bounded_shell.py``. Must not
import ``context``, ``energy``, ``workflows``, ``workers`` or provider SDKs.
"""

from __future__ import annotations
