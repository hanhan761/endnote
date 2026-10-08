# State indicators — 2026-10-08

Running: blue play triangle. Succeeded: green check. Failed: red cross.
Queued: amber hourglass. Each has a matching background and retains the text label.
Outage uses an orange warning symbol; waiting uses an empty ring, cancelled a dash.
Shapes remain distinct without relying only on color. No animation or dependencies.
Task cluster colors continue to group records independently of their status.

CSS-only release; no event logic, JavaScript, schema or telemetry changes.
Baseline: 41d0ba792836a763c007e32a896a7e2f9df67c1815e8fd2c83c642010097029b.
Candidate SHA-256: 196626a85d1f6dae2c3ff66f9f8ee0b3eb9c9d6d158ca8e0d8d53b075642a80f.
Validation: Python unittest 37 passed, Node dashboard interactions 8 passed;
CSS parser validation passed. Browser preview provider remains unavailable;
no rendered screenshot verification is claimed.
