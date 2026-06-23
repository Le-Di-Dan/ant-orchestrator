"""Workspace adapter: filesystem lifecycle of the ``.ant/`` Nest.

Implements ``application.ports.workspace.WorkspaceProvisioner``. Computes the
``WorkspaceArtifactState`` from filesystem/config/marker only — it never imports
sqlite3 or the persistence package (D29/D30).
"""
