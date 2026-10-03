
## 2026-10-02 — direct email entry and recipient blocking

- Runtime release: a4d9c63a75ea769754726fb85d3a6e7ff0590bf408231a996987bccc91ec7166.
- 20 behavior tests passed, including unauthenticated quick creation, SDK use without an account, same-recipient task isolation, recipient quotas, global blocking and cancellation of pending notifications. JavaScript syntax check passed.
- Public quick creation, scoped detail access and deletion passed over HTTPS. The configured owner received a test notification accepted by SMTP, containing a recipient-held block link. The real recipient's block link was not followed during verification.
- Service active, zero restarts, approximately 13 MiB systemd memory. Existing tunnel routes unchanged.
- SQLite backup was taken on the authorized workstation before the additive schema update. Rollback record: /opt/endnote/ops/20261002T123444Z/release.json. Older releases do not enforce the new global blacklist or understand quick-task recipient mappings; do not reactivate them with mail enabled after this feature has been used. Prefer forward recovery; pause mail before any legacy rollback.

## 2026-10-02 — identifiable notification titles

- Source revision: 536e6dd. Runtime artifact: 49a1f0e5dbc6e18e2d9e21b90122b56028aef675a74d59ef6810e807ef174797.
- 21 behavior tests passed. New coverage checks account and quick-task titles, all five trigger labels, full task identity in the body, outage threshold and legacy default-template compatibility.
- No schema change. Previous blacklist-compatible release a4d9c63a75ea769754726fb85d3a6e7ff0590bf408231a996987bccc91ec7166 retained. Rollback record: /opt/endnote/ops/20261002T142126Z/release.json.

## 2026-10-03 — start email, recipient dashboard and latency

- Runtime source revision: 8b73c5e. Artifact: dd36a14f1444be193e83e9dc1245cbfd313d7df5f54dd3851ceac96f3da05603.
- 26 behavior tests passed: recipient-only read scope across account and quick tasks, unknown-link rejection, no capability leakage through task APIs, complete pagination, restart persistence and bounded trend history, gzip negotiation, concurrent event writes during a read snapshot, immediate wake of idle mail worker. JavaScript syntax and synthetic DOM rendering/filter/search checks passed; no browser surface was available for screenshot review.
- Local synthetic benchmark: 200 tasks, 30 metrics each, 60 history points each, 8 requests; query plus JSON serialization mean 95.8 ms, maximum 97.5 ms. This is a local measurement, not a production capacity guarantee.
- Public dashboard HTML: 5 development-machine requests, mean 284 ms, maximum 645 ms. Private dashboard API: 3 workstation-to-public requests, 350.8 / 290.2 / 277.2 ms under low load. These sample paths do not represent every user's network.
- Authorized owner start notification accepted by SMTP 3.01 seconds after enqueue. Public API creation, metric updates, two-point trend and final cancelled status verified. Acceptance by SMTP does not establish inbox delivery time.
- Additive dashboards and samples tables; SQLite backup taken on the authorized workstation under deployment lock. Previous release 49a1f0e5dbc6e18e2d9e21b90122b56028aef675a74d59ef6810e807ef174797 retained; rollback record /opt/endnote/ops/20261003T045140Z/release.json. Previous release preserves blacklist behavior but would temporarily disable new dashboard links and start notifications.
- Service active with zero restarts, approximately 15 MiB systemd memory. Existing tunnel ingress unchanged.
