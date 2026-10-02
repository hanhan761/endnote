
## 2026-10-02 — direct email entry and recipient blocking

- Runtime release: a4d9c63a75ea769754726fb85d3a6e7ff0590bf408231a996987bccc91ec7166.
- 20 behavior tests passed, including unauthenticated quick creation, SDK use without an account, same-recipient task isolation, recipient quotas, global blocking and cancellation of pending notifications. JavaScript syntax check passed.
- Public quick creation, scoped detail access and deletion passed over HTTPS. The configured owner received a test notification accepted by SMTP, containing a recipient-held block link. The real recipient's block link was not followed during verification.
- Service active, zero restarts, approximately 13 MiB systemd memory. Existing tunnel routes unchanged.
- SQLite backup was taken on the authorized workstation before the additive schema update. Rollback record: /opt/endnote/ops/20261002T123444Z/release.json. Older releases do not enforce the new global blacklist or understand quick-task recipient mappings; do not reactivate them with mail enabled after this feature has been used. Prefer forward recovery; pause mail before any legacy rollback.
