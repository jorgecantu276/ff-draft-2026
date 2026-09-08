"""VBD, tiers, rookie/thin-data carve-out, and separate K/DST ranking.

League: 10 teams, starters QB=1, RB=2, WR=2, TE=1, FLEX=1 (RB/WR/TE eligible).
"""
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent / "data"

TEAMS = 10
STARTERS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1}
FLEX_SLOTS = TEAMS * 1
FLEX_ELIGIBLE = ["RB", "WR", "TE"]
SEASON_GAMES = 17
# Spec calls for a new tier when the drop exceeds ~15% of the VBD range.
# Tested at 15% (and at 5%/7%/10%) against this shrinkage-smoothed data: the
# curve is too smooth for any gap to clear that bar, producing a single
# degenerate tier across all 752 players. Calibrated down to 3% (of the
# range from replacement-level VBD=0 to the top player's VBD), which yields
# 17 tiers overall / 11 within the top 100 — a usable cheat-sheet spread.
# Flagging this deviation from the literal spec; adjust TIER_GAP_PCT if you
# want tiers coarser or finer.
TIER_GAP_PCT = 0.03


def compute_replacement_levels(df: pd.DataFrame) -> dict:
    """Dedicated starters per position, plus FLEX slots allocated to whichever
    RB/WR/TE players ranked just past their dedicated cutoff have the highest
    shrunk_ppg (i.e. scarcity-driven FLEX allocation)."""
    dedicated_cutoff = {pos: TEAMS * n for pos, n in STARTERS.items()}

    flex_pool = []
    for pos in FLEX_ELIGIBLE:
        pos_df = df[df["position"] == pos].sort_values("shrunk_ppg", ascending=False)
        beyond = pos_df.iloc[dedicated_cutoff[pos]:]
        flex_pool.append(beyond.assign(flex_position=pos))
    flex_pool = pd.concat(flex_pool).sort_values("shrunk_ppg", ascending=False)
    flex_picks = flex_pool.head(FLEX_SLOTS)
    flex_counts = flex_picks["flex_position"].value_counts().to_dict()

    replacement_rank = {"QB": dedicated_cutoff["QB"]}
    for pos in FLEX_ELIGIBLE:
        replacement_rank[pos] = dedicated_cutoff[pos] + flex_counts.get(pos, 0)

    replacement_ppg = {}
    for pos, rank in replacement_rank.items():
        pos_df = df[df["position"] == pos].sort_values("shrunk_ppg", ascending=False)
        idx = min(rank, len(pos_df) - 1)
        replacement_ppg[pos] = pos_df.iloc[idx]["shrunk_ppg"]

    print("Replacement levels (rank -> shrunk_ppg):")
    for pos in ["QB", "RB", "WR", "TE"]:
        extra = f" (+{flex_counts.get(pos, 0)} flex)" if pos in FLEX_ELIGIBLE else ""
        print(f"  {pos}: rank {replacement_rank[pos]}{extra} -> {replacement_ppg[pos]:.2f} ppg")

    return replacement_ppg


def assign_tiers(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("vbd", ascending=False).reset_index(drop=True)
    vbd_range = max(df["vbd"].max(), 0)  # range from replacement (0) to best player
    threshold = TIER_GAP_PCT * vbd_range
    print(f"Tier gap threshold: {threshold:.2f} VBD ({TIER_GAP_PCT:.0%} of {vbd_range:.1f} range)")

    tiers = [1]
    for i in range(1, len(df)):
        gap = df.loc[i - 1, "vbd"] - df.loc[i, "vbd"]
        tiers.append(tiers[-1] + 1 if gap > threshold else tiers[-1])
    df["tier"] = tiers
    df["vbd_rank"] = df.index + 1
    return df


def compute_k_dst() -> pd.DataFrame:
    """K and DST ranked by 2025 raw total points. The league's scoring rules
    only cover offensive skill positions, so this uses standard default
    K/DST scoring conventions (documented inline) — adjust if your league
    differs."""
    team_wk = pd.read_parquet(
        "https://github.com/nflverse/nflverse-data/releases/download/stats_team/stats_team_week_2025.parquet"
    )
    team_wk = team_wk[team_wk["season_type"] == "REG"].copy()

    games = pd.read_parquet(
        "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.parquet"
    )
    games = games[(games["season"] == 2025) & (games["game_type"] == "REG")]

    home = games[["week", "home_team", "away_score"]].rename(
        columns={"home_team": "team", "away_score": "points_allowed"}
    )
    away = games[["week", "away_team", "home_score"]].rename(
        columns={"away_team": "team", "home_score": "points_allowed"}
    )
    pa = pd.concat([home, away], ignore_index=True)

    def pa_points(pts: float) -> float:
        if pts == 0:
            return 10
        if pts <= 6:
            return 7
        if pts <= 13:
            return 4
        if pts <= 20:
            return 1
        if pts <= 27:
            return 0
        if pts <= 34:
            return -1
        return -4

    pa["pa_score"] = pa["points_allowed"].apply(pa_points)

    dst = team_wk.groupby("team").agg(
        sacks=("def_sacks", "sum"),
        interceptions=("def_interceptions", "sum"),
        fumble_rec=("def_fumbles", "sum"),
        safeties=("def_safeties", "sum"),
        def_tds=("def_tds", "sum"),
        st_tds=("special_teams_tds", "sum"),
        blocks=("def_punt_blocks", "sum"),
    ).reset_index()
    dst["blocks"] += (
        team_wk.groupby("team")["def_pat_blocks"].sum().values
        + team_wk.groupby("team")["def_fg_blocks"].sum().values
    )
    pa_by_team = pa.groupby("team")["pa_score"].sum().reset_index()
    dst = dst.merge(pa_by_team, on="team", how="left")

    dst["total_points"] = (
        dst["sacks"] * 1
        + dst["interceptions"] * 2
        + dst["fumble_rec"] * 2
        + dst["safeties"] * 2
        + (dst["def_tds"] + dst["st_tds"]) * 6
        + dst["blocks"] * 2
        + dst["pa_score"]
    )
    dst["position"] = "DST"
    dst["name"] = dst["team"] + " DST"
    dst = dst[["name", "position", "team", "total_points"]]

    k_wk = team_wk  # kicking stats live in the same per-team weekly file
    kick = k_wk.groupby("team").agg(
        fg_0_39=("fg_made_0_19", "sum"),
        fg_20_29=("fg_made_20_29", "sum"),
        fg_30_39=("fg_made_30_39", "sum"),
        fg_40_49=("fg_made_40_49", "sum"),
        fg_50_59=("fg_made_50_59", "sum"),
        fg_60_=("fg_made_60_", "sum"),
        fg_missed=("fg_missed", "sum"),
        pat_made=("pat_made", "sum"),
    ).reset_index()
    kick["total_points"] = (
        (kick["fg_0_39"] + kick["fg_20_29"] + kick["fg_30_39"]) * 3
        + kick["fg_40_49"] * 4
        + (kick["fg_50_59"] + kick["fg_60_"]) * 5
        - kick["fg_missed"] * 1
        + kick["pat_made"] * 1
    )
    kick["position"] = "K"
    kick["name"] = kick["team"] + " K"
    kick = kick[["name", "position", "team", "total_points"]]

    out = pd.concat([kick, dst], ignore_index=True).sort_values(
        ["position", "total_points"], ascending=[True, False]
    )
    out["rank"] = out.groupby("position")["total_points"].rank(ascending=False, method="min").astype(int)
    return out


def main() -> None:
    df = pd.read_csv(DATA_DIR / "blended_points.csv")
    df = df[df["position"].isin(["QB", "RB", "WR", "TE"])].copy()

    thin = df[df["total_games"] < 3].copy()
    thin_path = DATA_DIR / "rookies_and_thin_data.csv"
    thin.to_csv(thin_path, index=False)
    print(f"Split off {len(thin)} rookies/thin-data players to {thin_path}")

    modeled = df[df["total_games"] >= 3].copy()

    replacement_ppg = compute_replacement_levels(modeled)
    modeled["replacement_ppg"] = modeled["position"].map(replacement_ppg)
    modeled["vbd"] = (modeled["shrunk_ppg"] - modeled["replacement_ppg"]) * SEASON_GAMES

    tiered = assign_tiers(modeled)
    tiers_path = DATA_DIR / "tiers.csv"
    tiered[
        ["vbd_rank", "tier", "player_name", "position", "team", "shrunk_ppg", "vbd"]
    ].to_csv(tiers_path, index=False)
    print(f"\nSaved {len(tiered)} QB/RB/WR/TE players to {tiers_path} ({tiered['tier'].max()} tiers)")
    print(tiered[["vbd_rank", "tier", "player_name", "position", "team", "shrunk_ppg", "vbd"]].head(15).to_string(index=False))

    print("\nComputing K/DST simple rankings (2025 raw totals, standard scoring)...")
    k_dst = compute_k_dst()
    k_dst_path = DATA_DIR / "k_dst_simple.csv"
    k_dst.to_csv(k_dst_path, index=False)
    print(f"Saved {len(k_dst)} K/DST entries to {k_dst_path}")
    print(k_dst.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
