# Dashboard visual refinement — 2026-10-08

Keep the accepted machine overview, grouped task rows and all event logic. Apply
neutral surfaces, a restrained indigo accent, clearer type, consistent controls,
and responsive machine cards that use the available width for any host count.
Keep task cluster colors and status signals independent. Use system fonts and
native CSS; no third-party runtime scripts, remote assets or added dependencies.

Design references (adapted, no copied component code):
- https://github.com/shadcn-ui/ui
- https://github.com/satnaing/shadcn-admin
- https://github.com/netdata/netdata
- Local awesome-design-md Linear reference: spacing, hairlines and single accent;
  intentionally retain a light canvas for this existing dashboard.

Verification: scoped committed-source snapshot with the new CSS; Python unittest
37 passed; Node dashboard interaction tests 8 passed; CSS parsed successfully,
including responsive rules. Browser preview provider unavailable in this session;
no claim of screenshot or browser layout verification.

Release: CSS-only archive layered onto verified production release
f5b31f9f7184513090dec6ffe4f68288040c5b0ba2af9cbf12aead3b3b6c7800.
Candidate SHA-256: 41d0ba792836a763c007e32a896a7e2f9df67c1815e8fd2c83c642010097029b.
Packaging: scripts/package_dashboard_polish.py.
Activation: deploy/activate_dashboard_polish.py.
The previous release is retained; the activation script rolls back on failure.

Production verification: immutable CSS-only release activated successfully; 62 seconds
of observation with four origin/public health passes. Public CSS matches the exact
local artifact; JavaScript checksum unchanged; both machine reports remain online.
No browser screenshot verification was possible.
