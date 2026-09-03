# 2026-09-03 — the schedule moved off GitHub

Kept as the record of why this repo looks nothing like it did on 2026-08-25. If you are
wondering where the season guard, the double cron entries, the sleep and `schedule.py` went,
this is the answer.

## What broke

Nothing in the repo. GitHub's `schedule` queue degraded.

The old design fired cron **30 minutes before** each target and slept until the exact second, so
GitHub's delay was absorbed by the buffer instead of shifting the window's start. With
`EARLY_S=2700` and `LATE_S=3600` that tolerated a delay of at most **90 minutes** — past that a
run started, found no target in range, logged `No nearby target` and exited without pinging.

Through Aug 25 GitHub was 15–37 minutes late and the design held. Then:

```
Aug 18–25   delay 15–37 min     4/4 windows a day
Aug 26      delay 65–67 min     3/4
Aug 27–31   delay 67–74 min     1–2/4
Sep 1–3     delay 135–269 min   0 of 12
```

Measured, on Sep 2: cron `05:30` ran at `09:47`, `10:30` at `14:36`, `15:30` at `18:50`. GitHub
also began dropping firings outright — on Sep 3 the `15:30` entry never arrived at all.

Widening the buffer was not a fix. The delay ranged from +2 to +269 minutes, so a buffer big
enough for the worst case makes a punctual run sleep four hours; GitHub caps a job at 6 hours;
and `concurrency: refresh` would queue those long sleepers behind each other.

## What changed

The trigger moved out of GitHub. The runner stayed.

```
cron-job.org  ─ 0 8,13,18,23, timezone Europe/Rome     (see note below)
      │ POST workflow_dispatch
      ▼
GitHub Actions ─ install CLI → claude -p → log → commit
```

`workflow_dispatch` does not pass through the scheduler queue. Measured on the first live run:
the cron fired at `23:00:00`, the run was created at `23:00:44` — **44 seconds**, against 2–4
hours on the same repo the same evening.

## What was deleted, and why it is safe

| Removed | Why it existed | Why it is gone |
|---|---|---|
| `schedule:` cron entries | the trigger | the trigger is external now |
| Season guard (`case "$offset"`) | GitHub cron is UTC-only and DST-blind, so half the entries had to no-op | cron-job.org resolves `Europe/Rome` itself |
| `EARLY_S` / `LATE_S` / target lookup | decide whether a delayed run still had a target | dispatch arrives on the hour; there is nothing to decide |
| "Wait for the exact hour" sleep | absorb the delay so the window started on time | there is no delay to absorb |
| `.claude/skills/setup/schedule.py` (~600 lines) | keep four coupled places in sync: TZ, `TARGET_HOURS`, cron entries, guard arms | none of those four places exist any more |
| `timeout-minutes: 90` | a job could sleep 45 min | a job now runs ~1 minute |

The single biggest consequence: **changing the hours no longer touches this repo.** Edit the
crontab on cron-job.org and you are done. The old flow required editing four coupled places, and
getting three of four right produced a workflow that looked correct and silently never fired.

## Two things checked along the way, worth not re-deriving

- **Actions costs nothing here.** `billable_ms = 0` on every run of this repo, including a
  41-minute one — public repo on standard runners. The account's 2,201-minute alert and $13.60
  gross came ~97% from the private `move` repo (macOS runners, ×10 multiplier). Net owed: $0.
  Do not make this repo private: that would start metering minutes.
- **Claude routines are not a substitute.** A cloud routine (`claude.ai/code/routines`) does run
  — a 2026-04-27 run log shows Haiku answering and `result: success` — but the usage did not
  anchor the interactive 5-hour window. `claude -p` with `CLAUDE_CODE_OAUTH_TOKEN` is a
  first-party Claude Code session; the cloud routine is a different surface, accounted
  elsewhere. This was tested in April and is why the Actions approach exists at all.

## Follow-up, same day: the targets were staggered

The single `0 8,13,18,23` job above is what shipped that evening, and it is not the current
schedule — it was replaced within hours by four jobs at 07:57 / 12:58 / 17:59 / 23:00.

Reason: a window is exactly 5 hours and a ping lands ~55s after its target, so with targets
exactly 5 hours apart a new window opens only when `L_{N+1} > L_N` — only when that run is
slower than the one before it. Roughly half the hops were going to be silently absorbed by the
still-open previous window. Spacing them 5h01m apart buys 60s of margin per hop.

Do not copy the crontab from this file; see the README.
