# Deploy to the authorized 4090 workstation

No build runs on the workstation. Package and test locally with scripts/package_release.py.
deploy/activate.py accepts an uploaded archive and its exact SHA-256 and runs as root,
under /var/lock/endnote-deploy.lock. It verifies member boundaries, checksums,
available resources and service/ingress health before mutation.

Layout:
- /opt/endnote/releases/<archive-sha256>/ — immutable verified Python + static assets.
- /opt/endnote/current — active symlink; previous symlink recorded under ops.
- /var/lib/endnote/ — persistent SQLite state, owned by systemd DynamicUser.
- /etc/endnote/smtp.json — root-only minimal SMTP credentials, delivered via LoadCredential.
- /opt/endnote/ops/ — release records and named service/tunnel backups.

First publication adds an ingress rule for am.matterswarm.com path ^/endnote(?:/.*)?$
before the existing catch-all rule for that hostname. It targets http://127.0.0.1:8380.
No DNS record, public listening port, shared Caddy file or application container changes.
cloudflared ingress validate must pass; the existing tunnel briefly restarts to read
the new route. Recheck all existing tunnel hostnames after activation.

Use yun with registered workstation identity and --confirm-target workstation.
Never weaken host checking. SMTP credentials are filtered on-host from the existing
authorized /opt/matterswarm-workstation/shared/.env.production. No populated env
file is uploaded, downloaded, printed or committed.

Before activation: verify host identity, ports, disk/inodes, memory, pressure, running
workloads and origins. Abort if another deployment holds the lock, existing origins
are degraded, or sustained host pressure is present. Require 2 GiB or 15% filesystem
reserve after staging, whichever is greater.

Activation command (after bounded upload):
sudo -n python3 /home/codex-admin/endnote-activate.py \
  /home/codex-admin/endnote-release.tar.gz SHA256

The archive path and expected checksum must come from the local packaging output.
Mail authentication uses TLS; validate SMTP login and NOOP without sending a test
message. Actual delivery to a real recipient requires their verified address.

After activation:
1. Check endnote.service / cloudflared and local /endnote/health.
2. From the development machine check public DNS/TLS and /endnote/health.
3. Observe at least 60 seconds with consecutive passing checks.
4. Retain the previous release and configuration backups; no automatic cleanup.

Rollback:
Use deploy/activate.py --rollback RELEASE_RECORD as root. This restores the saved
current symlink, service configuration and tunnel configuration, validates ingress,
then restarts only endnote and cloudflared as needed. For first installation,
rollback stops/disables endnote and restores the original tunnel, leaving database,
credential file and immutable release for diagnosis. No database schema downgrade.
Source releases use additive schema only; review compatibility before future changes.

Set ENDNOTE_SIGNUP_ENABLED=false in the service to pause new registrations.
Set ENDNOTE_MAIL_ENABLED=false to pause real delivery while retaining pending mail.
Do not replace or delete the existing SMTP source or other services.
