# 4090 release verification — 2026-10-02

- Target: authorized yun workstation, hostname ps, NVIDIA RTX 4090.
- Public service: https://am.matterswarm.com/endnote/
- Runtime source: Git commit 8b01a8193528cf67a305ec21c5ece8824efaa529.
- Immutable release SHA-256: beafbecf017b53ea30a027d036b3d20f1809ea1c37551cf0b6d941390aa1631e.
- Build/test/package location: local development computer; no build or package installation on production.
- Local tests: 15 passed, including access isolation, concurrent deduplication, transient threshold retention with a full queue, restart recovery and preservation of experiment exit code.
- Skill: frontmatter and naming validator passed; installed at ~/.codex/skills/endnote.
- Preflight: host/ports checked, available memory approximately 49 GiB, filesystem free approximately 237 GiB, no current I/O or memory pressure.
- Deployment: endnote lock and shared tunnel-config lock, verified file manifest, additive SQLite schema.
- SMTP: TLS connection, authentication and NOOP passed, no real recipient test sent.
- Isolation: systemd DynamicUser, ProtectHome, ProtectSystem=strict, NoNewPrivileges, 256 MiB memory limit; only 127.0.0.1:8380 listens.
- Origin and public HTTPS /endnote/health: 200 with ok=true, mail_enabled=true, signup_enabled=true.
- Final observation: more than 90 seconds after reactivation, consecutive successful origin/public health checks, NRestarts=0, memory approximately 13 MiB.
- Existing tunnel site entrypoints: all eleven distinct hostnames returned HTTP 200 after both activation and rollback/reactivation.
- First-install rollback: executed successfully while accounts/tasks were both empty. Verified that endnote's port closed, cloudflared remained active, and the existing application health endpoint passed. Reactivated the exact retained artifact without rebuilding.
- Current rollback record: /opt/endnote/ops/20261002T115055Z/release.json.
- Previous first-install record: /opt/endnote/ops/20261002T114834Z/release.json.
- Secrets: only SMTP allowlist keys copied on-host to root-only credentials; no populated env file or secret in source/release.
- UI verification: HTTP/static asset and JavaScript syntax checks passed. Browser visual testing was unavailable because this session exposes no browser surfaces.
- Actual delivery into a user's inbox remains unverified until the user verifies their own address.
- Backups and immutable artifact retained; cleanup deferred.

To roll back this first installation:
sudo -n python3 /home/codex-admin/endnote-activate.py \
  --rollback /opt/endnote/ops/20261002T115055Z/release.json

Rollback restores the original tunnel configuration and disables endnote. It retains
database and credentials for a controlled reactivation. Confirm no later tunnel
changes would be overwritten before using an old record.
