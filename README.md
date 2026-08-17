# claude-session-refresh

Opens a Claude Code usage window at **fixed, predictable times**: 08:00, 13:00, 18:00 and
23:00 (Europe/Rome).

Claude Code usage windows last 5 hours and start on your first message, so the boundary lands
wherever you happened to begin working and you never really know when your quota resets. This
doesn't buy you more quota — it buys **predictability**. An automated trigger opens a window at
the same times every day, so the windows become `8–13`, `13–18`, `18–23`, `23–04`.

The whole point is knowing the times in advance, which makes **punctuality the requirement, not
a detail**.

## Quick start

```
┌──────────────────────────────────────────────────────────────────────────┐
│  1. Fork this repo — keep it PUBLIC (scheduled runs sleep, and Actions   │
│     minutes are free and unlimited only on public repos).                │
│                                                                          │
│  2. Generate a subscription token and store it as a secret:              │
│                                                                          │
│        claude setup-token                                                │
│        gh secret set CLAUDE_CODE_OAUTH_TOKEN --repo <you>/<repo>         │
│                                                                          │
│     `gh secret set` reads the value from stdin, so it never lands in     │
│     your shell history. Never paste the token anywhere else.             │
│                                                                          │
│  3. Set your timezone: edit `TZ` and `TARGET_HOURS` in                   │
│     `.github/workflows/refresh.yml` (see "Changing the schedule").       │
│                                                                          │
│  4. Make sure the workflow is on your default branch, then fire the      │
│     first run by hand — GitHub takes up to an hour to register a new     │
│     schedule:                                                            │
│                                                                          │
│        gh workflow run refresh.yml                                       │
│                                                                          │
│     It only pings within -60/+45 minutes of a target hour; outside that  │
│     range it exits cleanly.                                              │
│                                                                          │
│  5. Right after a green run, open Claude Code locally and run `/usage`.  │
│     The reset time must be ~5 hours after the run. If it isn't, the      │
│     ping did not open a window — stop here, nothing else will work.      │
└──────────────────────────────────────────────────────────────────────────┘
```

The 04:00–08:00 gap is deliberate: four windows cover twenty hours out of twenty-four, and
there is no need to anchor the night.

## How it works

A GitHub Actions workflow ([`.github/workflows/refresh.yml`](.github/workflows/refresh.yml))
actually runs the `claude` CLI — not an HTTP POST — authenticating with the token from
`claude setup-token`.

### Why this way and not another

- **It runs in the cloud, not on your Mac.** A local LaunchAgent is not a trigger: if the Mac is
  off, nothing fires. The runner is GitHub Actions.
- **It runs the CLI, not the API.** The OAuth token (`sk-ant-oat01-…`) authenticates your
  subscription, which is what matters here: a regular API key would spend API credits and
  **would not touch the 5-hour window at all**. That token, however, is only accepted by Claude
  Code, not by the Messages API — which rules out Cloudflare Workers and any serverless runtime
  without subprocesses.
- **The repo is public.** The job sleeps (see below), and sleeping burns Actions minutes. On
  private repos those minutes are metered (500/month on Free, 3000 on Pro), and four runs a day
  with sleeps of up to half an hour add up to roughly 1900–3700 minutes a month — over budget.
  On public repos the minutes are free and unlimited. Nothing sensitive lives in the code: the
  token lives in GitHub secrets, and secrets are not passed to workflows from forks.

### The core design: fire early **and** sleep

GitHub Actions cron is not punctual: 15+ minute delays are normal (and got worse in February
2026), and under load a run can be skipped entirely.

Firing early on its own solves nothing: if the job runs at 7:30, the window opens at 7:30, the
anchor just moves and the uncertainty is unchanged. The fix is to fire early **and make the job
wait**:

1. cron is scheduled **30 minutes before** the target (7:30 / 12:30 / 17:30 / 22:30 local);
2. the job resolves the upcoming target and **sleeps until the exact second**;
3. only then does it ping.

As long as GitHub's delay stays under 30 minutes — nearly always — the window opens at
**8:00:0x sharp**: the delay is absorbed by the buffer instead of propagating into the time.

For the same reason `npm i -g @anthropic-ai/claude-code` runs **before** the sleep: on wake-up
the ping fires immediately, without twenty seconds of install shifting the window.

### The steps

| # | Step | What it does |
|---|------|--------------|
| 1 | Resolve target | Season guard, then finds the first hour among 08/13/18/23 falling between −60 and +45 minutes from now. If there is none, the run exits cleanly. |
| 2 | Install Claude Code | `npm i -g @anthropic-ai/claude-code`, before the sleep. |
| 3 | Wait for the exact hour | `sleep` until the target second. If the target already passed, it proceeds immediately and records the delay. |
| 4 | Ping | `claude -p --model haiku --safe-mode --no-session-persistence "Reply with just: ok"`. `--safe-mode` skips hooks/MCP/plugins, `--model haiku` keeps the cost negligible. |
| 5 | Log + commit | Appends a line to `log/YYYY-MM.md` and commits it. |

### The double cron and the season guard

Actions cron is **UTC-only and knows nothing about daylight saving time**, so two sets of
entries are required:

```yaml
on:
  schedule:
    - cron: '30 6,11,16,21 * * *'   # winter CET  (UTC+1) -> 7:30/12:30/17:30/22:30 local
    - cron: '30 5,10,15,20 * * *'   # summer CEST (UTC+2) -> same local times
  workflow_dispatch:
```

Half of those entries must do nothing, depending on the season — and the time window alone is
not enough to discard them. In summer the winter entry fires at 8:30 local, and from there the
08:00 target looks like it is 30 minutes in the past, i.e. within the tolerance for late crons.
It would look like a delayed run, and it would ping.

So the workflow compares `github.event.schedule` (the cron entry that triggered this run)
against the current UTC offset of `Europe/Rome`, and exits immediately when they disagree.
Manual runs (`workflow_dispatch`) skip the check.

### The log

Every successful run appends a line to `log/YYYY-MM.md`:

```
2026-08-17 08:00 — window opened (cron 4 min late) → expires 13:00
```

This serves two purposes at once:

- it is the **readable history of your windows**, and it also shows how late cron actually runs;
- it **keeps the repo alive**: public repos get their scheduled workflows disabled after 60 days
  of inactivity, and a commit a day makes that a non-issue.

Commits made with `GITHUB_TOKEN` do not re-trigger workflows, so there is no loop. The time and
expiry also go into the run's step summary.

## Rotating the token

OAuth tokens expire. When the ping starts failing on authentication, run the same two commands
again: `claude setup-token` issues a fresh token and `gh secret set` overwrites the old one.
Nothing else changes — the workflow always reads `secrets.CLAUDE_CODE_OAUTH_TOKEN`.

## Changing the schedule

The times live in more than one place and must be kept in sync:

1. `TZ` and `TARGET_HOURS` in the job's `env` — your timezone and the local target hours
   (`8 13 18 23`);
2. the two `cron` entries, which must be **30 minutes before** each target: one set for your
   winter UTC offset, one for your summer offset (a single entry is enough if your timezone has
   no DST);
3. the cron strings inside the season guard (`expected=`), which are compared literally — if you
   change the `cron` entries, change these too.

Keep in mind that windows last 5 hours: targets closer together than that overlap, and the extra
pings do nothing.

## Widening the buffer

The buffer is two variables in the job's `env`:

- `EARLY_S` (default `2700`, 45 min) — how far in the future a target may be for the job to wait
  for it by sleeping;
- `LATE_S` (default `3600`, 60 min) — how far in the past a target may be for the job to ping it
  anyway, late.

To harden against longer delays, move the cron earlier (45 or 60 minutes instead of 30) and
raise `EARLY_S` to match. It only costs Actions minutes, which are free on a public repo. Avoid
raising `LATE_S` far beyond the cron's head start: the wider it gets, the more the season guard
is left doing all the work on its own.

## Known risks

- **Delays beyond 30 minutes.** Rare, but real. The buffer absorbs up to half an hour; past
  that, the window opens late and the log says so. If GitHub skips a scheduled run entirely,
  that window simply is not anchored.
- **If you use Claude before 08:00**, a window starts right there and the 08:00 one falls inside
  it and does nothing; the system realigns at 13:00. That is a property, not a bug: the trigger
  opens a window only when none is already open.
- **The token expires** and has to be rotated by hand (see above).

## Out of scope in v1

Push notifications (ntfy/Telegram). With the Mac off a macOS notification is pointless, and the
value is already in knowing the times in advance.
