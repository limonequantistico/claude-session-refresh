---
name: setup
description: Set up claude-session-refresh, or change which hours it fires at. Covers repo visibility, timezone and target hours, the cron schedule, the OAuth token secret, the first run, and the /usage proof. Use when the user runs /setup in this repo, asks how to set this project up, wants to change or move the refresh times, add or drop a window, switch timezone, or asks why its scheduled runs are not working.
---

You are setting up **claude-session-refresh** for the user. The project opens a Claude Code
usage window at fixed local times by running the `claude` CLI from GitHub Actions. Read
`README.md` if you need the reasoning behind any step; this skill is the operational path.

The setup is idempotent. Always run Phase 0 first and **skip whatever is already done** — do not
re-run steps that are green, and do not re-ask questions the repo already answers.

**Two entry points.** If the user is setting the project up, walk all the phases in order. If the
project already works and they only want **different hours or a different timezone** — moving a
window, adding one, dropping one, moving abroad — that is Phase 2 plus Phase 7, and nothing
else. Do not drag them back through the token or the visibility check to change a number.

## Hard rules

- **Never accept the OAuth token in the conversation.** It is a live credential for the user's
  subscription. If the user pastes one, tell them plainly that it is now in the transcript, that
  they should rotate it with `claude setup-token`, and do not use it. Do not write it to a file,
  a commit, an env var, or a `gh` command line.
- Only the user runs `claude setup-token` and `gh secret set`. You verify with
  `gh secret list`, which prints **names only** — never values.
- Do not push, open PRs, merge, or flip repo visibility without explicit confirmation. Editing
  the workflow in the working tree is fine.

## Phase 0 — status check

Run these read-only checks and report a short checklist of what is done and what is missing.

```bash
gh auth status
gh repo view --json nameWithOwner,visibility,defaultBranchRef
gh secret list
gh workflow list
git branch --show-current
git log --oneline -3
python3 .claude/skills/setup/schedule.py --show
ls log/ 2>/dev/null
```

What each one tells you:

| Check | Green means |
|---|---|
| `gh auth status` | the CLI can act on the repo at all |
| `visibility` | `PUBLIC` — Actions minutes are free and unlimited |
| `gh secret list` | `CLAUDE_CODE_OAUTH_TOKEN` exists |
| `gh workflow list` | `refresh` is registered, i.e. the workflow is on the default branch |
| `--show` | the schedule is self-consistent, and its TZ and hours are the ones the user actually wants |
| `ls log/` | at least one run has already succeeded |

`--show` exits non-zero when the four places the schedule lives have drifted apart. Its most
important finding is a cron entry with **no matching guard arm**: that entry is not broken in any
visible way, it just exits early on every run, forever. Nothing else reports that.

Then work through the phases below, doing only the ones that are not green.

## Phase 1 — repo visibility

If the repo is `PRIVATE`, explain the arithmetic: the job sleeps up to 30 minutes per run, four
runs a day is roughly 1900–3700 minutes a month, and private repos are capped at 500 (Free) or
3000 (Pro) — so it will overrun. Public repos have free unlimited minutes, and nothing sensitive
lives in the code: the token is a secret, and secrets are not passed to fork workflows.

Making a repo public is irreversible in practice (it can be indexed and forked within seconds).
**Ask before doing it**, and only then:

```bash
gh repo edit --visibility public --accept-visibility-change-consequences
```

## Phase 2 — timezone and target hours

This is both a setup step and the way to **change the hours later**. The repo ships with
`Europe/Rome` and targets `8 13 18 23`; nothing about those numbers is special.

### Agreeing on the hours

Show the user what is configured now (`--show`) and ask what they want instead. Useful things to
tell them while they decide:

- **Each target anchors a 5-hour window**, so the hours are the *starts*: `8 13 18 23` gives
  `8–13`, `13–18`, `18–23`, `23–04`.
- **Four targets 5 hours apart tile the day with no overlap and no gap** except the one you
  choose to leave. The stock layout leaves 04:00–08:00 unanchored on purpose, because nobody
  needs the night pinned.
- **Fewer targets is a legitimate choice.** Someone who only works mornings can run `8 13` and
  leave the rest alone; the unanchored hours simply behave the way Claude Code does by default.
- **They should be the hours the user wants to *start* working**, not round numbers for their own
  sake. The whole value is knowing the boundary in advance.

The script rejects or warns about the rest:

- **Targets must be 01:00 or later.** A 00:00 target puts the cron on the previous local day,
  which the workflow's `date -d "today H:00"` lookup does not handle.
- **Targets closer than 5 hours overlap.** The second ping lands inside the first window and does
  nothing. The script warns; it is not fatal, just pointless.
- **A timezone without DST needs only one cron entry.** That is handled automatically.

### Applying the change

Let the script write it. There are four coupled places — the headline comment, the `on:` cron
entries, the job's `TZ` / `TARGET_HOURS`, and the season guard's `case` — and getting three of
four right produces a workflow that looks correct and silently never fires:

```bash
python3 .claude/skills/setup/schedule.py <IANA_TZ> --apply [hours...]
```

It refuses to write unless the result comes out self-consistent, so a failure leaves the file
untouched. Confirm afterwards, and check the workflow still parses:

```bash
python3 .claude/skills/setup/schedule.py --show
ruby -ryaml -e 'YAML.load_file(".github/workflows/refresh.yml"); puts "YAML ok"'
```

If the user would rather paste the blocks themselves, the same command without `--apply` prints
them instead of writing.

### Changing a schedule that is already live

Say these three things — they are what people get wrong:

1. **It takes effect only once it reaches the default branch.** An edit sitting on a branch
   changes nothing.
2. **A job already sleeping keeps its old target.** If a run is mid-sleep when the change lands,
   it still pings at the hour it woke up for. The new times start from the next cron.
3. **Old log lines keep the old hours.** That is history, not drift — leave it.

Then go to Phase 7 and hand over the new times concretely.

## Phase 3 — the token secret

If `gh secret list` does not show `CLAUDE_CODE_OAUTH_TOKEN`, give the user these two commands to
run **themselves**, and explain that `gh secret set` reads the value from stdin so it never
reaches their shell history or this conversation:

```bash
claude setup-token
gh secret set CLAUDE_CODE_OAUTH_TOKEN --repo <owner>/<repo>
```

Explain why it must be this token and not an API key: the `sk-ant-oat01-…` token authenticates
the subscription, which is what moves the 5-hour window. A regular API key would spend API
credits and leave the window untouched.

Then confirm with `gh secret list` (names only). Wait for the user before continuing.

## Phase 4 — get the workflow onto the default branch

Scheduled runs and `workflow_dispatch` both only see the **default branch**. If
`gh workflow list` does not show `refresh`, the workflow is not there yet.

Check where things stand with `git branch --show-current` and
`git log --oneline origin/<default>..HEAD`, then tell the user what is needed — merge the branch,
or push it and open a PR. Ask before pushing or opening anything.

Also tell them: **GitHub takes up to an hour to register a new schedule.** This does not mean the
first run must be manual — it means a cron due within the next hour of the merge may be missed,
and the one after it will fire normally. `--plan` in Phase 7 says which case they are in.

A manual dispatch is therefore a choice, not a requirement, and it is not free: see the gate in
Phase 5. If the merge lands comfortably before the next cron, letting the schedule fire on its
own is the better path — it costs nothing and it keeps Phase 6 testable.

## Phase 5 — the first run

This phase proves the **plumbing**: authentication, target resolution, the ping, the log commit.
It does not prove the window moved — that is Phase 6, and it needs conditions this run almost
certainly does not meet. Do not conflate the two, and do not let a green run here stand in for
the verification.

A manual dispatch only pings inside the band around a target (60 minutes late to 45 minutes
early). Outside it, the run exits clean and proves nothing about the token. Check first:

```bash
python3 .claude/skills/setup/schedule.py <IANA_TZ> --check [hours...]
```

If it says nothing would happen, tell the user when the next usable slot opens and offer to run
it then — do not fire a dispatch that cannot ping and then call the setup verified.

**Ask before dispatching. Always, even when the slot is open.** This is not a read-only
command: it opens a real usage window, and that has a cost the user may not want to pay right
now. Put the decision in front of them in one short block:

- the exact local time the job would ping, and the window it would open (`--check` prints both);
- that this **spends the clean slate** — the window it opens runs for 5 hours, so every target
  inside those 5 hours becomes untestable per Phase 6;
- the alternative: skip the dispatch and let the first scheduled cron do it, which costs a wait
  but keeps the verification clean.

Recommend skipping the dispatch when the token is already confirmed present and the next
scheduled run is close: the dispatch mostly proves the plumbing, and Phase 6 is the claim that
actually matters. Recommend dispatching when the token has just been set and the user wants to
know now whether authentication works at all.

Once they say yes:

```bash
gh workflow run refresh.yml
sleep 10 && gh run list --workflow=refresh.yml --limit 1
gh run watch <run-id>
```

The job may sleep up to 45 minutes before pinging, so `gh run watch` can sit quiet for a while —
that is the design working, not a hang. When it finishes, check all three:

```bash
gh run view <run-id>                 # every step green
gh run view <run-id> --log | tail -30
git pull && cat log/*.md             # the log line was committed
```

A green run should have added a line like:

```
2026-08-17 08:00 — window opened (cron 4 min late) → expires 13:00
```

## Phase 6 — the proof that matters

Everything above only proves the job ran. It does not prove the ping *moved the usage window*.
That is a different claim and it needs a different setup — most attempts at it are confounded.

### Why the obvious test does not work

The trigger opens a window **only when none is already open**. So if any window is open when the
ping fires, the ping correctly does nothing and `/usage` shows a reset that has nothing to do
with the run. That is the design working, not a failure.

And a window is almost always open, because **the user's own Claude Code sessions open one** —
including the session running this very skill. Setting the project up is itself usage. So the
naive test ("dispatch a run, then check `/usage`") is not just unreliable, it is *systematically*
wrong: it will nearly always show an unrelated reset, on a project that is working perfectly.

Never conclude from a confounded test. An unrelated reset time means **inconclusive**, not
broken.

### The conditions for a valid test

All three must hold:

1. **No window open when the ping fires.** The user's last Claude Code message — including the
   setup session — must be more than 5 hours before the target. Ask them when they last used it;
   do not assume.
2. **No usage between that point and the target.** Opening Claude Code and sending anything
   before the target re-anchors the window and ruins the run.
3. **A green run at that target**, confirmed from `log/` or the run summary.

In practice the natural candidate is the **first morning target**, checked before touching
anything else. Setting up late at night works well: a session ending at 00:15 leaves a window
that expires at 05:15, so the 08:00 ping lands on a clean slate.

This means the verification usually **cannot happen in the same sitting as the setup**. Say so
plainly rather than running a test that cannot mean anything.

### Reading the result

After a valid run, the user opens Claude Code and runs `/usage`:

```
/usage
```

- **Reset at exactly target + 5 hours, on the round hour** (08:00 ping → 13:00) — the ping
  anchored the window. The project works.
- **Reset at a ragged time** (12:37) — that window was anchored by a human message, not by the
  ping. Conditions 1 or 2 were not met. Inconclusive: retest.
- **Reset at target + 5h but the conditions were not met** — still inconclusive, just lucky.

The round hour is the signature worth pointing at: a human's first message never lands at
:00:0x, the ping always does. If `/usage` in the user's version displays only a coarse time and
you cannot tell a round reset from a ragged one, say that the test is not decisive rather than
guessing.

Only when a test that met all three conditions comes back with an unrelated reset does the
premise of the project actually fail. **Then** stop and say so — do not paper over it or move on
to tuning.

## Phase 7 — the handover

Do not end on "now wait". End on **dates and times**, so the user knows exactly when the thing
starts working and when they are supposed to look at it. Get them from the script rather than
doing the arithmetic yourself:

```bash
python3 .claude/skills/setup/schedule.py <IANA_TZ> --plan [hours...]
```

It prints the upcoming windows with their cron times, whether the next cron is far enough out to
have been registered, and the first target that can serve as a valid `/usage` test given that
**this session is itself usage** and holds a window open for the next 5 hours.

Close with a handover that answers four questions, in this order:

1. **When does the first automatic run fire?** The cron time, not the target — and whether it is
   more than an hour away, because a schedule that just landed on the default branch may not be
   registered yet.
2. **When does the first window open, and what does it cover?** e.g. "08:00 → 13:00, then 13:00,
   18:00, 23:00 from then on, every day."
3. **When should the user check, and what exactly should they see?** The target from `--plan`,
   and the reset time it must show, on the round hour.
4. **What must they not do in the meantime?** The quiet stretch: no Claude Code — including
   asking you to check on it — between the end of the current window and that target. This is
   the instruction most likely to be broken by accident, so make it the last thing you say.

Add the honest caveat that until step 3 comes back clean, the project is *installed*, not
*proven*.

If `--plan` warns that the clearance is thin, say so and point at the later target instead. Do
not talk the user into a test that a two-minute follow-up question would invalidate.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `/usage` shows a reset unrelated to the run | a window was already open when the ping fired — usually one of the user's own sessions, possibly the setup session itself | inconclusive, **not** a failure; retest under the Phase 6 conditions |
| Ping step fails on authentication | token expired, wrong secret name, or secret never set | user re-runs `claude setup-token` + `gh secret set`; confirm the name is exactly `CLAUDE_CODE_OAUTH_TOKEN` |
| Run is green but no ping, summary says "no nearby target" | dispatched outside the band | re-run inside a slot, use `--check` |
| Run is green but no ping, summary says "out-of-season cron" | correct behaviour — the other cron entry handles this season | nothing to fix |
| Every scheduled run says "out-of-season cron" | `cron:` entries and the guard's `case` arms drifted apart | `--show` to confirm, then `--apply` to rewrite all four places at once |
| Windows open at the wrong hour after a timezone or DST change | `TZ` and the cron entries disagree | `--show`, then `--apply` with the right timezone |
| Scheduled runs never fire | workflow not on the default branch, or schedule not registered yet | Phase 4; wait up to an hour |
| Scheduled runs stopped after ~60 days | GitHub disables schedules on inactive public repos | the log commit normally prevents this; re-enable in the Actions tab |
| Window opens late, log says a big delay | GitHub cron delay exceeded the 30-minute head start | move the cron earlier and raise `EARLY_S` to match (see README, "Widening the buffer") |
| Log commit fails to push | concurrent run touched the same file | the workflow retries with rebase three times; check for a stuck concurrent run |

## When you are done

Report the final state as a short checklist, and say explicitly which items the user still has
to do themselves — realistically the `/usage` check, and the token if it was not set yet.
