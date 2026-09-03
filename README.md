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

The repo ships with `Europe/Rome` and a 08:00 start. Neither is special.

## How it works

```
cron-job.org  ─ 4 jobs: 07:57 / 12:58 / 17:59 / 23:00, timezone Europe/Rome
      │ POST workflow_dispatch
      ▼
GitHub Actions ─ install CLI → claude -p (Haiku) → append log → commit
```

**The schedule lives outside GitHub, on purpose.** GitHub Actions is only the runner. Its own
`schedule` queue is not used: in August 2026 it degraded from ~30-minute delays to 2–4 hours
with runs dropped outright, which is a failure mode you cannot design around — see
[the migration note](docs/archive/2026-09-03-scheduler-migration.md). `workflow_dispatch` skips
that queue entirely and arrives within seconds.

Two things follow from this split, and they are the whole reason it is worth understanding:

- **The hours are not in this repo.** To change them, edit the crontab on cron-job.org. No
  commit, no deploy, nothing to keep in sync.
- **DST needs no handling anywhere.** cron-job.org resolves `Europe/Rome` itself, so there is no
  UTC conversion and no seasonal switch to remember in October.

The job runs about a minute. It pings with `--model haiku`, so the cost is negligible, and with
`--safe-mode --no-session-persistence` so it skips hooks, MCP and plugins.

## Setup

### 1. Keep the repo public

Actions minutes are free and unlimited on public repos with standard runners — verified here:
`billable_ms = 0` on every run. Private would start metering them. Nothing sensitive lives in
the code; the token is a GitHub secret, and secrets are not passed to fork workflows.

### 2. The token secret

```bash
claude setup-token
gh secret set CLAUDE_CODE_OAUTH_TOKEN --repo <owner>/<repo>
```

It must be this token and not an API key. The `sk-ant-oat01-…` token authenticates **the
subscription**, which is what moves the 5-hour window. An API key would spend API credits and
leave the window untouched.

`gh secret set` reads from stdin, so the value never reaches your shell history.

### 3. The external cron

Create **four** jobs at [cron-job.org](https://console.cron-job.org/jobs) — one per target.
They cannot be collapsed into one: the minutes differ per hour, and a single expression like
`57,58,59,0 7,12,17,23 * * *` is a cross product that would fire sixteen times a day.

| Crontab | Fires | Window |
|---|---|---|
| `57 7 * * *`  | 07:57 | → 12:57 |
| `58 12 * * *` | 12:58 | → 17:58 |
| `59 17 * * *` | 17:59 | → 22:59 |
| `0 23 * * *`  | 23:00 | → 04:00 |

**Why the ragged minutes** — this is the one non-obvious thing in the project, see
[Why the targets are staggered](#why-the-targets-are-staggered).

Every job is otherwise identical:

| Field | Value |
|---|---|
| URL | `https://api.github.com/repos/<owner>/<repo>/actions/workflows/refresh.yml/dispatches` |
| Method | `POST` |
| Schedule | Custom → the crontab from the table above |
| Time zone | `Europe/Rome` |
| Request body | `{"ref":"main"}` |
| Save responses in job history | **on** — you will want the body when something fails |

Headers:

```
Authorization: Bearer <PAT>
Accept: application/vnd.github+json
X-GitHub-Api-Version: 2022-11-28
Content-Type: application/json
```

The PAT is a **fine-grained** token, scoped to this repo only, with `Actions: Read and write`
(plus the mandatory read-only `Metadata`). That is the whole blast radius: with it, someone can
trigger this workflow and nothing else.

Turn on cron-job.org's failure notifications — they are the only thing watching the trigger.

The PAT is duplicated across all four jobs, so **rotating it means editing four places.** That is
the cost of the stagger. Enable 2FA on the cron-job.org account: anyone with access to it reads
that token in clear text.

**Success is `204 No Content` with an empty body.** A `404` means the token or its permissions,
not a wrong URL: GitHub masks `403` as `404` on this endpoint so it does not reveal whether the
repo exists.

## Why the targets are staggered

A window lasts exactly 5 hours. If the targets were exactly 5 hours apart, the system would only
re-anchor about half the time — and the reason is worth understanding before changing anything.

A ping does not land at its target. Measured on a real run: the cron fires at `23:00:00`,
cron-job.org's dispatch reaches GitHub at `23:00:44`, the job starts and the ping goes out around
`23:00:56`. Call that total delay `L`. So the window opened by ping N actually expires at
`target + L_N + 5h`, while ping N+1 arrives at `target + 5h + L_{N+1}`. A new window opens only
if:

```
L_{N+1} > L_N
```

**A ping re-anchors only when its run is slower than the previous one.** When it is faster, it
lands inside the window still open and silently does nothing. With targets exactly 5 hours apart
that is close to a coin flip on every hop.

Note that firing the whole schedule a minute early does **not** fix this — it shifts all four
targets equally and leaves the comparison between consecutive runs untouched. What fixes it is
spacing the targets **5h01m** apart instead of 5h00m, which is what the ragged minutes above do.
That buys 60 seconds of margin per hop, and since the observed delay is around 55 seconds it
cannot drop by more than that.

The chain also resets itself every night: the 23:00 window expires at 04:00, so the morning ping
always lands on a clean slate regardless of what happened the day before.

## Changing the hours

Edit the crontabs on cron-job.org. That is it — nothing in this repo encodes them.

Worth knowing while you pick:

- **The hour is when a window *opens*,** so make it when you actually want to start working, not
  a round number for its own sake. The value is knowing the boundary in advance.
- **Space targets 5h01m apart, not 5h00m** — see above. Closer than 5 hours and the ping lands
  inside the previous window and does nothing at all.
- **Four windows cover twenty hours,** so four are always left unanchored. Those hours just
  behave the way Claude Code normally does.

## The log

Every run appends a line to `log/<YYYY-MM>.md` and commits it:

```
2026-09-04 07:57 — window opened (ping 07:57:55) → expires 12:57
```

Everything on that line is derived from **when the ping actually happened**, never from a target
the workflow assumes — it does not know the schedule, and the targets are not on the hour anyway.

The seconds in the ping timestamp are the **trigger delay**, because the cron always fires on a
whole minute: `07:57:55` means 55 seconds from cron to ping. That is the health metric. Watch for
a label that matches **no scheduled minute** (`07:58` when the job fires at `07:57`) — that means
the delay exceeded a minute and spilled into the next one, which is also when the 60-second
stagger margin stops being enough.

One caveat: the line says `window opened` whenever the ping succeeded, and the ping succeeds
whether or not a window was already open. The log proves the plumbing ran, not that a new window
was anchored. For that, see below.

## Verifying that it actually moves the window

Most attempts at this test are confounded, so it is worth doing deliberately.

The trigger opens a window **only when none is already open**. Your own Claude Code sessions open
one too, so if you have used Claude within 5 hours of the target, the ping correctly does nothing
and `/usage` shows a reset that has nothing to do with the run. That is the design working.

A valid test needs all three:

1. **No window open when the ping fires** — your last Claude Code message more than 5 hours
   before the target.
2. **No usage between then and the target** — opening Claude Code and sending anything
   re-anchors the window and ruins it.
3. **A green run at that target**, confirmed in `log/`.

The natural candidate is the first morning target, checked before touching anything else. Then:

```
/usage
```

- **Reset at exactly target + 5 hours, on the round hour** (08:00 → 13:00) — it works.
- **Reset at a ragged time** (12:37) — that window was anchored by a human message. Inconclusive,
  not broken. Retest.

The round hour is the signature: a human's first message never lands at `:00`, the ping always
does.

## Known risks

- **The external cron is a single point of failure.** If cron-job.org is down or the job gets
  disabled after repeated failures, nothing fires and nothing here notices. Their failure
  notifications are the safety net — keep them on.
- **The PAT** can be revoked or expire. Symptom: `404` in the cron-job.org history and no runs on
  GitHub at all.
- **The OAuth token** expires and has to be rotated by hand (`claude setup-token`, then
  `gh secret set`). Symptom: runs appear but the log says `PING FAILED`.
- **If you use Claude shortly before a target**, that target's ping falls inside the window you
  already opened and does nothing. The system realigns at the next target. Property, not bug.

## References

- **[cron-job.org console](https://console.cron-job.org/jobs)** — the trigger. Job
  `claude-refresh`.
- **[Workflow runs](https://github.com/limonequantistico/claude-session-refresh/actions)**
- **[Migration note, 2026-09-03](docs/archive/2026-09-03-scheduler-migration.md)** — why the
  schedule left GitHub, and what was deleted.
