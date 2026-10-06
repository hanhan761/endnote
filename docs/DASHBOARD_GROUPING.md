# Dashboard grouping

Each 200-record page groups rows by the first segment of the task name, before whitespace, a middle dot, a vertical bar, or a colon. Use a stable project prefix, e.g. 图像分类 ResNet50 seed42 第3次.

Groups sort by project name; records sort by creation time and task ID. Status changes do not reorder records. Same-name records show creation-order labels, not inferred retry numbers. Groups are contiguous row blocks with pale backgrounds and a narrow left accent. There is no additional group title, count row or collapse control. Neighboring groups use different tones and a small whitespace gap. The overview shows a single priority metric. Short task IDs and notification history are available in details; search, filters and reversible archiving remain available. Grouping is per page, not across pages.

## Verification and release

The scoped change passed 5 dashboard DOM regression tests and 28 Python tests in an isolated HEAD tree with only grouping changes. The full development tree includes unrelated unfinished OAuth/control work: its 127-test run reports 31 missing-oauthlib errors and one existing archive fixture failure. These changes are excluded from this release.

Package locally with python scripts/package_grouping.py. It preserves the exact production baseline archive and replaces only dashboard.js and dashboard.css. After registered target identity and capacity checks pass, use sudo python3 deploy/activate_grouping.py ARTIFACT. Activation verifies the digest, manifest and the two-file scope, retains the prior immutable release, and observes health for 60 seconds with rollback on failure.

2026-10-06: production activation pending. Read-only preflight found 101,353,336,832 free bytes on a 982,820,896,768-byte filesystem, below the existing 15% reserve. No production files, services, experiment data or credentials were changed.

## Queue state update

The release also adds explicit queued and started events. Queue heartbeats preserve the queued state; started clears it. Outage and terminal status take precedence. Queue transitions do not send extra start mail. A queued filter and summary count are available; legacy tasks without a queue report keep their existing state. The client and installed skill support the two new events. No database migration is needed.

Updated validation: 31 Python tests pass in the scoped HEAD tree and 6 dashboard DOM regressions pass. The release is built from the verified live baseline, with only dashboard.js, dashboard.css, service.py and client.py changed. The activation script verifies service/client bytes against the narrow queue patch. An owner-approved, one-release capacity exception can be specified with --approved-capacity-exception; it requires at least 2 GiB after conservatively estimated peak usage and preserves all remaining health, lock, checksum and rollback gates. Do not supply it without explicit authorization.

## Production activation

2026-10-06: the owner explicitly approved the one-release capacity exception. Release 7b7bf4743985ad7547d107eb9e0e3f5f7710111ba87ead690b9636ea1071296a was activated on the authorized workstation. Four origin/public health samples passed over 62 seconds; unrelated service PIDs and the service unit were unchanged. Previous release 47e3909e5937af46efa46239502ab8676c6c1aa9ba010252be6c8de3559b70eb is retained for rollback. Public dashboard asset checksums match the local candidate; the queued filter responds successfully. No experiment data cleanup or database migration was performed. The capacity exception does not alter the default 15% reserve for future releases.

## Simplified color layout activation

2026-10-06: release c4504b2e4aa79d5b10d051827ee52a4d184891473494bf2f114dedfc26e021ac activated the two-file color layout update. Group title rows and collapse controls were removed, adjacent groups receive distinct pale tones, and a single priority metric is shown. Public JavaScript/CSS checksums match the candidate; four health samples passed over 62 seconds. The prior queue release is retained for rollback. This dashboard follow-up used the owner's approved capacity exception without changing the default threshold. Actual free space was 140,363,472,896 bytes. Browser UI automation was unavailable; verification covered scoped Python tests, DOM regressions and live asset/health checks.
