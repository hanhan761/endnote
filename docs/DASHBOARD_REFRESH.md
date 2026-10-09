# Dashboard refresh resilience

The task overview remains on a five-second poll; machine cards use the existing one-second lightweight endpoint. Task/filter/detail reads cancel obsolete machine reads. Machine polling pauses during task/detail reads and task reconnects.

A transient failure retains the last successful overview, changes the small connection indicator to reconnecting, and retries after 1, 2, 4, 8, 16, then 30 seconds. The ordinary poll cannot bypass the retry timer. HTTP 429 waits at least 30 seconds and respects numeric Retry-After (capped at 120 seconds). Machine failures use independent bounded backoff. Permanent 400/401/403/404 responses remain explicit and stop automatic reads.

The eight-second per-request deadline remains bounded. After a failed read when task data is at least 30 seconds old, an explicit stale-data notice appears. True browser offline events remain explicit. Successful reads clear retry state; canceled/superseded requests do not count as outages. No experiment, notification, schema, collector, credential or rate-limit change is included.

## Evidence (2026-10-09)

Before modification, controlled slow-response tests reproduced overlapping task/machine reads and the full timeout banner after one missed update, without a prompt retry. Both regression assertions failed on the original script. Public baseline: 12 successful samples, 204–424 ms. Loopback baseline: six task reads 3.19–5.33 ms, six machine reads 1.31–1.51 ms. These samples do not reproduce the user's intermittent network timeout or establish its transport cause; they do rule out a continuously slow origin during measurement.

Validation uses the native Node DOM/fetch harness for request scheduling, cancellation, stale data, recovery, rate limits, and existing task/machine interactions. It is not a rendered-browser test. The scoped release tree also runs python -m unittest discover -s tests -v.
