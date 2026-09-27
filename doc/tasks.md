# Legacy task migration archive

BaseMem used to expose a writable task workflow. That workflow is no longer a supported first-class BaseMem feature and is not installed for new agents. Use the coding agent's own todos or the project tracker that owns delivery, status, and assignment.

## Compatibility policy

The existing `tasks` table and compatibility code remain so BaseMem can read and migrate databases created by older releases. No core schema change is required by this documentation migration. Existing task rows are not silently converted into memory notes because their status and ownership semantics are not the same as durable project memory.

Before upgrading, back up `~/.basemem/basemem.db` and stop agents that may be writing to it. After upgrading, keep using the local database if you need historical task records, or remove the legacy table only through a separately reviewed migration.

## Source and deployment changes

- `bin/lib/install.js` no longer deploys the `tasks` OpenCode command.
- `skills/task-workflow` is not installed by new releases.
- Uninstall retains cleanup for `tasks.md` and `task-workflow` so upgrades can remove files from older installs.
- This archive is the only task-specific documentation shipped for new users.

## Data exit

Task data is local SQLite data. To export it, make a filesystem copy of the database while BaseMem is stopped. To remove it, back up anything you need and use the documented purge path (`uninstall.sh --purge-data`) or delete the local data directory. Do not copy credentials or unrelated files from the data directory.

This archive does not document or encourage a new BaseMem task API.
