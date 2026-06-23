"""Configuration-layer errors (PHASE_1_PLAN §11.5).

No ``ConfigFileNotFound``: a missing file yields defaults (generic loader) or is a
workspace-corruption concern handled by the workspace layer.
"""

from __future__ import annotations

from ant_orchestrator.errors import AntError


class ConfigError(AntError):
    """Base class for configuration errors."""


class ConfigInvalid(ConfigError):
    """The configuration document is malformed or has an invalid value/type."""


class UnknownConfigKey(ConfigError):
    """The configuration document contains an unrecognised key."""
