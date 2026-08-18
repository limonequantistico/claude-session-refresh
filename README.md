# claude-session-refresh

Opens a Claude Code usage window at **fixed, predictable times** — the hours are yours to pick.

Claude Code usage windows last 5 hours and start on your first message, so the boundary lands
wherever you happened to begin working and you never really know when your quota resets. This
doesn't buy you more quota — it buys **predictability**. An automated trigger opens a window at
the same times every day.

Because a window is 5 hours long, **you only choose when your day starts** and the rest follows:
start at 8 and you get `8–13`, `13–18`, `18–23`, `23–04`; start at 10 and you get `10–15`,
`15–20`, `20–01`, `01–06`. Four windows cover twenty hours out of twenty-four, so there is
always a four-hour stretch left unanchored — by default the one before your start hour, which
is usually the night.

The repo ships with `Europe/Rome` and a 08:00 start. Neither is special; see
[Changing the schedule](#changing-the-schedule).

## Quick start

**Using Claude Code?** Run `/setup` in this repo and it walks you through everything below,
checking as it goes what is already done. It also computes the cron entries for your timezone,
which is the one step that is easy to get wrong by hand.

Otherwise, by hand:

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
│  3. Set your timezone and the hour your day starts. The helper works    │
│     out the rest of the cycle and rewrites all four coupled places:      │
│                                                                          │
│        python3 .claude/skills/setup/schedule.py <TZ> --from 8 --apply    │
│                                                                          │
│     Drop `--apply` to preview. Check it any time with `--show`, which    │
│     also flags drift.                                                    │
│                                                                          │
│  4. Get the workflow onto your default branch. A cron due within the     │
│     hour after that may be missed — GitHub takes up to an hour to        │
│     register a new schedule — but the next one fires normally.           │
│                                                                          │
│     Don't want to wait? Dispatch it:                                     │
│                                                                          │
│        gh workflow run refresh.yml                                       │
│                                                                          │
│     It only pings within -60/+45 min of a target hour, and it opens a    │
│     real window — which spends the clean slate step 5 needs.             │
│                                                                          │
│  5. Verify — and mind the trap. The trigger opens a window only when     │
│     none is open, and your own sessions open one too, including the      │
│     one you set this up in. So test on a target at least 5 hours after   │
│     your last message, typically the morning one before you touch        │
│     anything, then run `/usage` in Claude Code. Reset must land on       │
│     target+5h, on the round hour. A ragged time means your own           │
│     activity anchored that window: inconclusive, not broken.             │
└──────────────────────────────────────────────────────────────────────────┘
```

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

1. cron is scheduled **30 minutes before** each target (7:30 / 12:30 / 17:30 / 22:30 local, for
   the shipped hours);
2. the job resolves the upcoming target and **sleeps until the exact second**;
3. only then does it ping.

As long as GitHub's delay stays under 30 minutes — nearly always — the window opens at
**8:00:0x sharp**: the delay is absorbed by the buffer instead of propagating into the time.

For the same reason `npm i -g @anthropic-ai/claude-code` runs **before** the sleep: on wake-up
the ping fires immediately, without twenty seconds of install shifting the window.

### The steps

| # | Step | What it does |
|---|------|--------------|
| 1 | Resolve target | Season guard, then finds the first of your `TARGET_HOURS` falling between −60 and +45 minutes from now. If there is none, the run exits cleanly. |
| 2 | Install Claude Code | `npm i -g @anthropic-ai/claude-code`, before the sleep. |
| 3 | Wait for the exact hour | `sleep` until the target second. If the target already passed, it proceeds immediately and records the delay. |
| 4 | Ping | `claude -p --model haiku --safe-mode --no-session-persistence "Reply with just: ok"`. `--safe-mode` skips hooks/MCP/plugins, `--model haiku` keeps the cost negligible. |
| 5 | Log + commit | Appends a line to `log/YYYY-MM.md` and commits it. |

### The double cron and the season guard

Actions cron is **UTC-only and knows nothing about daylight saving time**, so two sets of
entries are required — here for the shipped Europe/Rome, 08:00 start:

```yaml
on:
  schedule:
    - cron: '30 6,11,16,21 * * *'   # UTC+0100 -> 7:30/12:30/17:30/22:30 local
    - cron: '30 5,10,15,20 * * *'   # UTC+0200 -> 7:30/12:30/17:30/22:30 local
  workflow_dispatch:
```

Half of those entries must do nothing, depending on the season — and the time window alone is
not enough to discard them. In summer the winter entry fires at 8:30 local, and from there the
08:00 target looks like it is 30 minutes in the past, i.e. within the tolerance for late crons.
It would look like a delayed run, and it would ping.

So the workflow compares `github.event.schedule` (the cron entry that triggered this run)
against the current UTC offset of your configured `TZ`, and exits immediately when they
disagree.
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

Nothing about the shipped `Europe/Rome` and 08:00 start is special. The only decision is **the
hour you want your day to start**; since a window is 5 hours long, that fixes the whole cycle,
wrapping into the next day when it has to:

```bash
python3 .claude/skills/setup/schedule.py --show                             # what is set now
python3 .claude/skills/setup/schedule.py America/New_York --from 10 --apply
```

`--from 10` becomes targets `10 15 20 1` — windows `10–15`, `15–20`, `20–01`, `01–06`, leaving
`06:00–10:00` unanchored. It prints exactly that before it writes anything, so you can check the
cycle is the one you wanted.

`--apply` rewrites all four coupled places and refuses to write unless the result is
self-consistent, so a failure leaves the file untouched. Drop `--apply` to print the blocks and
paste them yourself. `--show` also works as a drift check: it exits non-zero if the four places
disagree, and it is the only thing that catches a cron entry with no matching guard arm — an
entry that looks fine and silently exits early on every single run.

**Midnight is the one hour you cannot have.** A 00:00 target's cron fires at 23:30 the *previous*
local day, and the workflow looks for targets with `date -d "today H:00"`, which only ever
considers the current one. Starts of **9, 14 and 19** put a target on midnight; the script drops
it and tells you, leaving three windows and a wider gap. Shifting the start an hour either way
avoids it.

### Hours that aren't a clean cycle

`--from` is the convenient path, not the only one. An explicit list still works, and is the way
to run fewer windows than the day allows:

```bash
python3 .claude/skills/setup/schedule.py America/New_York --apply 8 13
```

That anchors mornings only and leaves the rest of the day behaving the way Claude Code does
normally. The script rejects targets before 01:00, and warns when two are less than 5 hours
apart — the second ping would land inside the first window and do nothing.

Changing a live schedule takes effect only once it reaches the default branch, and a job that is
already sleeping keeps its old target — the new times start from the next cron.

For reference, the four places, if you would rather do it by hand:

1. `TZ` and `TARGET_HOURS` in the job's `env` — your timezone and the local target hours
   (e.g. `8 13 18 23`);
2. the `cron` entries, which must be **30 minutes before** each target: one set for your winter
   UTC offset, one for your summer offset (a single entry is enough if your timezone has no
   DST);
3. the cron strings inside the season guard (`expected=`), compared literally — if you change
   the `cron` entries, change these too, or the unguarded entry exits early on every run;
4. the headline comment at the top of the file, which restates the schedule in prose and is the
   first thing to go stale.

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
- **If you use Claude shortly before a target**, a window starts right there and the target's
  ping falls inside it and does nothing; the system realigns at the following target. That is a
  property, not a bug: the trigger opens a window only when none is already open.
- **The token expires** and has to be rotated by hand (see above).

## Out of scope in v1

Push notifications (ntfy/Telegram). With the Mac off a macOS notification is pointless, and the
value is already in knowing the times in advance.
