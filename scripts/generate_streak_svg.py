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
    """
    Fetch contribution days in [from_day, to_day_exclusive).
    NOTE: GitHub GraphQL contributionsCollection(from,to) must be <= 1 year range,
    so callers should chunk requests.
    """
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

def compute_current_streak(day_counts: dict[date, int], today_local: date) -> tuple[int, date | None]:
    """
    Typical streak behavior:
    - If today has contributions -> streak ends today
    - else if yesterday has contributions -> streak ends yesterday
    - else -> current streak is 0
    """
    if day_counts.get(today_local, 0) > 0:
        end = today_local
    elif day_counts.get(today_local - timedelta(days=1), 0) > 0:
        end = today_local - timedelta(days=1)
    else:
        return 0, None

    cur = 0
    d = end
    while day_counts.get(d, 0) > 0:
        cur += 1
        d -= timedelta(days=1)
    return cur, end

def compute_longest_streak(day_counts: dict[date, int]) -> int:
    longest = 0
    run = 0
    for d in sorted(day_counts.keys()):
        if day_counts[d] > 0:
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    return longest

def sum_last_n_days(day_counts: dict[date, int], end_day: date, n: int) -> int:
    start = end_day - timedelta(days=n - 1)
    total = 0
    d = start
    while d <= end_day:
        total += day_counts.get(d, 0)
        d += timedelta(days=1)
    return total

def render_svg(user: str, total_last_n: int, total_days: int, current: int, longest: int, as_of: date, tz: str) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="720" height="140" viewBox="0 0 720 140" role="img" aria-label="GitHub streak for {user}">
  <rect x="0.5" y="0.5" width="719" height="139" rx="18" ry="18" fill="#0d1117" stroke="#30363d"/>

  <text x="24" y="38" fill="#c9d1d9" font-size="20"
        font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto">
    {user} • Streak (computed from GitHub API)
  </text>

  <text x="24" y="74" fill="#8b949e" font-size="14"
        font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto">Current</text>
  <text x="24" y="98" fill="#58a6ff" font-size="22" font-weight="700"
        font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto">{current} day(s)</text>

  <text x="260" y="74" fill="#8b949e" font-size="14"
        font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto">Longest</text>
  <text x="260" y="98" fill="#58a6ff" font-size="22" font-weight="700"
        font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto">{longest} day(s)</text>

  <text x="496" y="74" fill="#8b949e" font-size="14"
        font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto">Total (last {total_days}d)</text>
  <text x="696" y="98" fill="#58a6ff" font-size="22" font-weight="700" text-anchor="end"
        font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto">{total_last_n}</text>

  <text x="24" y="126" fill="#8b949e" font-size="12"
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

    # First fetch a small recent window to get createdAt quickly and have current days
    recent_from = today_local - timedelta(days=364)
    recent_to_excl = today_local + timedelta(days=1)
    created_at, day_counts = fetch_days(token, args.user, recent_from, recent_to_excl)

    # Decide how far back we want to fetch
    wanted_start = today_local - timedelta(days=args.max_years * 366)
    start_day = max(created_at, wanted_start)
    end_excl = today_local + timedelta(days=1)

    # Fetch additional history in 1-year chunks (inclusive-ish)
    # Each chunk: [chunk_start, chunk_end_exclusive), where span <= 365 days
    cur_start = start_day
    while cur_start < recent_from:
        cur_end = min(cur_start + timedelta(days=365), recent_from)
        _, chunk = fetch_days(token, args.user, cur_start, cur_end)
        day_counts.update(chunk)
        cur_start = cur_end

    # Now compute streaks
    current, streak_end = compute_current_streak(day_counts, today_local)
    # If no current streak, still show "as of today"
    as_of = streak_end if streak_end else today_local

    longest = compute_longest_streak(day_counts)

    # Total contributions over last N days ending at "as_of"
    total_last_n = sum_last_n_days(day_counts, as_of, args.total_days)

    svg = render_svg(args.user, total_last_n, args.total_days, current, longest, as_of, args.tz)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(svg)

if __name__ == "__main__":
    main()
