"""Multi-year blended, shrinkage-adjusted fantasy points model.

Scoring: 0.04/pass yd, 4/pass TD, -2/INT, 0.1/rush yd, 6/rush TD,
1/reception, 0.1/rec yd, 6/rec TD.
"""
import sys
from pathlib import Path

import nfl_data_py as nfl
import pandas as pd

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

YEARS = [2023, 2024, 2025]
RECENCY_WEIGHTS = {2025: 0.5, 2024: 0.3, 2023: 0.2}
SHRINK_K = 6
MAX_GAMES = 51  # 17 games * 3 seasons

STAT_COLS = [
    "passing_yards", "passing_tds", "interceptions",
    "rushing_yards", "rushing_tds",
    "receptions", "receiving_yards", "receiving_tds",
]

# Independently sourced (ESPN + cross-checked search, 2025 regular season)
# actual totals used to sanity-check the scoring formula / aggregation.
VERIFICATION = {
    "Ja'Marr Chase": 314.2,   # 125 rec, 1412 yds, 8 TD
    "Saquon Barkley": 232.3,  # 1140 rush yds, 7 rush TD, 37 rec, 273 rec yds, 2 rec TD
    "Josh Allen": 368.62,     # 3668 pass yds, 25 pass TD, 10 INT, 579 rush yds, 14 rush TD
}


def fetch_weekly_data(years: list[int]) -> pd.DataFrame:
    """nflverse renamed the 'player_stats' release to 'stats_player_week_<year>'
    partway through 2025; nfl_data_py 0.3.2 still points at the old (now-404)
    per-year URLs. Try the library first, fall back to the current release path."""
    try:
        df = nfl.import_weekly_data(years)
        print("Fetched via nfl_data_py.import_weekly_data")
        return df
    except Exception as e:
        print(f"nfl_data_py.import_weekly_data failed ({e});")
        print("falling back to direct fetch from nflverse-data's 'stats_player' release.")
        frames = []
        for y in years:
            url = f"https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{y}.parquet"
            frames.append(pd.read_parquet(url))
        return pd.concat(frames, ignore_index=True)


def score(df: pd.DataFrame, int_col: str) -> pd.Series:
    for col in STAT_COLS:
        if col not in df.columns and col != "interceptions":
            df[col] = 0
    fill_cols = [c for c in STAT_COLS if c != "interceptions"] + [int_col]
    df = df.fillna({c: 0 for c in fill_cols})
    return (
        0.04 * df["passing_yards"]
        + 4 * df["passing_tds"]
        - 2 * df[int_col]
        + 0.1 * df["rushing_yards"]
        + 6 * df["rushing_tds"]
        + 1 * df["receptions"]
        + 0.1 * df["receiving_yards"]
        + 6 * df["receiving_tds"]
    )


def main() -> None:
    print(f"Fetching weekly data for {YEARS}...")
    weekly = fetch_weekly_data(YEARS)

    if "season_type" in weekly.columns:
        weekly = weekly[weekly["season_type"] == "REG"].copy()

    name_col = "player_display_name" if "player_display_name" in weekly.columns else "player_name"
    id_col = "player_id" if "player_id" in weekly.columns else name_col
    team_col = "recent_team" if "recent_team" in weekly.columns else "team"
    int_col = "interceptions" if "interceptions" in weekly.columns else "passing_interceptions"

    weekly["fantasy_points_custom"] = score(weekly, int_col)

    # --- verification block (independent of downstream blending) ---
    print("\nVerification against independently sourced 2025 totals:")
    all_pass = True
    season_2025 = weekly[weekly["season"] == 2025]
    for name, expected in VERIFICATION.items():
        actual = season_2025.loc[season_2025[name_col] == name, "fantasy_points_custom"].sum()
        if actual == 0:
            print(f"  FAIL  {name}: no rows found for 2025 (check name match)")
            all_pass = False
            continue
        pct_diff = abs(actual - expected) / expected
        status = "PASS" if pct_diff <= 0.05 else "FAIL"
        if status == "FAIL":
            all_pass = False
        print(f"  {status}  {name}: computed={actual:.2f} expected={expected:.2f} diff={pct_diff:.1%}")

    if not all_pass:
        print("\nERROR: verification failed — scoring/aggregation logic is suspect. Halting.", file=sys.stderr)
        sys.exit(1)
    print("All verification checks passed.\n")

    # --- season-level aggregation ---
    season_group = (
        weekly.groupby([id_col, name_col, "position", team_col, "season"])
        .agg(season_total=("fantasy_points_custom", "sum"), games=("week", "nunique"))
        .reset_index()
    )
    season_group["ppg"] = season_group["season_total"] / season_group["games"]

    # most recent position/team per player
    latest = (
        season_group.sort_values("season")
        .groupby(id_col)
        .last()[[name_col, "position", team_col]]
        .rename(columns={name_col: "player_name", team_col: "team"})
    )

    # per-player blended PPG (recency-weighted, renormalized over available years)
    records = []
    for pid, grp in season_group.groupby(id_col):
        weight_sum = 0.0
        weighted_ppg = 0.0
        total_games = 0
        for _, row in grp.iterrows():
            yr = row["season"]
            if yr not in RECENCY_WEIGHTS:
                continue
            w = RECENCY_WEIGHTS[yr]
            weighted_ppg += w * row["ppg"]
            weight_sum += w
            total_games += row["games"]
        if weight_sum == 0:
            continue
        blended_ppg = weighted_ppg / weight_sum
        records.append({
            "player_id": pid,
            "blended_ppg": blended_ppg,
            "total_games": min(total_games, MAX_GAMES),
        })

    blended = pd.DataFrame(records).set_index("player_id").join(latest)

    # position average blended PPG, then shrinkage
    pos_avg = blended.groupby("position")["blended_ppg"].transform("mean")
    games = blended["total_games"]
    blended["shrunk_ppg"] = (
        (games / (games + SHRINK_K)) * blended["blended_ppg"]
        + (SHRINK_K / (games + SHRINK_K)) * pos_avg
    )

    out = blended.reset_index()[
        ["player_name", "position", "team", "blended_ppg", "shrunk_ppg", "total_games"]
    ].sort_values("shrunk_ppg", ascending=False)

    out_path = DATA_DIR / "blended_points.csv"
    out.to_csv(out_path, index=False)
    print(f"Saved {len(out)} players to {out_path}")
    print(out.head(15).to_string(index=False))


if __name__ == "__main__":
    main()
