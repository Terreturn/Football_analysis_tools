# Football Passing Network — Methodology & Skill Notes

Source notebook: `Network_sample.ipynb` (Bundesliga 2015/16, StatsBomb free data)  
Approach credit: **Victoria Friss de Kereki** — Sports Analytics & Data Science

---

## Core Dependencies

| Package | Purpose |
|---|---|
| `statsbombpy` | Free football event data API |
| `mplsoccer` | Pitch coordinate system and visualization |
| `scipy.optimize.linear_sum_assignment` | Hungarian algorithm for node alignment |
| `pandas / numpy / matplotlib` | Data processing and plotting |
| `tqdm` | Progress bar for batch extraction |

Constants: `PITCH_X_MAX=120, PITCH_Y_MAX=80, MIN_STARTERS=11`

---

## Phase 1: Competition Selection

**Rationale**: StatsBomb free data does not cover every match — first identify competitions with enough samples.

```python
free_comps = sb.competitions()
comps = free_comps[free_comps["competition_gender"] == "male"]
# Keep only seasons starting 2015 or later
comps["season_start"] = comps["season_name"].str.split("/").str[0].astype(int)

# Count matches per competition; keep those above threshold (FULL_MATCH_THRESHOLD=100)
for comp_id, season_id in zip(...):
    matches = sb.matches(competition_id=comp_id, season_id=season_id)
    match_counts.append({"matches_count": len(matches), ...})
full_comps = match_counts_df[match_counts_df["matches_count"] >= 100]
```

> **Note**: StatsBomb free Bundesliga data (competition_id=9) contains only 34 matches, all involving Bayer Leverkusen — not a complete season.

---

## Phase 2: Pass Extraction

**Rationale**: Filter pass events from the event stream, extract per match, merge match metadata, and save to CSV.

```python
all_passes = []
for match_id in tqdm(matches_df["match_id"]):
    events = sb.events(match_id=match_id)
    passes = events[events["type"] == "Pass"].copy()
    passes["match_id"] = match_id
    all_passes.append(passes)

passes_df = pd.concat(all_passes, ignore_index=True)

# Merge match metadata (teams, score, date)
matches_meta = matches_df[["match_id","match_date","season","competition",
                            "home_team","away_team","home_score","away_score"]]
passes_df = passes_df.merge(matches_meta, on="match_id", how="left")
passes_df.to_csv("path/to/save.csv", index=False)
```

---

## Phase 3: Data Cleaning

**Rationale**: The `location` and `pass_end_location` columns are stored as JSON list strings; parse them with `ast.literal_eval` and clip coordinates to pitch bounds.

```python
def load_passes(path):
    import ast
    df = pd.read_csv(path, low_memory=False, converters={
        "location":          lambda x: ast.literal_eval(x) if pd.notna(x) else None,
        "pass_end_location": lambda x: ast.literal_eval(x) if pd.notna(x) else None,
    })
    return clean_passes(df)

def clean_passes(df):
    # Unpack coordinates
    df["start_x"] = df["location"].apply(lambda v: v[0] if isinstance(v, (list,tuple)) else None)
    df["start_y"] = df["location"].apply(lambda v: v[1] if isinstance(v, (list,tuple)) else None)
    df["end_x"]   = df["pass_end_location"].apply(lambda v: v[0] if isinstance(v,(list,tuple)) else None)
    df["end_y"]   = df["pass_end_location"].apply(lambda v: v[1] if isinstance(v,(list,tuple)) else None)
    # Remove invalid passes
    df = df[df["pass_outcome"] != "Injury Clearance"]
    # Clip to pitch bounds
    for col, maxv in [("start_x",120),("end_x",120),("start_y",80),("end_y",80)]:
        df[col] = df[col].clip(0, maxv)
    return df
```

---

## Phase 4: Helper Functions

```python
def _norm(x):
    """Normalise a player name to lowercase + stripped for consistent cross-source matching."""
    return str(x).strip().lower() if pd.notna(x) else None

def format_nickname(name):
    """Capitalise each word while preserving common particles (de, van, von, etc.)."""
    particles = {"de","da","del","van","von"}
    words = str(name).split()
    return " ".join(w.lower() if w.lower() in particles else w.capitalize() for w in words)
```

---

## Phase 5: Match-Level Network

**Rationale**: Nodes = average on-ball position of each starter (pooling both passing and receiving touches); edges = pass count between player pairs.

```python
def get_starting_xi(match_id, team):
    """Get starting 11: explode positions → sort by first appearance time → take head(11)."""
    lineup = sb.lineups(match_id=match_id)[team]
    df = lineup.explode("positions")
    pos = pd.json_normalize(df["positions"])
    df = pd.concat([df.drop(columns="positions").reset_index(drop=True), pos], axis=1)
    df["player"] = df["player_name"].apply(_norm)
    df["from"] = df["from"].fillna("0:00")
    return df.sort_values("from").head(11)[["player","nickname"]]

def build_match_network(match_id, team, passes):
    df = passes[(passes["match_id"]==match_id) & (passes["team"]==team)].copy()
    df["p"] = df["player"].apply(_norm)
    df["r"] = df["pass_recipient"].apply(_norm)
    xi = get_starting_xi(match_id, team)
    starters = xi["player"].tolist()
    # Pool passer and recipient positions
    locs = pd.concat([
        df[df["p"].isin(starters)][["p","start_x","start_y"]].rename(columns={"p":"player","start_x":"x","start_y":"y"}),
        df[df["r"].isin(starters)][["r","end_x","end_y"]].rename(columns={"r":"player","end_x":"x","end_y":"y"}),
    ])
    avg = locs.groupby("player").agg(x=("x","mean"), y=("y","mean")).reset_index()
    return (avg, df, xi) if len(avg) >= 11 else None

def build_edges(pass_df, node_pos):
    """Count passes between player pairs and attach coordinates."""
    edges = (pass_df.groupby(["p","r"]).size()
             .reset_index(name="weight")
             .rename(columns={"p":"slot_from","r":"slot_to"}))
    edges = edges[edges["slot_from"] != edges["slot_to"]]
    edges = (edges
             .merge(node_pos.rename(columns={"player":"slot_from","x":"x_start","y":"y_start"}), on="slot_from")
             .merge(node_pos.rename(columns={"player":"slot_to","x":"x_end","y":"y_end"}), on="slot_to"))
    return edges
```

---

## Phase 6: Cross-Match Alignment (Hungarian Algorithm)

**Rationale**: Line-ups change from match to match. To aggregate across games, each match's nodes must be mapped to a shared set of positional "slots" — the Hungarian algorithm finds the globally optimal spatial assignment.

```python
def _align_nodes(match_nodes, reference):
    """Align each match's nodes to a reference layout (first match's average positions)."""
    aligned = []
    for nodes in match_nodes:
        if len(nodes) < len(reference):
            continue
        # Cost matrix: pairwise Euclidean distances
        cost = np.linalg.norm(
            nodes[["x","y"]].values[:, None, :] - reference[["x","y"]].values[None, :, :],
            axis=2
        )
        r, c = linear_sum_assignment(cost)   # Hungarian algorithm
        nodes = nodes.iloc[r].copy()
        nodes["slot"] = c
        aligned.append(nodes)
    return aligned
```

---

## Phase 7: Season-Level Aggregation

**Rationale**: Average slot positions across all matches, sum edge weights, then use a second pass of the Hungarian algorithm to label each slot with the most representative player.

```python
def build_season_network(passes, team, season):
    # 1. Collect match-level results for every game
    # 2. Align all matches to shared slots via _align_nodes
    # 3. Average position per slot → node_pos
    node_pos = nodes_df.groupby("slot").agg(x=("x","mean"), y=("y","mean")).reset_index()
    # 4. Second Hungarian pass: map slot → most representative player
    matrix = ...  # player × slot appearance count matrix
    r_ind, c_ind = linear_sum_assignment(-matrix)
    slot_to_player = {slots[j]: players[i] for i,j in zip(r_ind, c_ind)}
    # 5. Aggregate pass edges
    all_passes["slot_from"] = all_passes["p"].map(player_to_slot)
    all_passes["slot_to"]   = all_passes["r"].map(player_to_slot)
    edges = all_passes.groupby(["slot_from","slot_to"]).size().reset_index(name="weight")
    return node_pos, edges
```

---

## Phase 8: Visualization

**Rationale**: `mplsoccer` provides a StatsBomb-compatible pitch background. Edge width and opacity scale proportionally with pass count; nodes are blue scatter points with white rounded-box labels.

```python
def _draw_network(ax, pitch, node_pos, edges, node_size=240, label_size=8):
    pitch.draw(ax=ax)
    max_w = edges["weight"].max()
    for _, r in edges.iterrows():
        pitch.lines(r.x_start, r.y_start, r.x_end, r.y_end,
                    lw=(r["weight"]/max_w)*6,            # line width ∝ pass count
                    alpha=0.3 + (r["weight"]/max_w)*0.6, # opacity ∝ pass count
                    color="red", ax=ax, zorder=1)
    pitch.scatter(node_pos.x, node_pos.y, s=node_size,
                  color="blue", edgecolor="black", ax=ax, zorder=3)
    for _, r in node_pos.iterrows():
        ax.text(r.x, r.y, r["label"], ha="center", va="center",
                fontsize=label_size, fontweight="bold",
                bbox=dict(facecolor="white", alpha=0.6, edgecolor="none", boxstyle="round,pad=0.2"),
                zorder=4)
```

**Away team mirroring**: In single-match side-by-side plots, the away team's coordinates are flipped (`PITCH_X_MAX - x`) so both teams attack left-to-right.

---

## Phase 9: Responsive Grid Layout

```python
def _make_grid(n_items, n_cols):
    if n_items == 1:  return fig(10,6), [ax], node_size=400
    if n_items == 2:  return fig(14,5), axes, node_size=320
    else:             return fig(18, 4*n_rows), axes.flatten(), node_size=240
```

---

## Phase 10: Universal Entry Point — `plot_network()`

Four calling modes:

| Call | Output |
|---|---|
| `plot_network(passes, match_id=id)` | Single match, both teams side by side (away mirrored) |
| `plot_network(passes, team=t, season=s, match_level=True)` | Grid of every match for one team |
| `plot_network(passes, team=t, season=s)` | Season-aggregated network for one team |
| `plot_network(passes, season=s)` | Season-aggregated grid for all teams |

---

## Key Design Decisions

1. **Average position over fixed formation**: Players move dynamically during a match; averaging all on-ball touches (both as passer and recipient) captures their true activity zone.
2. **Hungarian alignment is necessary**: Squads rotate across matches, so aggregation must align positional *roles* rather than player names — the Hungarian algorithm finds the globally optimal spatial matching.
3. **Two rounds of Hungarian**: Round 1 aligns spatial positions (each match → slots); Round 2 maps slots to the most representative player (for labelling).
4. **Coordinate system**: StatsBomb uses a (0→120, 0→80) coordinate system; `mplsoccer`'s `pitch_type="statsbomb"` is directly compatible — no conversion needed.
