"""Security policies — pure, side-effect-free guards (ADR-0006).

Holds redaction, path and command policy. Must not import the ``execution``,
``context``, ``energy``, ``workflows`` or ``workers`` packages, concrete adapters
or provider SDKs; these policies are reusable primitives depended on by the
execution boundary (3A) and the context package (3B).
"""

from __future__ import annotations
