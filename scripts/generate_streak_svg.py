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
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        totalContributions
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

def compute_streak(day_counts: dict[date, int], end_day: date) -> tuple[int, int]:
    # Current streak ending at end_day (inclusive)
    cur = 0
    d = end_day
    while day_counts.get(d, 0) > 0:
        cur += 1
        d -= timedelta(days=1)

    # Longest streak in the dataset
    longest = 0
    run = 0
    for d in sorted(day_counts.keys()):
        if day_counts[d] > 0:
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    return cur, longest

def render_svg(user: str, total: int, current: int, longest: int, as_of: date, tz: str) -> str:
    # Dark card, GitHub-safe SVG (no external assets)
    # Dimensions match your README usage (width=720 looks clean)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="720" height="140" viewBox="0 0 720 140" role="img" aria-label="GitHub streak for {user}">
  <rect x="0.5" y="0.5" width="719" height="139" rx="18" ry="18" fill="#0d1117" stroke="#30363d"/>

  <text x="24" y="38" fill="#c9d1d9" font-size="20"
        font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto">
    {user} • Streak (computed from GitHub API)
  </text>

  <text x="24" y="74" fill="#8b949e" font-size="14"
        font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto">
    Current
  </text>
  <text x="24" y="98" fill="#58a6ff" font-size="22" font-weight="700"
        font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto">
    {current} day(s)
  </text>

  <text x="260" y="74" fill="#8b949e" font-size="14"
        font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto">
    Longest
  </text>
  <text x="260" y="98" fill="#58a6ff" font-size="22" font-weight="700"
        font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto">
    {longest} day(s)
  </text>

  <text x="496" y="74" fill="#8b949e" font-size="14"
        font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto">
    Total (range)
  </text>
  <text x="696" y="98" fill="#58a6ff" font-size="22" font-weight="700" text-anchor="end"
        font-family="ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto">
    {total}
  </text>

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
    ap.add_argument("--days", type=int, default=370)
    args = ap.parse_args()

    token = os.getenv("GH_TOKEN")
    if not token:
        raise SystemExit("GH_TOKEN is required. Use secrets.GITHUB_TOKEN or create a secret GH_STATS_TOKEN.")

    tzinfo = ZoneInfo(args.tz)
    today_local = datetime.now(tzinfo).date()

    # Query slightly beyond today to reduce edge/caching issues
    from_day = today_local - timedelta(days=args.days)
    to_day = today_local + timedelta(days=1)

    from_iso = f"{from_day.isoformat()}T00:00:00Z"
    to_iso = f"{to_day.isoformat()}T00:00:00Z"

    data = gql(token, args.user, from_iso, to_iso)
    if "errors" in data:
        raise SystemExit("GraphQL error: " + json.dumps(data["errors"], indent=2))

    cal = data["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    total = int(cal["totalContributions"])

    day_counts: dict[date, int] = {}
    for w in cal["weeks"]:
        for d in w["contributionDays"]:
            day_counts[date.fromisoformat(d["date"])] = int(d["contributionCount"])

    if not day_counts:
        raise SystemExit("No contribution data returned. Check token permissions / username.")

    end_day = min(today_local, max(day_counts.keys()))
    current, longest = compute_streak(day_counts, end_day)

    svg = render_svg(args.user, total, current, longest, end_day, args.tz)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(svg)

if __name__ == "__main__":
    main()
