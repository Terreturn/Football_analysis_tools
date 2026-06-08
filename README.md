# Football Analysis Tools

A collection of football data analysis and visualization projects using open-source data.

---

## Projects

### 📊 [passing_network/](passing_network/)

**Football Passing Network — Bundesliga 2015/16**

Builds match-level and season-level passing networks from StatsBomb free event data.

> Approach and methodology based on the work of **Victoria Friss de Kereki** — Sports Analytics & Data Science.

**Pipeline:**
1. Fetch pass events via `statsbombpy`
2. Clean coordinates and filter starters
3. Compute average player positions → network nodes
4. Aggregate pass counts between players → network edges
5. Align nodes across matches using the Hungarian algorithm
6. Visualize with `mplsoccer`

**Files:**
- `Network_sample.ipynb` — full pipeline notebook
- `passes_bundesliga_201516_statsbomb_all.csv` — pre-extracted pass data (34 matches)
- `skill_notes.md` — methodology and design notes

**Dependencies:** `statsbombpy`, `mplsoccer`, `pandas`, `numpy`, `scipy`, `tqdm`, `matplotlib`

---

### 🔥 [defensive-heat-zones/](defensive-heat-zones/)

**Defensive Heat Zones — FC Barcelona, La Liga 2015/16**

Maps *where* a team defends, using StatsBomb free event data over a full 38-match season.

**Pipeline:**
1. Scan free male competitions (2015/16+) and keep the full seasons
2. Select FC Barcelona's 38 La Liga 2015/16 matches
3. Fetch the event feed and keep Barcelona's defensive actions via `statsbombpy`
4. Split into **active pressing** (Pressure + Interception + Duel) vs **reactive defending** (Block + Clearance + Ball Recovery)
5. Render KDE heat zones with `mplsoccer` — team-level, per-player, or pooled combinations

**Files:**
- `Viz-heatmap-360.ipynb` — full pipeline notebook
- `README.md` — project overview and usage

**Dependencies:** `statsbombpy`, `mplsoccer`, `pandas`, `numpy`, `scipy`, `seaborn`, `tqdm`, `matplotlib`

---

### 🔍 [sofascore_scraper/](sofascore_scraper/)

Web scraper for football match data from Sofascore.

---

## Setup

```bash
conda create -n footballnetwork python=3.10
conda activate footballnetwork
pip install statsbombpy mplsoccer pandas numpy scipy tqdm matplotlib
```

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
