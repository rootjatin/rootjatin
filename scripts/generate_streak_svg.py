#!/usr/bin/env python3
import argparse
import json
import os
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from urllib.request import Request, urlopen

GQL_URL = "https://api.github.com/graphql"

QUERY = """
query($login:String!, $from:DateTime!, $to:DateTime!) {
  user(login: $login) {
    createdAt
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        weeks {
          contributionDays {
            date
            contributionCount
          }
        }
      }
    }
  }
}
"""

def gql(token: str, login: str, from_iso: str, to_iso: str) -> dict:
    payload = {"query": QUERY, "variables": {"login": login, "from": from_iso, "to": to_iso}}
    req = Request(
        GQL_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "rootjatin-profile-assets",
        },
        method="POST",
    )
    with urlopen(req) as r:
        return json.loads(r.read().decode("utf-8"))

def fetch_days(token: str, user: str, from_day: date, to_day_exclusive: date) -> tuple[date, dict[date, int]]:
    from_iso = f"{from_day.isoformat()}T00:00:00Z"
    to_iso = f"{to_day_exclusive.isoformat()}T00:00:00Z"
    data = gql(token, user, from_iso, to_iso)

    if "errors" in data:
        raise SystemExit("GraphQL error: " + json.dumps(data["errors"], indent=2))

    u = data["data"]["user"]
    created_at = datetime.fromisoformat(u["createdAt"].replace("Z", "+00:00")).date()

    day_counts: dict[date, int] = {}
    cal = u["contributionsCollection"]["contributionCalendar"]
    for w in cal["weeks"]:
        for d in w["contributionDays"]:
            day_counts[date.fromisoformat(d["date"])] = int(d["contributionCount"])

    return created_at, day_counts

def compute_current_streak_details(day_counts: dict[date, int], today_local: date) -> tuple[int, date | None, date | None]:
    """
    Current streak:
    - If today has contributions -> ends today
    - else if yesterday has contributions -> ends yesterday
    - else -> 0
    Returns: (length, start_date, end_date)
    """
    if day_counts.get(today_local, 0) > 0:
        end = today_local
    elif day_counts.get(today_local - timedelta(days=1), 0) > 0:
        end = today_local - timedelta(days=1)
    else:
        return 0, None, None

    length = 0
    d = end
    while day_counts.get(d, 0) > 0:
        length += 1
        d -= timedelta(days=1)

    start = end - timedelta(days=length - 1)
    return length, start, end

def compute_top_two_longest_streaks(day_counts: dict[date, int]) -> tuple[
    tuple[int, date | None, date | None],
    tuple[int, date | None, date | None],
]:
    """
    Finds top 2 longest non-overlapping streak segments (they're naturally non-overlapping).
    Returns:
      (len1, start1, end1), (len2, start2, end2)
    """
    dates = sorted(day_counts.keys())
    if not dates:
        return (0, None, None), (0, None, None)

    segments: list[tuple[int, date, date]] = []
    run_len = 0
    run_start: date | None = None
    prev: date | None = None

    for d in dates:
        # If there's a gap in dates (shouldn't usually happen), treat as break
        if prev is not None and d != prev + timedelta(days=1):
            if run_len > 0 and run_start is not None:
                segments.append((run_len, run_start, prev))
            run_len = 0
            run_start = None

        c = day_counts.get(d, 0)
        if c > 0:
            if run_len == 0:
                run_start = d
            run_len += 1
        else:
            if run_len > 0 and run_start is not None:
                segments.append((run_len, run_start, prev if prev is not None else d))
            run_len = 0
            run_start = None

        prev = d

    # Close trailing run
    if run_len > 0 and run_start is not None and prev is not None:
        segments.append((run_len, run_start, prev))

    # Sort by length desc, then end desc (more recent first), then start desc
    segments.sort(key=lambda x: (-x[0], -x[2].toordinal(), -x[1].toordinal()))

    if len(segments) == 0:
        return (0, None, None), (0, None, None)
    if len(segments) == 1:
        l1, s1, e1 = segments[0]
        return (l1, s1, e1), (0, None, None)

    l1, s1, e1 = segments[0]
    l2, s2, e2 = segments[1]
    return (l1, s1, e1), (l2, s2, e2)

def sum_last_n_days(day_counts: dict[date, int], end_day: date, n: int) -> int:
    start = end_day - timedelta(days=n - 1)
    total = 0
    d = start
    while d <= end_day:
        total += day_counts.get(d, 0)
        d += timedelta(days=1)
    return total

def fmt_range(start: date | None, end: date | None) -> str:
    if start is None or end is None:
        return "—"
    return f"{start.isoformat()} → {end.isoformat()}"

def render_svg(
    user: str,
    total_last_n: int,
    total_days: int,
    cur_len: int,
    cur_start: date | None,
    cur_end: date | None,
    long1_len: int,
    long1_start: date | None,
    long1_end: date | None,
    long2_len: int,
    long2_start: date | None,
    long2_end: date | None,
    as_of: date,
    tz: str,
) -> str:
    # Taller to fit two longest streak blocks
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="720" height="220" viewBox="0 0 720 220" role="img" aria-label="GitHub streak for {user}">
  <rect x="0.5" y="0.5" width="719" height="219" rx="18" ry="18" fill="#0d1117" stroke="#30363d"/>

  <text x="24" y="34" fill="#c9d1d9" font-size="20"
        font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto">
    {user} • Streak (computed from GitHub API)
  </text>

  <!-- Row 1: Current + Total -->
  <text x="24" y="62" fill="#8b949e" font-size="13"
        font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto">Current streak</text>
  <text x="24" y="88" fill="#58a6ff" font-size="22" font-weight="700"
        font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto">{cur_len} day(s)</text>
  <text x="24" y="110" fill="#8b949e" font-size="12"
        font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto">{fmt_range(cur_start, cur_end)}</text>

  <!-- FIXED: Total (last Nd) value now directly under the title -->
  <text x="540" y="62" fill="#8b949e" font-size="13" text-anchor="middle"
        font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto">Total (last {total_days}d)</text>
  <text x="540" y="88" fill="#58a6ff" font-size="22" font-weight="700" text-anchor="middle"
        font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto">{total_last_n}</text>

  <!-- Row 2: Longest #1 + Longest #2 -->
  <text x="24" y="140" fill="#8b949e" font-size="13"
        font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto">Longest streak</text>
  <text x="24" y="166" fill="#58a6ff" font-size="22" font-weight="700"
        font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto">{long1_len} day(s)</text>
  <text x="24" y="188" fill="#8b949e" font-size="12"
        font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto">{fmt_range(long1_start, long1_end)}</text>

  <text x="390" y="140" fill="#8b949e" font-size="13"
        font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto">2nd longest streak</text>
  <text x="390" y="166" fill="#58a6ff" font-size="22" font-weight="700"
        font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto">{long2_len} day(s)</text>
  <text x="390" y="188" fill="#8b949e" font-size="12"
        font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto">{fmt_range(long2_start, long2_end)}</text>

  <text x="24" y="212" fill="#8b949e" font-size="12"
        font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto">
    As of {as_of.isoformat()} ({tz})
  </text>
</svg>
"""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tz", default="UTC")
    ap.add_argument("--max-years", type=int, default=8, help="How many years of history to fetch (chunked by 1-year windows).")
    ap.add_argument("--total-days", type=int, default=365, help="Total contributions shown for last N days.")
    args = ap.parse_args()

    token = os.getenv("GH_TOKEN")
    if not token:
        raise SystemExit("GH_TOKEN is required. Use secrets.GITHUB_TOKEN or create a secret GH_STATS_TOKEN.")

    tzinfo = ZoneInfo(args.tz)
    today_local = datetime.now(tzinfo).date()

    # Fetch a recent window first (also yields createdAt)
    recent_from = today_local - timedelta(days=364)
    recent_to_excl = today_local + timedelta(days=1)
    created_at, day_counts = fetch_days(token, args.user, recent_from, recent_to_excl)

    wanted_start = today_local - timedelta(days=args.max_years * 366)
    start_day = max(created_at, wanted_start)

    # Backfill history in <= 1-year chunks up to recent_from
    cur_start = start_day
    while cur_start < recent_from:
        cur_end = min(cur_start + timedelta(days=365), recent_from)
        _, chunk = fetch_days(token, args.user, cur_start, cur_end)
        day_counts.update(chunk)
        cur_start = cur_end

    if not day_counts:
        raise SystemExit("No contribution data returned. Check token permissions / username.")

    # Current streak + range
    cur_len, cur_start_d, cur_end_d = compute_current_streak_details(day_counts, today_local)
    as_of = cur_end_d if cur_end_d else today_local

    # Top 2 longest streaks + ranges (over fetched history)
    (long1_len, long1_start, long1_end), (long2_len, long2_start, long2_end) = compute_top_two_longest_streaks(day_counts)

    # Total contributions over last N days ending at as_of
    total_last_n = sum_last_n_days(day_counts, as_of, args.total_days)

    svg = render_svg(
        user=args.user,
        total_last_n=total_last_n,
        total_days=args.total_days,
        cur_len=cur_len,
        cur_start=cur_start_d,
        cur_end=cur_end_d,
        long1_len=long1_len,
        long1_start=long1_start,
        long1_end=long1_end,
        long2_len=long2_len,
        long2_start=long2_start,
        long2_end=long2_end,
        as_of=as_of,
        tz=args.tz,
    )

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out), open(args.out, "w", encoding="utf-8") as f:
        f.write(svg)

if __name__ == "__main__":
    main()
