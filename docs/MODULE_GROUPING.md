# Stable module grouping

Task creation accepts optional group: a nonempty plain-text module identifier up to 60 characters (no control characters). Both account and public quick entry retain it in task config. Dashboard responses expose group, and rows use it before the legacy first-name-token fallback. Display names, statuses, notifications, filters and archives retain their existing meaning.

Use the same group across renamed rounds and restarts, for example:

python -m endnote.client run --group beam-module --name "New name round19" -- python experiment.py

SDK: client.experiment("New name round19", group="beam-module").

Existing related records can receive the same group through a bounded operator assignment: exact task IDs, checked common recipient, preflight, private rollback receipt, and config-only transaction. No matching by similar titles, no status mutation, and no automatic experiment restart. Other recipients remain isolated. Assignment IDs and recipient data do not belong in the public release.

## Attention ordering

Whole visible module groups sort by their highest attention state: any outage or failed task first; any succeeded or cancelled task next; groups with only running, queued or waiting tasks last. Equal-priority groups retain alphabetical order and each group retains chronological member order. Polls recompute priority, so state changes move the whole group. Archived records remain in their separate view and do not affect the normal overview.

## Recipient-scoped namespace bindings

An operator-confirmed module namespace can be stored in dashboard_module_bindings for one recipient. Dashboard reads resolve both explicit group variants and legacy title prefixes to that module, including archived and future records. Prefixes match normalized whole namespace boundaries (space, hyphen, underscore or title separators), never arbitrary similar words. Rules do not rename tasks, change status, move archives, or affect other recipients. The additive table is compatible with rollback; bounded activation retains a private SQLite backup and verifies the rule against real records.

Additional confirmed aliases can be applied without a release or restart using deploy/apply_module_binding.py and a private assignment bundle. The operator verifies common recipient scope, retains a private backup and previous rules, applies one bounded transaction, and checks the real dashboard and unchanged service PIDs. Never include private task anchors or recipient information in Git.
