# Dashboard grouping

Each 200-record page groups rows by the first segment of the task name, before whitespace, a middle dot, a vertical bar, or a colon. Use a stable project prefix, e.g. 图像分类 ResNet50 seed42 第3次.

Groups sort by project name; records sort by creation time and task ID. Status changes do not reorder records. Same-name records show creation-order labels, not inferred retry numbers. Groups show record and status counts and can collapse; collapse state survives automatic refresh during the page session. Search, filters, details and reversible archiving remain available. Grouping is per page, not across pages.

## Verification and release

The scoped change passed 5 dashboard DOM regression tests and 28 Python tests in an isolated HEAD tree with only grouping changes. The full development tree includes unrelated unfinished OAuth/control work: its 127-test run reports 31 missing-oauthlib errors and one existing archive fixture failure. These changes are excluded from this release.

Package locally with python scripts/package_grouping.py. It preserves the exact production baseline archive and replaces only dashboard.js and dashboard.css. After registered target identity and capacity checks pass, use sudo python3 deploy/activate_grouping.py ARTIFACT. Activation verifies the digest, manifest and the two-file scope, retains the prior immutable release, and observes health for 60 seconds with rollback on failure.

2026-10-06: production activation pending. Read-only preflight found 101,353,336,832 free bytes on a 982,820,896,768-byte filesystem, below the existing 15% reserve. No production files, services, experiment data or credentials were changed.
