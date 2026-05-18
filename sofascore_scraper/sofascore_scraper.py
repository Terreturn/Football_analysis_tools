"""
sofascore_scraper.py  (Playwright edition)
Scrape Sofascore football data using a real Chromium browser to bypass bot detection.

Strategy: launch Chromium, navigate to sofascore.com to establish a valid session,
then issue all API calls via browser-side fetch() — which carries real cookies and
a genuine TLS fingerprint that passes Cloudflare / anti-bot checks.

Supported modes:
  1. daily_league  — all player stats for a given date and league
  2. player_match  — one player's stats in a specific match
  3. player_season — one player's season-level statistics
  4. match_detail  — all players' stats for a single match

Usage examples (CLI):
  python sofascore_scraper.py --mode daily_league --date 2025-05-15 --league 17 --out csv
  python sofascore_scraper.py --mode player_match  --player 839956 --match 12695944 --out json
  python sofascore_scraper.py --mode player_season --player 839956 --league 17 --season 61627 --out csv
  python sofascore_scraper.py --mode match_detail  --match 12695944 --out csv
  python sofascore_scraper.py --mode match_detail  --match 12695944 --out csv --show-browser
"""

import argparse
import time
import sys
from pathlib import Path
from datetime import datetime

import pandas as pd
from playwright.sync_api import sync_playwright, Page


# ── Common league IDs (Sofascore internal IDs) ───────────────────────────────
LEAGUE_IDS = {
    "premier_league":   17,
    "la_liga":          8,
    "bundesliga":       35,
    "serie_a":          23,
    "ligue_1":          34,
    "champions_league": 7,
    "europa_league":    679,
    "fa_cup":           19,
    "chinese_super":    155,
}

# ── Request configuration ────────────────────────────────────────────────────
BASE_URL  = "https://www.sofascore.com/api/v1"
DELAY     = 1.2   # seconds to wait between API calls
MAX_RETRY = 3

# ── Module-level browser state ───────────────────────────────────────────────
_pw      = None
_browser = None
_page: Page | None = None


# ── Browser lifecycle ─────────────────────────────────────────────────────────
def init_browser(headless: bool = True) -> None:
    """Launch Chromium and navigate to sofascore.com to establish a valid session."""
    global _pw, _browser, _page

    print("  [Browser] Launching Chromium ...")
    _pw      = sync_playwright().start()
    _browser = _pw.chromium.launch(headless=headless)

    context = _browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        locale="en-US",
        timezone_id="America/New_York",
        viewport={"width": 1280, "height": 800},
    )
    _page = context.new_page()

    print("  [Browser] Navigating to sofascore.com to establish session ...")
    _page.goto("https://www.sofascore.com/", wait_until="domcontentloaded", timeout=30_000)
    time.sleep(2)
    print("  [Browser] Session ready.\n")


def close_browser() -> None:
    global _pw, _browser
    if _browser:
        _browser.close()
    if _pw:
        _pw.stop()


# ── Core fetch (runs inside the real browser) ─────────────────────────────────
def _get(path: str, params: dict | None = None) -> dict:
    """
    Call a Sofascore API endpoint from within the Chromium page context.
    Because the request originates from a real browser, cookies, TLS fingerprint,
    and all bot-detection signals are authentic.
    """
    url = f"{BASE_URL}{path}"
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())

    for attempt in range(1, MAX_RETRY + 1):
        try:
            result = _page.evaluate(
                """
                async (url) => {
                    try {
                        const resp = await fetch(url, {
                            credentials: 'include',
                            headers: {
                                'Accept':          'application/json, text/plain, */*',
                                'Accept-Language': 'en-US,en;q=0.9',
                                'Referer':         'https://www.sofascore.com/',
                            }
                        });
                        if (!resp.ok) return { __status: resp.status };
                        return await resp.json();
                    } catch (e) {
                        return { __error: e.message };
                    }
                }
                """,
                url,
            )

            if not result:
                time.sleep(3)
                continue

            status = result.get("__status")
            if status == 429:
                wait = 10 * attempt
                print(f"  [Rate limited] Waiting {wait}s ...")
                time.sleep(wait)
                continue
            if status == 404:
                print(f"  [404] Not found: {url}")
                return {}
            if status:
                print(f"  [Warning] HTTP {status}, retrying {attempt}/{MAX_RETRY}")
                time.sleep(3 * attempt)
                continue
            if "__error" in result:
                print(f"  [JS error] {result['__error']}, retrying {attempt}/{MAX_RETRY}")
                time.sleep(3)
                continue

            time.sleep(DELAY)
            return result

        except Exception as e:
            print(f"  [Error] {e}, retrying {attempt}/{MAX_RETRY}")
            time.sleep(5)

    print(f"  [Failed] Max retries exceeded: {url}")
    return {}


# ── Data fetching ─────────────────────────────────────────────────────────────
def get_matches_by_date_league(date: str, league_id: int) -> list[dict]:
    """Fetch all matches for a given date and league. date format: YYYY-MM-DD"""
    print(f"[1/N] Fetching matches for {date}, league {league_id} ...")
    data   = _get(f"/sport/football/scheduled-events/{date}")
    events = data.get("events", [])
    matched = [
        e for e in events
        if e.get("tournament", {}).get("uniqueTournament", {}).get("id") == league_id
    ]
    print(f"      Found {len(matched)} match(es)")
    return matched


def get_match_lineups(match_id: int) -> dict:
    """Fetch lineups and player ratings for both teams in a match."""
    return _get(f"/event/{match_id}/lineups")


def get_match_statistics(match_id: int) -> dict:
    """Fetch full-match statistics for a given match."""
    return _get(f"/event/{match_id}/statistics")


def get_player_statistics(player_id: int, match_id: int) -> dict:
    """Fetch detailed statistics for a player in a specific match."""
    return _get(f"/event/{match_id}/player/{player_id}/statistics")


def get_player_season_stats(player_id: int, tournament_id: int, season_id: int) -> dict:
    """Fetch a player's season-level statistics."""
    return _get(
        f"/player/{player_id}/tournament/{tournament_id}"
        f"/season/{season_id}/statistics/overall"
    )


def get_season_id(tournament_id: int) -> int | None:
    """Automatically retrieve the latest season ID for a league."""
    data    = _get(f"/unique-tournament/{tournament_id}/seasons")
    seasons = data.get("seasons", [])
    if seasons:
        latest = seasons[0]
        print(f"      Latest season: {latest.get('name')} (ID={latest.get('id')})")
        return latest.get("id")
    return None


# ── Parsing layer ─────────────────────────────────────────────────────────────
def _parse_lineup_players(lineup_data: dict, match_id: int) -> list[dict]:
    """
    Extract all player records from lineup data, flattened to a list of dicts.
    Includes: team, name, position, rating, minutes played, goals, assists, etc.
    """
    rows = []
    for side in ("home", "away"):
        team_data = lineup_data.get(side, {})
        team_name = team_data.get("team", {}).get("name", side)
        for group, group_label in [("players", "starter"), ("supportStaff", None)]:
            if group_label is None:
                continue
            for p in team_data.get(group, []):
                player   = p.get("player", {})
                stats    = p.get("statistics", {})
                row = {
                    "match_id":        match_id,
                    "team":            team_name,
                    "group":           group_label,
                    "player_id":       player.get("id"),
                    "player_name":     player.get("name"),
                    "position":        p.get("position", ""),
                    "shirt_number":    p.get("shirtNumber"),
                    "rating":          stats.get("rating"),
                    "minutes_played":  stats.get("minutesPlayed"),
                    "goals":           stats.get("goals"),
                    "assists":         stats.get("goalAssist"),
                    "shots_total":     stats.get("totalShots"),
                    "shots_on_target": stats.get("onTargetScoringAttempt"),
                    "key_passes":      stats.get("keyPass"),
                    "pass_accuracy":   stats.get("accuratePass"),
                    "dribbles":        stats.get("successfulDribble"),
                    "tackles":         stats.get("tackles"),
                    "interceptions":   stats.get("interceptionWon"),
                    "yellow_cards":    stats.get("yellowCard"),
                    "red_cards":       stats.get("redCard"),
                    "saves":           stats.get("savedShotsFromInsideTheBox"),
                }
                rows.append(row)
    return rows


def _parse_player_stats(raw: dict, player_id: int, match_id: int | None = None) -> dict:
    """Flatten a single-match or season player statistics dict into one row."""
    stats = raw.get("statistics", {})
    stats["player_id"] = player_id
    if match_id:
        stats["match_id"] = match_id
    return stats


# ── Four scraping modes ───────────────────────────────────────────────────────
def mode_daily_league(date: str, league_id: int) -> pd.DataFrame:
    """Mode 1: date x league -> all player stats across all matches."""
    matches = get_matches_by_date_league(date, league_id)
    if not matches:
        print("  No matches found. Check the date and league ID.")
        return pd.DataFrame()

    all_rows = []
    for i, match in enumerate(matches, 1):
        mid  = match["id"]
        home = match.get("homeTeam", {}).get("name", "?")
        away = match.get("awayTeam", {}).get("name", "?")
        print(f"  [{i}/{len(matches)}] {home} vs {away} (ID={mid})")
        lineup = get_match_lineups(mid)
        rows   = _parse_lineup_players(lineup, mid)
        for r in rows:
            r["match_home"] = home
            r["match_away"] = away
            r["match_date"] = date
        all_rows.extend(rows)

    df = pd.DataFrame(all_rows)
    print(f"\n✓ Retrieved {len(df)} player records across {len(matches)} match(es)")
    return df


def mode_match_detail(match_id: int) -> pd.DataFrame:
    """Mode 2: single match -> all player stats for both teams."""
    print(f"[1/1] Fetching lineup for match {match_id} ...")
    lineup = get_match_lineups(match_id)
    rows   = _parse_lineup_players(lineup, match_id)
    df     = pd.DataFrame(rows)
    print(f"✓ Retrieved {len(df)} player records")
    return df


def mode_player_match(player_id: int, match_id: int) -> pd.DataFrame:
    """Mode 3: one player x one match -> detailed stats."""
    print(f"[1/1] Fetching stats for player {player_id} in match {match_id} ...")
    raw = get_player_statistics(player_id, match_id)
    row = _parse_player_stats(raw, player_id, match_id)
    df  = pd.DataFrame([row])
    print(f"✓ Success — {len(df.columns)} fields retrieved")
    return df


def mode_player_season(player_id: int, tournament_id: int, season_id: int | None) -> pd.DataFrame:
    """Mode 4: one player x one season -> season-level statistics."""
    if season_id is None:
        print(f"[1/2] Looking up latest season for league {tournament_id} ...")
        season_id = get_season_id(tournament_id)
        if not season_id:
            print("  Could not retrieve season ID. Please specify --season manually.")
            return pd.DataFrame()

    print(f"[2/2] Fetching season {season_id} stats for player {player_id} ...")
    raw = get_player_season_stats(player_id, tournament_id, season_id)
    row = _parse_player_stats(raw, player_id)
    row["tournament_id"] = tournament_id
    row["season_id"]     = season_id
    df  = pd.DataFrame([row])
    print(f"✓ Success — {len(df.columns)} fields retrieved")
    return df


# ── Output ────────────────────────────────────────────────────────────────────
def save_output(df: pd.DataFrame, mode: str, fmt: str, out_dir: str = ".") -> None:
    if df.empty:
        print("  [Skipped] DataFrame is empty, no file saved.")
        return
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"sofascore_{mode}_{ts}"
    path     = Path(out_dir) / filename

    if fmt == "csv":
        out_path = path.with_suffix(".csv")
        df.to_csv(out_path, index=False, encoding="utf-8-sig")
    elif fmt == "json":
        out_path = path.with_suffix(".json")
        df.to_json(out_path, orient="records", force_ascii=False, indent=2)
    elif fmt == "both":
        df.to_csv(path.with_suffix(".csv"), index=False, encoding="utf-8-sig")
        df.to_json(path.with_suffix(".json"), orient="records", force_ascii=False, indent=2)
        out_path = path

    print(f"  -> Saved: {out_path}")


# ── CLI ───────────────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Sofascore football data scraper (Playwright edition)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Mode examples:

  # Mode 1: all player stats for Premier League on 2025-05-15
  python sofascore_scraper.py --mode daily_league --date 2025-05-15 --league 17 --out csv

  # Mode 2: all player stats for a single match
  python sofascore_scraper.py --mode match_detail --match 12695944 --out json

  # Mode 3: one player's stats in a single match
  python sofascore_scraper.py --mode player_match --player 839956 --match 12695944 --out csv

  # Mode 4: one player's season stats (auto-fetch latest season)
  python sofascore_scraper.py --mode player_season --player 839956 --league 17 --out both

  # Add --show-browser to watch the browser window (useful for debugging)
  python sofascore_scraper.py --mode match_detail --match 12695944 --show-browser

Common league IDs:
  Premier League=17  La Liga=8  Bundesliga=35  Serie A=23  Ligue 1=34
  Champions League=7  Europa League=679  FA Cup=3  Chinese Super League=155
        """
    )
    p.add_argument("--mode",   required=True,
                   choices=["daily_league", "match_detail", "player_match", "player_season"],
                   help="Scraping mode")
    p.add_argument("--date",   help="Date in YYYY-MM-DD format (required for daily_league)")
    p.add_argument("--league", type=int, help="League ID (required for daily_league / player_season)")
    p.add_argument("--match",  type=int, help="Match ID (required for match_detail / player_match)")
    p.add_argument("--player", type=int, help="Player ID (required for player_match / player_season)")
    p.add_argument("--season", type=int, default=None,
                   help="Season ID (optional for player_season; auto-fetched if omitted)")
    p.add_argument("--out",    default="csv", choices=["csv", "json", "both"],
                   help="Output format (default: csv)")
    p.add_argument("--outdir", default=".", help="Output directory (default: current directory)")
    p.add_argument("--show-browser", action="store_true",
                   help="Show the browser window instead of running headless")
    return p


def main():
    parser = build_parser()
    args   = parser.parse_args()

    print(f"\n{'='*55}")
    print(f"  Sofascore Scraper (Playwright)  |  Mode: {args.mode}")
    print(f"{'='*55}\n")

    try:
        init_browser(headless=not args.show_browser)

        df = pd.DataFrame()

        if args.mode == "daily_league":
            if not args.date or not args.league:
                parser.error("--mode daily_league requires --date and --league")
            df = mode_daily_league(args.date, args.league)

        elif args.mode == "match_detail":
            if not args.match:
                parser.error("--mode match_detail requires --match")
            df = mode_match_detail(args.match)

        elif args.mode == "player_match":
            if not args.player or not args.match:
                parser.error("--mode player_match requires --player and --match")
            df = mode_player_match(args.player, args.match)

        elif args.mode == "player_season":
            if not args.player or not args.league:
                parser.error("--mode player_season requires --player and --league")
            df = mode_player_season(args.player, args.league, args.season)

        if not df.empty:
            print(f"\n  Preview (first 3 rows):\n{df.head(3).to_string()}\n")
            save_output(df, args.mode, args.out, args.outdir)

    finally:
        close_browser()

    print("\nDone.\n")


if __name__ == "__main__":
    main()
