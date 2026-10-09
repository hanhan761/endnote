# Optional machine monitoring

Reference layouts: [Beszel](https://github.com/henrygd/beszel), [Glances](https://github.com/nicolargo/glances). The implementation is native endnote code with no added runtime dependencies.

A recipient-private dashboard can enroll up to 12 machines, with independent hashed bearer credentials. The enrollment response privately includes a configured script. No credential appears in read responses. Machine credentials can only submit bounded numeric telemetry for their own ID. Existing experiment credentials do not enroll or read machines. Management is scoped by the random dashboard token; keep that link private. Disable/enable is reversible and independent of experiment reminders.

The collector targets one report per second; machine cards use a lightweight one-second read endpoint while experiment rows remain on five-second polling. Reports are limited to 90 per minute per machine; enrollment to six per hour per recipient. Global machine cap: 2000. Payload uses the existing 16 KiB body bound, finite numbers, capacity bounds, at most eight GPUs and no URLs or executable fields. Only one latest snapshot is retained. No metric history or automatic resource email alerts are added.

The collector reads local proc/sysfs counters on Linux or standard Windows memory/CPU APIs. The only child command is fixed NVIDIA telemetry via nvidia-smi, without a shell, with a four-second timeout and hidden Windows subprocesses. It targets one sample and report per second, retries with bounded backoff and stops on revoked credentials. It opens no server port and sends no files, process list, IPs or commands. CPU temperature is optional and currently Linux-only; NVIDIA GPU temperatures require the driver utility. Missing metrics are null rather than fake zero.

UI: responsive equal-style machine cards replace the top task summary. CPU/GPU/memory/disk dials, temperature and GPU per-device details; waiting, online, offline after 90 seconds, and disabled states. Task status counts stay in filter tabs. No collector means a small opt-in prompt. Browser automation was unavailable; layout verification covers DOM behavior and responsive CSS rules rather than screenshots.

Migration: one additive machines table and recipient index. Previous runtime ignores the table and can be restored safely; no task schema migration. Build off-host with scripts/package_machines.py from the exact verified color release. activate_machines.py verifies the full artifact, narrow integration patches, checksums, resource gate, health and 60-second observation. Retain the exact prior release. The workstation collector is separately opt-in and runs as codex-admin with 96 MiB memory and 10% CPU caps via install_machine_collector.py; its private configuration is never in source or artifacts. Rollback the collector by stopping/disabling endnote-machine; roll back the web runtime via the previous immutable symlink. No database downgrade is needed.

## Verified production release

2026-10-07: runtime f5b31f9f7184513090dec6ffe4f68288040c5b0ba2af9cbf12aead3b3b6c7800 was activated on the authorized workstation, retaining c4504b2e4aa79d5b10d051827ee52a4d184891473494bf2f114dedfc26e021ac and a private pre-migration SQLite backup. Four health samples passed over 62 seconds. Public JavaScript/CSS checksums matched, the optional panel replaced the old totals, and the owner-authorized workstation collector reported real CPU/GPU/capacity/temperature telemetry. The collector ran as codex-admin with no restarts; measured resident service memory was approximately 11 MB. Private config mode is 0600 and transient configuration copies were removed. Other machines were not automatically enrolled.

Validation: 37 Python tests in the scoped source tree, 8 dashboard DOM regressions, and 9 machine/queue regressions against the exact immutable runtime artifact passed. Other unfinished working-tree features were excluded. The existing owner-approved capacity exception was used for this small dashboard extension; the default reserve remains unchanged.

## One-second monitoring — 2026-10-09

Release 42f9703f949b6bdfac5851efa241648ccf3e0550ba47d3f873a40c55b6721483; baseline 072cd17720043c4db66d8159dec066be4d0202380936b89af4d5a3c61e1b4f23.
A drifted baseline was rejected before activation; current server/service changes
were downloaded by bounded transfer, hash checked and retained. Only the machine
module, collector and machine-card JavaScript changed. No mail-budget or task event changes.
38 scoped Python tests, 9 Node UI regressions, and 10 machine/queue tests against
the actual runtime artifact passed. Origin/public health passed four checks over
69 seconds. Both collectors updated with existing private configurations; 3090
retains its previous runner and 4090 retains the previous immutable release.

Local sampler benchmark: 4090 mean 24.43 ms, 3090 mean 33.16 ms per sample;
CPU including NVIDIA utility children 19.28 / 21.07 ms per sample, RSS about 19 MiB.
Runtime acceptance: 4090 工作站 78 reports in 95 seconds (0.82/s); 3090 工作站 76 reports in 95 seconds (0.8/s).
Collector RSS about 22 MiB each. These are a short observation, not a training
throughput benchmark; HTTPS, server and browser work are additional to sampling.
Public JavaScript matches the candidate. Machine reads are isolated from task
refreshes, hidden tabs suspend polling, requests do not overlap, and collectors
back off on failures. No browser screenshot validation was available.
