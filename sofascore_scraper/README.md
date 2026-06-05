# Sofascore Scraper

Sofascore Scraper is a Playwright-based football data scraper. It opens a real
Chromium browser, establishes a Sofascore session, and sends API requests from
inside the browser page so requests carry normal cookies, headers, and browser
fingerprints.

The folder contains two entry points:

- `sofascore_scraper.py`: original match/player focused scraper.
- `hierarchical_scraper.py`: six-layer scraper for tournament, season, team,
  position, player, and metric-group workflows.

## Install

```bash
python3 -m pip install pandas playwright
python3 -m playwright install chromium
```

## Six-Layer Scraper

The hierarchical scraper follows this data flow:

```text
tournament type
  -> season
    -> teams
      -> player position filter
        -> individual player profile
          -> selected metric groups
```

Supported tournament types:

- `league`
- `cup`
- `national`

Supported position filters:

- `forward` or `F`
- `midfielder` or `M`
- `defender` or `D`
- `goalkeeper` or `G`

Supported metric groups:

- `attack`
- `defense`
- `passing`
- `goalkeeping`
- `all`

## Hierarchical Usage

Scrape all Premier League players for the latest season:

```bash
python3 hierarchical_scraper.py \
  --tournament-type league \
  --tournament 17 \
  --metrics all \
  --outdir data
```

Scrape only forwards and midfielders, with attacking and passing metrics:

```bash
python3 hierarchical_scraper.py \
  --tournament-type league \
  --tournament 17 \
  --season 76986 \
  --positions forward,midfielder \
  --metrics attack,passing \
  --concurrency 3 \
  --min-delay 1.0 \
  --max-delay 3.0 \
  --outdir data
```

Scrape specific teams only:

```bash
python3 hierarchical_scraper.py \
  --tournament-type league \
  --tournament 17 \
  --season 76986 \
  --teams 44,35 \
  --positions defender,goalkeeper \
  --metrics defense,goalkeeping \
  --outdir data
```

Show the browser window for debugging:

```bash
python3 hierarchical_scraper.py \
  --tournament-type league \
  --tournament 17 \
  --show-browser
```

Output is saved as:

```text
sofascore_hierarchy_<tournament_id>_<season_id>_<timestamp>.json
```

## JSON Output Shape

```json
{
  "source": "sofascore",
  "scraped_at": "2026-06-05T00:00:00+00:00",
  "tournament": {
    "type": "league",
    "id": 17
  },
  "season": {
    "id": 76986,
    "name": "2025/2026"
  },
  "filters": {
    "team_ids": null,
    "positions": ["F", "M"],
    "metric_groups": ["attack", "passing"]
  },
  "teams": [
    {
      "team_id": 44,
      "team_name": "Liverpool",
      "team_slug": "liverpool",
      "players": [
        {
          "player_id": 839956,
          "player_name": "Example Player",
          "position": "F",
          "profile": {},
          "metrics": {
            "attack": {
              "goals": 18,
              "totalShots": 92
            },
            "passing": {
              "accuratePass": 812,
              "keyPass": 49
            }
          },
          "raw_metric_scope": {
            "tournament_id": 17,
            "season_id": 76986,
            "stat_type": "overall"
          }
        }
      ]
    }
  ]
}
```

## Original Scraper Usage

All player stats for a league on a date:

```bash
python3 sofascore_scraper.py \
  --mode daily_league \
  --date 2025-05-15 \
  --league 17 \
  --out csv
```

All player stats for one match:

```bash
python3 sofascore_scraper.py \
  --mode match_detail \
  --match 12695944 \
  --out json
```

One player's stats in one match:

```bash
python3 sofascore_scraper.py \
  --mode player_match \
  --player 839956 \
  --match 12695944 \
  --out csv
```

One player's season-level stats:

```bash
python3 sofascore_scraper.py \
  --mode player_season \
  --player 839956 \
  --league 17 \
  --season 61627 \
  --out both
```

## Concurrency and Anti-Blocking Notes

Use conservative concurrency. The hierarchical scraper uses a pool of browser
pages and a global randomized delay before each API request. Start with:

```bash
--concurrency 2 --min-delay 1.0 --max-delay 3.0
```

Increase only after confirming the run is stable. If Sofascore returns `403` or
`429`, the scraper automatically backs off before retrying.

Recommended practices:

- Keep one browser context per run so cookies and session state remain stable.
- Do not open many browser instances in parallel.
- Run broad jobs by season or team chunks instead of scraping every tournament
  in one process.
- Cache completed JSON outputs and avoid refetching the same
  `player_id + tournament_id + season_id` combination unnecessarily.

## Common Tournament IDs

- Premier League: `17`
- La Liga: `8`
- Bundesliga: `35`
- Serie A: `23`
- Ligue 1: `34`
- Champions League: `7`
- Europa League: `679`
- Chinese Super League: `155`

## License

This project is licensed under the MIT License. See [../LICENSE](../LICENSE) for details.

