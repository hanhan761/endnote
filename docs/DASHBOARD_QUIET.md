# Quiet visual hierarchy — 2026-10-08

Remove colored status containers; retain distinct, small semantic status icons.
Use neutral status text, with a warning emphasis for actual outage only.
Lighten existing cluster backgrounds while keeping their colored leading edge.
Give resource gauges a shared muted accent; high-use warning colors stay semantic.
Preserve the accepted layout and all task grouping, polling and notification logic.

CSS-only release. No added dependencies, assets, animation or JavaScript changes.
Baseline: 9769f126b202b02af2f7e47f5f9dad7802f1aefcd3dd40a126b1ff57686a3999.
Release SHA-256: ed57d225f12d183dacde13b34bb6a4cb13941e410ed8a9365e2e54eab35c702a.
Validation: 37 Python tests and 8 dashboard interaction checks passed; CSS and
activation syntax validated. Browser preview provider unavailable; no actual
rendered screenshots or visual browser acceptance are claimed.

Production verified: 63 seconds with four origin/public health checks, public CSS
matched the exact local artifact, and both machines stayed online. Previous
release retained for rollback.
