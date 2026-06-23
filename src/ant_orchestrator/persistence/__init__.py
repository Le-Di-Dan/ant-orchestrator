"""SQLite persistence adapter: database lifecycle, schema, migrations, repositories.

Implements the application's outbound database ports and the core repository ports.
Depends on ``sqlite3`` + ``core`` + ``application/ports``; never imports typer/yaml
or the workspace package.
"""
