---
name: setup
description: Set up claude-session-refresh, or change which hours it fires at. Covers repo visibility, the OAuth token secret, the external cron on cron-job.org, and the /usage proof. Use when the user runs /setup in this repo, asks how to set this project up, wants to change or move the refresh times, add or drop a window, switch timezone, or asks why its runs are not firing.
---

You are setting up **claude-session-refresh**. It opens a Claude Code usage window at fixed
local times by running the `claude` CLI from GitHub Actions, triggered by an external cron.
`README.md` has the reasoning; this skill is the operational path.

The setup is idempotent. Run Phase 0 first and **skip whatever is already green** — do not
re-run steps that are done, and do not re-ask questions the repo already answers.

**Read this before anything else:** the schedule is **not in this repo**. It lives in a
cron-job.org job. If the user wants different hours, that is Phase 4 alone — do not touch the
workflow, and do not drag them through the token or the visibility check to change a number.

## Hard rules

- **Never accept the OAuth token or the GitHub PAT in the conversation.** Both are live
  credentials. If the user pastes one, tell them plainly that it is now in the transcript, that
  they should rotate it (`claude setup-token` for the OAuth token; regenerate the PAT on
  GitHub), and do not use it. Do not write either to a file, a commit, an env var, or a `gh`
  command line.
- Only the user runs `claude setup-token` and `gh secret set`. You verify with
  `gh secret list`, which prints **names only** — never values.
- You cannot see or edit the cron-job.org job. Give the user the values; they enter them.
- Do not push, open PRs, merge, or flip repo visibility without explicit confirmation. Editing
  the workflow in the working tree is fine.

## Phase 0 — status check

```bash
gh auth status
gh repo view --json nameWithOwner,visibility,defaultBranchRef
gh secret list
gh workflow list
git branch --show-current && git log --oneline -3
gh run list --workflow=refresh.yml --limit 5 --json createdAt,event,conclusion
tail -5 log/*.md 2>/dev/null
```

| Check | Green means |
|---|---|
| `gh auth status` | the CLI can act on the repo at all |
| `visibility` | `PUBLIC` — Actions minutes are free |
| `gh secret list` | `CLAUDE_CODE_OAUTH_TOKEN` exists |
| `gh workflow list` | `refresh` is registered, i.e. it is on the default branch |
| `gh run list` | recent runs, `event` = `workflow_dispatch`, landing on the hour |
| `tail log/*.md` | recent lines with a drift in **seconds**, not minutes |

Two failure signatures worth naming, because they look alike and are not:

- **No runs at all** → the trigger never arrived. The problem is cron-job.org or the PAT, not
  this repo. Send the user to their job's history to read the HTTP status.
- **Runs exist but say `PING FAILED`** → the trigger works and the OAuth token does not. Phase 3.

## Phase 1 — repo visibility

If the repo is `PRIVATE`, explain: public repos get free unlimited Actions minutes on standard
runners, private ones are metered. Nothing sensitive lives in the code — the token is a secret,
and secrets are not passed to fork workflows.

Making a repo public is irreversible in practice (it can be indexed and forked within seconds).
**Ask before doing it**, and only then:

```bash
gh repo edit --visibility public --accept-visibility-change-consequences
```

## Phase 2 — get the workflow onto the default branch

`workflow_dispatch` only sees the **default branch**. If `gh workflow list` does not show
`refresh`, it is not there yet. Check with `git log --oneline origin/<default>..HEAD`, then tell
the user what is needed — merge the branch, or push and open a PR. Ask before pushing anything.

Unlike the old scheduled setup, there is **no registration delay**: once the workflow is on the
default branch, a dispatch works immediately.

## Phase 3 — the token secret

If `gh secret list` does not show `CLAUDE_CODE_OAUTH_TOKEN`, give the user these to run
**themselves**:

```bash
claude setup-token
gh secret set CLAUDE_CODE_OAUTH_TOKEN --repo <owner>/<repo>
```

`gh secret set` reads from stdin, so the value never reaches their shell history or this
conversation.

Explain why it must be this token and not an API key: the `sk-ant-oat01-…` token authenticates
the subscription, which is what moves the 5-hour window. An API key would spend API credits and
leave the window untouched.

Confirm with `gh secret list` (names only). Wait for the user before continuing.

## Phase 4 — the external cron

This is both a setup step and **the way to change the hours later**.

### Agreeing on the hours

**Ask one question: what hour does the user want their day to start?** A window is 5 hours long,
so the start hour determines the rest — 8 gives `8 13 18 23`, 10 gives `10 15 20 1`. Do not ask
for a list of four.

Useful while they decide:

- **The hour is when a window opens,** so it should be when they actually want to start working.
  The whole value is knowing the boundary ahead.
- **Four windows cover twenty hours,** so four are always unanchored — usually the night.
- **Space them 5h01m apart, not 5h00m** — see below. Closer than 5 hours and the ping lands
  inside the previous window and does nothing at all.

Fewer windows is a legitimate choice — someone who only works mornings can use two targets.
Offer it if they ask; do not lead with it.

### The stagger — explain this, do not just hand over the numbers

A window lasts exactly 5 hours, and a ping does not land at its target: dispatch plus job startup
add roughly 55 seconds. So the window from ping N expires at `target + L_N + 5h` while ping N+1
arrives at `target + 5h + L_{N+1}`, and a new window opens **only if `L_{N+1} > L_N`** — only if
that run happened to be slower than the previous one. At exactly 5 hours apart it is close to a
coin flip every hop.

Two things users get wrong here:

- **Firing everything a minute early does not fix it.** It shifts all targets equally and leaves
  the comparison between consecutive runs untouched.
- **The minutes must differ per target,** so this cannot be one cron expression: `57,58,59,0
  7,12,17,23 * * *` is a cross product that fires sixteen times a day. It is **one job per
  target**.

The shipped schedule, 5h01m apart with the last anchored on the hour:

| Crontab | Fires | Window |
|---|---|---|
| `57 7 * * *`  | 07:57 | → 12:57 |
| `58 12 * * *` | 12:58 | → 17:58 |
| `59 17 * * *` | 17:59 | → 22:59 |
| `0 23 * * *`  | 23:00 | → 04:00 |

Reassure them about the failure mode: the chain resets nightly, because the last window expires
at 04:00 and the morning ping always lands on a clean slate.

### The jobs

Four jobs, identical except the crontab. Give the user these values:

| Field | Value |
|---|---|
| URL | `https://api.github.com/repos/<owner>/<repo>/actions/workflows/refresh.yml/dispatches` |
| Method | `POST` |
| Schedule | Custom → one crontab from the table above |
| Time zone | their IANA zone, e.g. `Europe/Rome` |
| Request body | `{"ref":"main"}` |
| Save responses in job history | on |
| Failure notifications | on |

```
Authorization: Bearer <PAT>
Accept: application/vnd.github+json
X-GitHub-Api-Version: 2022-11-28
Content-Type: application/json
```

The PAT is **fine-grained**, scoped to this repo only, `Actions: Read and write` plus the
mandatory read-only `Metadata`. Tell them the blast radius: with that token someone can trigger
this workflow and nothing else — not read the code, not modify the workflow, not reach the OAuth
token, which never leaves GitHub.

It is duplicated across all four jobs, so say plainly that **rotating it means editing four
places**, and recommend 2FA on the cron-job.org account, where the token sits in clear text.

**Set the time zone on the job.** That is what makes DST a non-issue — do not have them convert
to UTC.

Reading the result: **`204 No Content`** is success. **`404`** is the token or its permissions,
not the URL — GitHub masks `403` as `404` here. **`422`** is a bad `ref`.

### Changing hours that are already live

Only two things to say, and they are what people get wrong:

1. **Nothing in the repo changes.** No commit, no deploy. The workflow does not encode the hours.
2. **Keep the 1-minute stagger** when they move the hours, or they lose the margin and go back to
   re-anchoring about half the time.
3. **Old log lines keep the old hours.** That is history, not drift — leave it.

Then hand over the new times concretely: list the upcoming windows with their expiries.

## Phase 5 — the first run

This proves the **plumbing**: the trigger arrives, authentication works, the ping succeeds, the
log commits. It does **not** prove the window moved — that is Phase 6. Do not conflate them.

Unlike the old design, a dispatch works at any time: there is no target band to be inside of. So
this is always available, but it is **not free** — it opens a real usage window.

**Ask before dispatching. Always.** Put the decision in front of them:

- it opens a window right now, running for 5 hours;
- that **spends the clean slate**, so every target inside those 5 hours becomes untestable per
  Phase 6;
- the alternative is to wait for the next scheduled trigger, which costs a wait and keeps the
  verification clean.

Recommend skipping it when the token is already confirmed present and the next trigger is close.
Recommend dispatching when the token has just been set and they want to know now.

Once they say yes:

```bash
gh workflow run refresh.yml
sleep 10 && gh run list --workflow=refresh.yml --limit 1
gh run watch <run-id>
```

It takes about a minute. Then check all three:

```bash
gh run view <run-id>
gh run view <run-id> --log | tail -30
git pull && tail -3 log/*.md
```

A green run adds a line like:

```
2026-09-03 23:00 — window opened (+44s) → expires 04:00
```

Look at the drift. **Seconds is healthy.** Minutes means the trigger is lagging and is worth
investigating before it grows.

## Phase 6 — the proof that matters

Everything above proves the job ran, not that the ping **moved the usage window**. Most attempts
at this test are confounded.

The trigger opens a window **only when none is already open**. If any window is open when the
ping fires, the ping correctly does nothing and `/usage` shows an unrelated reset. And a window
is almost always open, because the user's own sessions open one — **including the session running
this skill**. Setting the project up is itself usage.

So the naive test ("dispatch a run, then check `/usage`") is not merely unreliable, it is
*systematically* wrong: it will nearly always show an unrelated reset on a project that works.

Never conclude from a confounded test. An unrelated reset means **inconclusive**, not broken.

All three conditions must hold:

1. **No window open when the ping fires** — their last Claude Code message, including this
   session, more than 5 hours before the target. Ask when they last used it; do not assume.
2. **No usage between then and the target.**
3. **A green run at that target**, confirmed from `log/`.

The natural candidate is the **first morning target**, checked before touching anything else.
Setting up late at night works well: a session ending at 00:15 leaves a window expiring at 05:15,
so the 08:00 ping lands clean.

This usually means the verification **cannot happen in the same sitting as the setup**. Say so
plainly rather than running a test that cannot mean anything.

Then the user runs `/usage`:

- **Reset at exactly target + 5 hours, on the round hour** (08:00 → 13:00) — it works.
- **Reset at a ragged time** (12:37) — anchored by a human message. Inconclusive; retest.
- **Reset at target + 5h but the conditions were not met** — still inconclusive, just lucky.

The round hour is the signature: a human's first message never lands at `:00:0x`, the ping always
does. If their `/usage` shows only a coarse time and you cannot tell round from ragged, say the
test is not decisive rather than guessing.

Only when a test meeting all three conditions comes back with an unrelated reset does the premise
actually fail. **Then** stop and say so — do not paper over it.

## Phase 7 — the handover

Do not end on "now wait". End on **dates and times**: the upcoming windows with their expiries,
which one is the first valid `/usage` test given that this session has a window open, and the two
places to look when something breaks — the cron-job.org history for the trigger, `log/` and
`gh run list` for the run.
