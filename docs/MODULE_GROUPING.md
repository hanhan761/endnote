# Stable module grouping

Task creation accepts optional group: a nonempty plain-text module identifier up to 60 characters (no control characters). Both account and public quick entry retain it in task config. Dashboard responses expose group, and rows use it before the legacy first-name-token fallback. Display names, statuses, notifications, filters and archives retain their existing meaning.

Use the same group across renamed rounds and restarts, for example:

python -m endnote.client run --group beam-module --name "New name round19" -- python experiment.py

SDK: client.experiment("New name round19", group="beam-module").

Existing related records can receive the same group through a bounded operator assignment: exact task IDs, checked common recipient, preflight, private rollback receipt, and config-only transaction. No matching by similar titles, no status mutation, and no automatic experiment restart. Other recipients remain isolated. Assignment IDs and recipient data do not belong in the public release.
