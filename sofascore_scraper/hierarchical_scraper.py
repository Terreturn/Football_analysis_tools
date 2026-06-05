"""
Hierarchical Sofascore scraper.

This module adds a six-layer data flow:
  tournament type -> season -> team -> player position -> player -> metrics.

It uses a real Chromium session and sends API requests from browser pages so
Sofascore receives normal browser cookies and request fingerprints.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright


BASE_URL = "https://www.sofascore.com/api/v1"
DEFAULT_TIMEOUT_MS = 30_000
MAX_RETRY = 3


class TournamentType(str, Enum):
    LEAGUE = "league"
    CUP = "cup"
    NATIONAL = "national"


class PlayerPosition(str, Enum):
    FORWARD = "F"
    MIDFIELDER = "M"
    DEFENDER = "D"
    GOALKEEPER = "G"


MetricGroup = Literal["attack", "defense", "passing", "goalkeeping", "all"]


POSITION_ALIASES = {
    "forward": PlayerPosition.FORWARD,
    "f": PlayerPosition.FORWARD,
    "attacker": PlayerPosition.FORWARD,
    "midfielder": PlayerPosition.MIDFIELDER,
    "midfield": PlayerPosition.MIDFIELDER,
    "m": PlayerPosition.MIDFIELDER,
    "defender": PlayerPosition.DEFENDER,
    "defense": PlayerPosition.DEFENDER,
    "d": PlayerPosition.DEFENDER,
    "goalkeeper": PlayerPosition.GOALKEEPER,
    "keeper": PlayerPosition.GOALKEEPER,
    "gk": PlayerPosition.GOALKEEPER,
    "g": PlayerPosition.GOALKEEPER,
}


METRIC_FIELDS: dict[str, list[str]] = {
    "attack": [
        "goals",
        "goalAssist",
        "assists",
        "totalShots",
        "shotsOnTarget",
        "onTargetScoringAttempt",
        "bigChancesCreated",
        "bigChanceMissed",
        "successfulDribble",
        "touchesInOppBox",
        "penaltyWon",
    ],
    "defense": [
        "tackles",
        "interceptionWon",
        "interceptions",
        "clearance",
        "clearances",
        "blockedScoringAttempt",
        "duelWon",
        "duelLost",
        "aerialWon",
        "aerialLost",
        "wasFouled",
        "fouls",
        "yellowCard",
        "redCard",
    ],
    "passing": [
        "accuratePass",
        "totalPass",
        "accurateFinalThirdPasses",
        "keyPass",
        "bigChanceCreated",
        "accurateCross",
        "totalCross",
        "accurateLongBalls",
        "totalLongBalls",
    ],
    "goalkeeping": [
        "saves",
        "savedShotsFromInsideTheBox",
        "savesCaught",
        "savesParried",
        "cleanSheet",
        "goalsPrevented",
        "penaltySave",
        "punches",
        "highClaims",
        "runsOut",
    ],
}


@dataclass
class ScrapeConfig:
    tournament_type: TournamentType
    tournament_id: int
    season_id: int | None = None
    season_name: str | None = None
    team_ids: list[int] = field(default_factory=list)
    positions: list[PlayerPosition] = field(default_factory=list)
    metric_groups: list[MetricGroup] = field(default_factory=lambda: ["all"])
    max_concurrency: int = 3
    min_delay: float = 0.8
    max_delay: float = 2.5
    headless: bool = True
    out_dir: str = "."


class BrowserApiClient:
    """Rate-limited Sofascore API client backed by a pool of browser pages."""

    def __init__(self, context: BrowserContext, config: ScrapeConfig) -> None:
        self.context = context
        self.config = config
        self._pages: asyncio.Queue[Page] = asyncio.Queue()
        self._delay_lock = asyncio.Lock()
        self._last_request_at = 0.0

    async def start(self) -> None:
        for _ in range(max(1, self.config.max_concurrency)):
            page = await self.context.new_page()
            await page.goto("https://www.sofascore.com/", wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
            await self._pages.put(page)

    async def close(self) -> None:
        while not self._pages.empty():
            page = await self._pages.get()
            await page.close()

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = self._build_url(path, params)

        for attempt in range(1, MAX_RETRY + 1):
            page = await self._pages.get()
            try:
                await self._pace_requests()
                result = await self._fetch_from_page(page, url)
            finally:
                await self._pages.put(page)

            status = result.get("__status")
            if status in (403, 429):
                wait = min(90, 10 * attempt + random.uniform(0, 5))
                print(f"  [Rate limited HTTP {status}] Waiting {wait:.1f}s ...")
                await asyncio.sleep(wait)
                continue
            if status == 404:
                print(f"  [404] Not found: {url}")
                return {}
            if status:
                wait = 3 * attempt
                print(f"  [HTTP {status}] Retrying in {wait}s: {url}")
                await asyncio.sleep(wait)
                continue
            if "__error" in result:
                print(f"  [JS error] {result['__error']} - retrying {attempt}/{MAX_RETRY}")
                await asyncio.sleep(3 * attempt)
                continue

            return result

        print(f"  [Failed] Max retries exceeded: {url}")
        return {}

    def _build_url(self, path: str, params: dict[str, Any] | None) -> str:
        url = f"{BASE_URL}{path}"
        if params:
            query = "&".join(f"{key}={value}" for key, value in params.items())
            url = f"{url}?{query}"
        return url

    async def _pace_requests(self) -> None:
        async with self._delay_lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            elapsed = now - self._last_request_at
            wait = random.uniform(self.config.min_delay, self.config.max_delay)
            if elapsed < wait:
                await asyncio.sleep(wait - elapsed)
            self._last_request_at = loop.time()

    async def _fetch_from_page(self, page: Page, url: str) -> dict[str, Any]:
        return await page.evaluate(
            """
            async (url) => {
                try {
                    const resp = await fetch(url, {
                        credentials: 'include',
                        headers: {
                            'Accept': 'application/json, text/plain, */*',
                            'Accept-Language': 'en-US,en;q=0.9',
                            'Referer': 'https://www.sofascore.com/',
                        }
                    });
                    if (!resp.ok) return { __status: resp.status, __url: url };
                    return await resp.json();
                } catch (e) {
                    return { __error: e.message, __url: url };
                }
            }
            """,
            url,
        )


class HierarchicalScraper:
    def __init__(self, client: BrowserApiClient, config: ScrapeConfig) -> None:
        self.client = client
        self.config = config

    async def run(self) -> dict[str, Any]:
        season = await self.resolve_season()
        season_id = season["id"]
        teams = await self.fetch_teams(season_id)

        result = {
            "source": "sofascore",
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "tournament": {
                "type": self.config.tournament_type.value,
                "id": self.config.tournament_id,
            },
            "season": season,
            "filters": {
                "team_ids": self.config.team_ids or None,
                "positions": [position.value for position in self.config.positions] or None,
                "metric_groups": self.config.metric_groups,
            },
            "teams": [],
        }

        for index, team in enumerate(teams, 1):
            print(f"[{index}/{len(teams)}] Fetching roster: {team.get('name')} ({team.get('id')})")
            roster = await self.fetch_team_players(team["id"])
            selected_players = self.filter_players_by_position(roster)
            player_records = await self.fetch_players(selected_players, season_id)

            result["teams"].append(
                {
                    "team_id": team.get("id"),
                    "team_name": team.get("name"),
                    "team_slug": team.get("slug"),
                    "players": player_records,
                }
            )

        return result

    async def resolve_season(self) -> dict[str, Any]:
        if self.config.season_id:
            return {
                "id": self.config.season_id,
                "name": self.config.season_name,
            }

        print("[1/N] Resolving latest season ...")
        data = await self.client.get(f"/unique-tournament/{self.config.tournament_id}/seasons")
        seasons = data.get("seasons", [])
        if not seasons:
            raise RuntimeError("No seasons found. Pass --season explicitly.")

        latest = seasons[0]
        print(f"      Latest season: {latest.get('name')} (ID={latest.get('id')})")
        return latest

    async def fetch_teams(self, season_id: int) -> list[dict[str, Any]]:
        print(f"[2/N] Fetching teams for season {season_id} ...")
        teams = await self.fetch_teams_from_standings(season_id)
        if not teams:
            teams = await self.fetch_teams_from_events(season_id)

        if self.config.team_ids:
            wanted = set(self.config.team_ids)
            teams = [team for team in teams if team.get("id") in wanted]

        print(f"      Found {len(teams)} team(s)")
        return teams

    async def fetch_teams_from_standings(self, season_id: int) -> list[dict[str, Any]]:
        data = await self.client.get(
            f"/unique-tournament/{self.config.tournament_id}/season/{season_id}/standings/total"
        )
        teams_by_id: dict[int, dict[str, Any]] = {}
        for standing in data.get("standings", []):
            for row in standing.get("rows", []):
                team = row.get("team")
                if team and team.get("id"):
                    teams_by_id[team["id"]] = team
        return list(teams_by_id.values())

    async def fetch_teams_from_events(self, season_id: int) -> list[dict[str, Any]]:
        data = await self.client.get(
            f"/unique-tournament/{self.config.tournament_id}/season/{season_id}/events"
        )
        teams_by_id: dict[int, dict[str, Any]] = {}
        for event in data.get("events", []):
            for key in ("homeTeam", "awayTeam"):
                team = event.get(key)
                if team and team.get("id"):
                    teams_by_id[team["id"]] = team
        return list(teams_by_id.values())

    async def fetch_team_players(self, team_id: int) -> list[dict[str, Any]]:
        data = await self.client.get(f"/team/{team_id}/players")
        return data.get("players", [])

    def filter_players_by_position(self, roster: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not self.config.positions:
            return roster

        allowed = {position.value for position in self.config.positions}
        selected = []
        for item in roster:
            player = item.get("player", item)
            position = item.get("position") or player.get("position")
            if position in allowed:
                selected.append(item)
        return selected

    async def fetch_players(self, roster: list[dict[str, Any]], season_id: int) -> list[dict[str, Any]]:
        tasks = [self.build_player_record(item, season_id) for item in roster]
        if not tasks:
            return []
        return await asyncio.gather(*tasks)

    async def build_player_record(self, roster_item: dict[str, Any], season_id: int) -> dict[str, Any]:
        player = roster_item.get("player", roster_item)
        player_id = player["id"]

        profile_task = self.client.get(f"/player/{player_id}")
        metrics_task = self.client.get(
            f"/player/{player_id}/unique-tournament/{self.config.tournament_id}"
            f"/season/{season_id}/statistics/overall"
        )
        profile_raw, metrics_raw = await asyncio.gather(profile_task, metrics_task)

        return {
            "player_id": player_id,
            "player_name": player.get("name"),
            "position": roster_item.get("position") or player.get("position"),
            "profile": profile_raw.get("player", profile_raw),
            "metrics": self.select_metric_groups(metrics_raw.get("statistics", {})),
            "raw_metric_scope": {
                "tournament_id": self.config.tournament_id,
                "season_id": season_id,
                "stat_type": "overall",
            },
        }

    def select_metric_groups(self, stats: dict[str, Any]) -> dict[str, Any]:
        groups = self.config.metric_groups
        if "all" in groups:
            return stats

        selected: dict[str, dict[str, Any]] = {}
        for group in groups:
            selected[group] = {
                field: stats[field]
                for field in METRIC_FIELDS.get(group, [])
                if field in stats
            }
        return selected


def parse_positions(raw: str | None) -> list[PlayerPosition]:
    if not raw:
        return []
    positions = []
    for item in raw.split(","):
        key = item.strip().lower()
        if key not in POSITION_ALIASES:
            valid = ", ".join(sorted(POSITION_ALIASES))
            raise argparse.ArgumentTypeError(f"Unknown position '{item}'. Valid values: {valid}")
        positions.append(POSITION_ALIASES[key])
    return positions


def parse_metric_groups(raw: str | None) -> list[MetricGroup]:
    if not raw:
        return ["all"]
    groups = [item.strip().lower() for item in raw.split(",") if item.strip()]
    valid = {"attack", "defense", "passing", "goalkeeping", "all"}
    invalid = [group for group in groups if group not in valid]
    if invalid:
        raise argparse.ArgumentTypeError(f"Unknown metric group(s): {', '.join(invalid)}")
    if "all" in groups and len(groups) > 1:
        return ["all"]
    return groups  # type: ignore[return-value]


def parse_team_ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    return [int(item.strip()) for item in raw.split(",") if item.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Six-layer Sofascore scraper: tournament -> season -> team -> position -> player -> metrics"
    )
    parser.add_argument("--tournament-type", required=True, choices=[item.value for item in TournamentType])
    parser.add_argument("--tournament", required=True, type=int, help="Sofascore unique tournament ID")
    parser.add_argument("--season", type=int, default=None, help="Sofascore season ID. Latest season is used if omitted.")
    parser.add_argument("--season-name", default=None, help="Optional season label for output metadata")
    parser.add_argument("--teams", default=None, help="Comma-separated team IDs. Omit to scrape all teams.")
    parser.add_argument(
        "--positions",
        default=None,
        help="Comma-separated positions: forward, midfielder, defender, goalkeeper, F, M, D, G",
    )
    parser.add_argument(
        "--metrics",
        default="all",
        help="Comma-separated metric groups: attack, defense, passing, goalkeeping, all",
    )
    parser.add_argument("--concurrency", type=int, default=3, help="Max browser pages used for API requests")
    parser.add_argument("--min-delay", type=float, default=0.8, help="Minimum delay between API calls")
    parser.add_argument("--max-delay", type=float, default=2.5, help="Maximum delay between API calls")
    parser.add_argument("--outdir", default=".", help="Output directory")
    parser.add_argument("--show-browser", action="store_true", help="Show Chromium window")
    return parser


async def create_browser(headless: bool) -> tuple[Playwright, Browser, BrowserContext]:
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=headless)
    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        locale="en-US",
        timezone_id="America/New_York",
        viewport={"width": 1280, "height": 800},
    )
    return playwright, browser, context


async def run_from_config(config: ScrapeConfig) -> dict[str, Any]:
    playwright, browser, context = await create_browser(config.headless)
    client = BrowserApiClient(context, config)
    try:
        bootstrap = await context.new_page()
        print("[Browser] Opening sofascore.com to establish session ...")
        await bootstrap.goto("https://www.sofascore.com/", wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
        await asyncio.sleep(2)
        await bootstrap.close()

        await client.start()
        scraper = HierarchicalScraper(client, config)
        return await scraper.run()
    finally:
        await client.close()
        await browser.close()
        await playwright.stop()


def save_json(data: dict[str, Any], out_dir: str) -> Path:
    path = Path(out_dir)
    path.mkdir(parents=True, exist_ok=True)
    tournament_id = data["tournament"]["id"]
    season_id = data["season"]["id"]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = path / f"sofascore_hierarchy_{tournament_id}_{season_id}_{ts}.json"
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main() -> None:
    args = build_parser().parse_args()
    config = ScrapeConfig(
        tournament_type=TournamentType(args.tournament_type),
        tournament_id=args.tournament,
        season_id=args.season,
        season_name=args.season_name,
        team_ids=parse_team_ids(args.teams),
        positions=parse_positions(args.positions),
        metric_groups=parse_metric_groups(args.metrics),
        max_concurrency=args.concurrency,
        min_delay=args.min_delay,
        max_delay=args.max_delay,
        headless=not args.show_browser,
        out_dir=args.outdir,
    )

    print("\n" + "=" * 72)
    print("  Sofascore Hierarchical Scraper")
    print("=" * 72)
    print(json.dumps(asdict(config), ensure_ascii=False, default=str, indent=2))
    print()

    data = asyncio.run(run_from_config(config))
    out_path = save_json(data, config.out_dir)
    print(f"\nSaved: {out_path}")
    print("Done.\n")


if __name__ == "__main__":
    main()
