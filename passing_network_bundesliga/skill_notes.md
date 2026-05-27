---
name: football-passing-network-skill
description: 完整的足球传球网络构建流水线 —— 从 StatsBomb 数据提取、清洗、网络建模到多场景可视化呈现的思路与方法
metadata: 
  node_type: memory
  type: project
  originSessionId: fa9b3116-c447-43c5-81b1-0af15b7049f3
---

# Football Passing Network — 方法论 & Skill 蒸馏

来源：`D:\桌面\Network_sample.ipynb`（Bundesliga 2015/16，StatsBomb 免费数据）

---

## 核心依赖

| 包 | 用途 |
|---|---|
| `statsbombpy` | 免费足球事件数据 API |
| `mplsoccer` | 足球场坐标系可视化 |
| `scipy.optimize.linear_sum_assignment` | 匈牙利算法（节点对齐） |
| `pandas / numpy / matplotlib` | 数据处理与绘图 |
| `tqdm` | 批量提取进度条 |

常量：`PITCH_X_MAX=120, PITCH_Y_MAX=80, MIN_STARTERS=11`

---

## Phase 1：数据发现（Competition Selection）

**思路**：StatsBomb 免费数据并非每场比赛都可用，需先筛选出样本足够的赛事。

```python
free_comps = sb.competitions()
comps = free_comps[free_comps["competition_gender"] == "male"]
# 仅保留 season_start >= 2015 的赛季
comps["season_start"] = comps["season_name"].str.split("/").str[0].astype(int)

# 统计每个赛事的比赛数，筛出样本量足够的（阈值 FULL_MATCH_THRESHOLD=100）
for comp_id, season_id in zip(...):
    matches = sb.matches(competition_id=comp_id, season_id=season_id)
    match_counts.append({"matches_count": len(matches), ...})
full_comps = match_counts_df[match_counts_df["matches_count"] >= 100]
```

**注意**：StatsBomb 免费德甲数据（competition_id=9）只含 34 场，全部是拜尔勒沃库森相关比赛，并非完整赛季。

---

## Phase 2：数据提取（Pass Extraction）

**思路**：从事件流中过滤出传球事件，按比赛批量提取，合并元数据后保存 CSV。

```python
all_passes = []
for match_id in tqdm(matches_df["match_id"]):
    events = sb.events(match_id=match_id)
    passes = events[events["type"] == "Pass"].copy()
    passes["match_id"] = match_id
    all_passes.append(passes)

passes_df = pd.concat(all_passes, ignore_index=True)

# 合并比赛元数据（主客队、比分、日期）
matches_meta = matches_df[["match_id","match_date","season","competition",
                            "home_team","away_team","home_score","away_score"]]
passes_df = passes_df.merge(matches_meta, on="match_id", how="left")
passes_df.to_csv("path/to/save.csv", index=False)
```

---

## Phase 3：数据清洗（Cleaning）

**思路**：`location` 和 `pass_end_location` 列是 JSON 列表字符串，需用 `ast.literal_eval` 解析；坐标 clip 至球场范围内。

```python
def load_passes(path):
    import ast
    df = pd.read_csv(path, low_memory=False, converters={
        "location":          lambda x: ast.literal_eval(x) if pd.notna(x) else None,
        "pass_end_location": lambda x: ast.literal_eval(x) if pd.notna(x) else None,
    })
    return clean_passes(df)

def clean_passes(df):
    # 解包坐标
    df["start_x"] = df["location"].apply(lambda v: v[0] if isinstance(v, (list,tuple)) else None)
    df["start_y"] = df["location"].apply(lambda v: v[1] if isinstance(v, (list,tuple)) else None)
    df["end_x"]   = df["pass_end_location"].apply(lambda v: v[0] if isinstance(v,(list,tuple)) else None)
    df["end_y"]   = df["pass_end_location"].apply(lambda v: v[1] if isinstance(v,(list,tuple)) else None)
    # 去除无效传球
    df = df[df["pass_outcome"] != "Injury Clearance"]
    # 坐标限制在球场范围内
    for col, maxv in [("start_x",120),("end_x",120),("start_y",80),("end_y",80)]:
        df[col] = df[col].clip(0, maxv)
    return df
```

---

## Phase 4：辅助函数

```python
def _norm(x):
    """球员名字标准化：小写+去空格，用于跨数据源匹配"""
    return str(x).strip().lower() if pd.notna(x) else None

def format_nickname(name):
    """首字母大写，保留 de/van/von 等语言粒子"""
    particles = {"de","da","del","van","von"}
    words = str(name).split()
    return " ".join(w.lower() if w.lower() in particles else w.capitalize() for w in words)
```

---

## Phase 5：单场网络构建（Match-Level Network）

**思路**：节点 = 首发球员的平均持球位置（同时作为传球方和接球方），边 = 球员对之间的传球次数。

```python
def get_starting_xi(match_id, team):
    """获取首发11人：explode positions → 按上场时间排序 → 取前11"""
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
    # 合并传球方和接球方的位置
    locs = pd.concat([
        df[df["p"].isin(starters)][["p","start_x","start_y"]].rename(columns={"p":"player","start_x":"x","start_y":"y"}),
        df[df["r"].isin(starters)][["r","end_x","end_y"]].rename(columns={"r":"player","end_x":"x","end_y":"y"}),
    ])
    avg = locs.groupby("player").agg(x=("x","mean"), y=("y","mean")).reset_index()
    return (avg, df, xi) if len(avg) >= 11 else None

def build_edges(pass_df, node_pos):
    """统计球员对传球次数，附加坐标"""
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

## Phase 6：跨场对齐（Hungarian Algorithm Alignment）

**思路**：不同比赛首发球员不同，需将各场网络的节点映射到统一的"位置槽（slot）"，用匈牙利算法基于空间距离最优匹配。

```python
def _align_nodes(match_nodes, reference):
    """将每场比赛的节点对齐到参考布局（第一场比赛的平均位置）"""
    aligned = []
    for nodes in match_nodes:
        if len(nodes) < len(reference):
            continue
        # 代价矩阵：每对节点之间的欧氏距离
        cost = np.linalg.norm(
            nodes[["x","y"]].values[:, None, :] - reference[["x","y"]].values[None, :, :],
            axis=2
        )
        r, c = linear_sum_assignment(cost)   # 匈牙利算法
        nodes = nodes.iloc[r].copy()
        nodes["slot"] = c
        aligned.append(nodes)
    return aligned
```

---

## Phase 7：赛季网络（Season-Level Aggregation）

**思路**：将所有场次的 slot 位置取平均，传球权重汇总，再用第二轮匈牙利算法将 slot 映射到"最常出现"的球员。

```python
def build_season_network(passes, team, season):
    # 1. 遍历所有比赛，获取 match-level 结果
    # 2. 用 _align_nodes 将各场节点对齐到 slot
    # 3. 按 slot 平均位置 → node_pos
    node_pos = nodes_df.groupby("slot").agg(x=("x","mean"), y=("y","mean")).reset_index()
    # 4. 二轮匈牙利算法：slot → 最具代表性的球员
    matrix = ... # player × slot 出现次数矩阵
    r_ind, c_ind = linear_sum_assignment(-matrix)
    slot_to_player = {slots[j]: players[i] for i,j in zip(r_ind, c_ind)}
    # 5. 汇总传球边
    all_passes["slot_from"] = all_passes["p"].map(player_to_slot)
    all_passes["slot_to"]   = all_passes["r"].map(player_to_slot)
    edges = all_passes.groupby(["slot_from","slot_to"]).size().reset_index(name="weight")
    return node_pos, edges
```

---

## Phase 8：可视化（Drawing）

**思路**：mplsoccer 提供 StatsBomb 坐标系的球场背景；边的粗细和透明度与传球次数成正比；节点用蓝色散点，标签用白色圆角背景。

```python
def _draw_network(ax, pitch, node_pos, edges, node_size=240, label_size=8):
    pitch.draw(ax=ax)
    max_w = edges["weight"].max()
    for _, r in edges.iterrows():
        pitch.lines(r.x_start, r.y_start, r.x_end, r.y_end,
                    lw=(r["weight"]/max_w)*6,           # 线宽正比传球数
                    alpha=0.3 + (r["weight"]/max_w)*0.6, # 透明度正比传球数
                    color="red", ax=ax, zorder=1)
    pitch.scatter(node_pos.x, node_pos.y, s=node_size,
                  color="blue", edgecolor="black", ax=ax, zorder=3)
    for _, r in node_pos.iterrows():
        ax.text(r.x, r.y, r["label"], ha="center", va="center",
                fontsize=label_size, fontweight="bold",
                bbox=dict(facecolor="white", alpha=0.6, edgecolor="none", boxstyle="round,pad=0.2"),
                zorder=4)
```

**客队镜像**：单场双队并排时，客队的 x/y 坐标翻转（`PITCH_X_MAX - x`），使两队都从左向右进攻。

---

## Phase 9：响应式网格布局

```python
def _make_grid(n_items, n_cols):
    if n_items == 1:  return fig(10,6), [ax], node_size=400
    if n_items == 2:  return fig(14,5), axes, node_size=320
    else:             return fig(18, 4*n_rows), axes.flatten(), node_size=240
```

---

## Phase 10：统一入口 plot_network()

4 种调用模式：

| 调用方式 | 效果 |
|---|---|
| `plot_network(passes, match_id=id)` | 单场，双队并排（客队镜像）|
| `plot_network(passes, team=t, season=s, match_level=True)` | 该队全赛季所有场次网格 |
| `plot_network(passes, team=t, season=s)` | 该队赛季聚合网络 |
| `plot_network(passes, season=s)` | 全赛季所有队的网格 |

---

## 关键设计决策

1. **为什么用平均位置而非固定位置**：球员在真实比赛中位置动态变化，取所有持球/接球时刻的均值能反映其实际活动区域。
2. **为什么需要匈牙利对齐**：阵容逐场变化，跨场汇总时必须将"中后卫"这个角色而非具体球员名字对齐，匈牙利算法找全局最优匹配。
3. **两轮匈牙利**：第一轮对齐空间位置（各场 → slot），第二轮将 slot 映射到最具代表性的球员（用于标注）。
4. **坐标系**：StatsBomb 采用 (0→120, 0→80) 坐标系，mplsoccer 的 `pitch_type="statsbomb"` 直接兼容，无需转换。
