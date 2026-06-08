# Defensive Heat Zones

**Defensive heat zones from StatsBomb event data — FC Barcelona, La Liga 2015/16.**

This project maps *where* a team does its defensive work. It pulls every defensive
action from a full 38-match season, splits it into **active pressing** vs
**reactive defending**, and renders the spatial density as a KDE "heat zone" on the
pitch — at team level, for a single player, or for a pooled combination of players.

> FC Barcelona, La Liga 2015/16 has the richest free-data coverage (a full 38-match
> season), so it is used as the worked example.

---

## What it does

1. **Scan competitions** — list StatsBomb free male competitions from 2015/16 onward and keep the "full" seasons.
2. **Select the sample** — pull every match of La Liga 2015/16 and keep FC Barcelona's 38 games.
3. **Extract defensive events** — fetch the full event feed per match and keep Barcelona's defensive actions.
4. **Team heat zones** — KDE density of all / active / reactive defensive actions on an `mplsoccer` pitch.
5. **Per-player & combinations** — a roster ranked by defensive-action count, plus heat zones for an individual or a pooled set of players (falls back to a scatter when there are too few actions for a KDE).

## Defensive categories

| Category | Event types |
|---|---|
| **Active pressing** | Pressure, Interception, Duel |
| **Reactive defending** | Block, Clearance, Ball Recovery |
| **All** | All six of the above |

All coordinates use the StatsBomb 120 × 80 pitch, with every team normalised to
attack left → right.

## Files

- `Viz-heatmap-360.ipynb` — full pipeline notebook (setup → competition scan → event extraction → team & player heat zones)

## Dependencies

`statsbombpy`, `mplsoccer`, `pandas`, `numpy`, `scipy`, `seaborn`, `matplotlib`, `tqdm`

```bash
pip install statsbombpy mplsoccer pandas numpy scipy seaborn matplotlib tqdm
```

## Usage

Open the notebook and run the cells top to bottom:

```python
# Team-level heat zone
plot_defensive_heatzone(category="all")        # or "active" / "reactive"

# Ranking + per-player / per-combination heat zones
defensive_roster(category="active", top_n=10)
plot_player_defensive_kde("Sergio Busquets i Burgos")
plot_player_defensive_kde(
    ["Gerard Piqué Bernabéu", "Javier Alejandro Mascherano"],
    category="reactive",
)
```

Data is fetched live from the StatsBomb open data via `statsbombpy`, so no local
data files are required.
