#!/usr/bin/env python3
"""Compute the cron entries and season-guard arms for a given timezone.

Usage:
  python3 .claude/skills/start/schedule.py <IANA_TZ> [target_hour ...]
  python3 .claude/skills/start/schedule.py <IANA_TZ> --check [target_hour ...]
  python3 .claude/skills/start/schedule.py <IANA_TZ> --plan  [target_hour ...]

Example: python3 .claude/skills/start/schedule.py America/New_York 8 13 18 23

The workflow fires cron 30 minutes before each target and sleeps until the exact
second, so the cron entries are the targets shifted back by the head start and
converted to UTC — one set per UTC offset the timezone uses during the year.

--check answers a different question: would `gh workflow run refresh.yml` right
now actually ping, or would it exit clean? A manual run only does something
inside the -LATE_S/+EARLY_S band around a target.

--plan is the handover: when the next cron fires, the upcoming windows, and the
first target that can serve as a valid /usage test given that the current
session is itself usage and has a window open for the next 5 hours.
"""

import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

HEAD_START_MIN = 30  # keep in sync with the 1800 in the workflow's delay math
EARLY_S = 2700       # keep in sync with EARLY_S in the workflow
LATE_S = 3600        # keep in sync with LATE_S in the workflow
WINDOW_H = 5         # a Claude Code usage window lasts 5 hours


def offset_label(off: timedelta) -> str:
    """Format an offset the way `date +%z` does, e.g. +0100, -0430."""
    total = int(off.total_seconds())
    sign = "+" if total >= 0 else "-"
    return f"{sign}{abs(total) // 3600:02d}{abs(total) % 3600 // 60:02d}"


def upcoming(now: datetime, targets: list[int], count: int) -> list[datetime]:
    """The next `count` target instants, in order, starting after `now`."""
    out = []
    day = 0
    while len(out) < count:
        for hour in sorted(targets):
            t = (now + timedelta(days=day)).replace(
                hour=hour, minute=0, second=0, microsecond=0
            )
            if t > now:
                out.append(t)
        day += 1
    return sorted(out)[:count]


def plan(zone: ZoneInfo, tz_name: str, targets: list[int]) -> int:
    """Print the handover timeline: when it fires, when it is live, when to verify."""
    now = datetime.now(zone)
    print(f"Local time in {tz_name}: {now:%F %H:%M %Z}\n")

    slots = upcoming(now, targets, len(targets) + 1)

    print("Upcoming windows")
    for t in slots[: len(targets)]:
        cron = t - timedelta(minutes=HEAD_START_MIN)
        expiry = t + timedelta(hours=WINDOW_H)
        print(f"  {t:%a %H:%M} → {expiry:%H:%M}   (cron fires {cron:%H:%M})")

    print()
    if slots[0] - timedelta(minutes=HEAD_START_MIN) <= now:
        print(f"The cron for the {slots[0]:%H:%M} window already fired at")
        print(f"{slots[0] - timedelta(minutes=HEAD_START_MIN):%H:%M}: if the schedule was registered by then that job")
        print("is sleeping right now, otherwise that window was missed.")
        nxt = slots[1]
    else:
        nxt = slots[0]

    next_cron = nxt - timedelta(minutes=HEAD_START_MIN)
    lead = (next_cron - now).total_seconds() / 60
    if lead < 60:
        print(f"The next cron fires at {next_cron:%H:%M}, only {int(lead)} min from now.")
        print("GitHub takes up to an hour to register a new schedule, so if the workflow")
        print("just landed on the default branch that run may not happen — the")
        print(f"{slots[slots.index(nxt) + 1]:%H:%M} window would then be the first automatic one.")
    else:
        print(f"The next cron fires at {next_cron:%H:%M}, {int(lead // 60)}h {int(lead % 60)}m from now —")
        print("comfortably past the hour GitHub needs to register a new schedule.")

    # Verification: this session is usage, so a window is open until now + 5h.
    open_until = now + timedelta(hours=WINDOW_H)
    valid = next((t for t in slots if t >= open_until), None)
    print("\nFirst target that can serve as a valid test")
    print(f"  This session counts as usage, so a window is open until ~{open_until:%H:%M}.")
    if valid is None:
        print("  No upcoming target clears it. Re-run --plan later.")
        return 0
    gap = (valid - now).total_seconds() / 60
    print(f"  The first target on a clean slate is {valid:%a %H:%M}, in {int(gap // 60)}h {int(gap % 60)}m.")
    print(f"  Do not use Claude Code between ~{open_until:%H:%M} and {valid:%H:%M}, or the")
    print("  window gets anchored by you and the test means nothing.")
    print(f"  After {valid:%H:%M}, run /usage: the reset must read "
          f"{valid + timedelta(hours=WINDOW_H):%H:%M}, on the round hour.")

    clearance = (valid - open_until).total_seconds() / 60
    if clearance < 30:
        later = next((t for t in slots if t > valid), None)
        print(f"\n  Careful: that clears the open window by only {int(clearance)} min, and the")
        print("  window moves with your last message — a few more minutes of this session")
        print("  and the target falls back inside it.")
        if later is not None:
            print(f"  The {later:%a %H:%M} target is the safer one to test on.")
    return 0


def check_now(zone: ZoneInfo, tz_name: str, targets: list[int]) -> int:
    """Report whether a manual dispatch right now would ping, or when it would."""
    now = datetime.now(zone)
    print(f"Local time in {tz_name}: {now:%F %H:%M:%S %Z}\n")

    for hour in sorted(targets):
        for day in (0, 1):
            target = (now + timedelta(days=day)).replace(
                hour=hour, minute=0, second=0, microsecond=0
            )
            delta = (target - now).total_seconds()
            if -LATE_S <= delta <= EARLY_S:
                expiry = target + timedelta(hours=WINDOW_H)
                if delta > 0:
                    print(f"Dispatch now: the job would sleep {int(delta // 60)} min and")
                    print(f"ping at {target:%H:%M} sharp, opening a window until {expiry:%H:%M}.")
                else:
                    print(f"Dispatch now: the {target:%H:%M} target passed {int(-delta // 60)} min")
                    print(f"ago, so the job would ping immediately (late) — window until {expiry:%H:%M}.")
                return 0

    # Nothing usable now: find the next moment a dispatch would start doing something.
    upcoming = []
    for hour in sorted(targets):
        for day in (0, 1):
            target = (now + timedelta(days=day)).replace(
                hour=hour, minute=0, second=0, microsecond=0
            )
            opens = target - timedelta(seconds=EARLY_S)
            if opens > now:
                upcoming.append((opens, target))
    opens, target = min(upcoming)
    wait = int((opens - now).total_seconds() // 60)
    closes = target + timedelta(seconds=LATE_S)
    print("Dispatch now: nothing would happen — no target within the band.")
    print(f"Next usable slot opens at {opens:%H:%M} (in {wait} min) and stays open")
    print(f"until {closes:%H:%M}, for the {target:%H:%M} window.")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__.strip())
        return 2

    tz_name = sys.argv[1]
    args = sys.argv[2:]
    check = "--check" in args
    want_plan = "--plan" in args
    targets = [int(h) for h in args if not h.startswith("--")] or [8, 13, 18, 23]

    try:
        zone = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        print(f"Unknown timezone: {tz_name!r}. Use an IANA name like Europe/Rome.")
        return 2

    if any(h < 1 or h > 23 for h in targets):
        print("Target hours must be between 1 and 23: a 00:00 target would put the")
        print("cron on the previous local day, which the workflow's lookup does not")
        print("handle. Use 01:00 or later.")
        return 2

    if len(set(targets)) != len(targets):
        print("Duplicate target hours.")
        return 2

    if check:
        return check_now(zone, tz_name, targets)

    if want_plan:
        return plan(zone, tz_name, targets)

    for a, b in zip(sorted(targets), sorted(targets)[1:]):
        if b - a < 5:
            print(f"Warning: targets {a}:00 and {b}:00 are less than 5 hours apart.")
            print("Windows last 5 hours, so the second ping lands inside the first")
            print("window and does nothing.\n")

    # One representative instant per distinct UTC offset used during the year.
    year = datetime.now(timezone.utc).year
    reps: dict[timedelta, datetime] = {}
    probe = datetime(year, 1, 1, tzinfo=timezone.utc)
    while probe < datetime(year + 1, 1, 1, tzinfo=timezone.utc):
        reps.setdefault(probe.astimezone(zone).utcoffset(), probe)
        probe += timedelta(hours=6)

    entries = []
    for off, rep in sorted(reps.items()):
        local = rep.astimezone(zone)
        slots = set()
        for hour in targets:
            target = local.replace(hour=hour, minute=0, second=0, microsecond=0)
            if target.utcoffset() != off:  # target sits on the far side of a DST jump
                target = (local + timedelta(days=1)).replace(
                    hour=hour, minute=0, second=0, microsecond=0
                )
            utc = (target - timedelta(minutes=HEAD_START_MIN)).astimezone(timezone.utc)
            slots.add((utc.minute, utc.hour))

        minutes = {m for m, _ in slots}
        if len(minutes) != 1:
            print(f"Cannot express offset {offset_label(off)} as a single cron entry.")
            return 1
        hours = ",".join(str(h) for _, h in sorted(slots, key=lambda s: s[1]))
        entries.append((offset_label(off), f"{minutes.pop()} {hours} * * *"))

    print(f"# {tz_name}, targets {':00, '.join(str(h) for h in sorted(targets))}:00 local")
    print(f"# {len(entries)} UTC offset(s) in use during {year}\n")

    print("--- .github/workflows/refresh.yml, the `on:` block ---\n")
    print("on:")
    print("  schedule:")
    for label, cron in entries:
        print(f"    - cron: '{cron}'   # UTC{label}")
    print("  workflow_dispatch:\n")

    print("--- the job's `env:` block ---\n")
    print(f"      TZ: {tz_name}")
    print(f"      TARGET_HOURS: '{' '.join(str(h) for h in sorted(targets))}'\n")

    print("--- the season guard's `case` in the 'Resolve target' step ---\n")
    print("          case \"$offset\" in")
    for label, cron in entries:
        print(f"            {label}) expected='{cron}' ;;")
    print("            *)     expected='' ;;")
    print("          esac")

    if len(entries) == 1:
        print("\nThis timezone has no DST, so one cron entry is enough and the season")
        print("guard never rejects anything. Keep it anyway: it costs nothing and it")
        print("stays correct if the timezone's rules change.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
