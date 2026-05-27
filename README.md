# Football Analysis Tools

A collection of football data analysis and visualization projects using open-source data.

---

## Projects

### 📊 [passing_network/](passing_network/)

**Football Passing Network — Bundesliga 2015/16**

Builds match-level and season-level passing networks from StatsBomb free event data.

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

### 🔍 [sofascore_scraper/](sofascore_scraper/)

Web scraper for football match data from Sofascore.

---

## Setup

```bash
conda create -n footballnetwork python=3.10
conda activate footballnetwork
pip install statsbombpy mplsoccer pandas numpy scipy tqdm matplotlib
```
