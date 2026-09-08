"""Merge market ADP vs. model VBD, flag sleepers/overvalued, via a Sleeper-id crosswalk."""
import json
import re
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz, process

DATA_DIR = Path(__file__).parent / "data"
SLEEPER_URL = "https://api.sleeper.app/v1/players/nfl"
FUZZY_THRESHOLD = 90
SLEEPER_POSITIONS = {"QB", "RB", "WR", "TE"}


def normalize_name(name: str) -> str:
    name = name.lower()
    name = name.replace(".", "").replace("'", "").replace("-", " ")
    name = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def load_sleeper_players() -> pd.DataFrame:
    cache_path = DATA_DIR / "sleeper_players.json"
    if cache_path.exists():
        print(f"Using cached {cache_path}")
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
    else:
        import requests
        print(f"Fetching {SLEEPER_URL} ...")
        resp = requests.get(SLEEPER_URL, timeout=60)
        resp.raise_for_status()
        raw = resp.json()
        cache_path.write_text(json.dumps(raw), encoding="utf-8")
        print(f"Cached to {cache_path}")

    rows = []
    for pid, p in raw.items():
        pos = p.get("position")
        if pos not in SLEEPER_POSITIONS:
            continue
        name = p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
        if not name:
            continue
        rows.append({
            "sleeper_id": pid,
            "name": name,
            "norm_name": normalize_name(name),
            "team": p.get("team"),
            "position": pos,
            "years_exp": p.get("years_exp"),
            "active": p.get("active"),
            "injury_status": p.get("injury_status"),
        })
    df = pd.DataFrame(rows)
    print(f"Canonical Sleeper list: {len(df)} active-position players")
    return df


def match_to_canonical(df: pd.DataFrame, name_col: str, canonical: pd.DataFrame, label: str) -> pd.DataFrame:
    """Return df with a new 'sleeper_id' column, matched exact-first then fuzzy fallback."""
    canonical_by_name = canonical.groupby("norm_name")["sleeper_id"].apply(list).to_dict()
    choices = canonical["norm_name"].tolist()

    sleeper_ids = []
    fallback_log = []
    for _, row in df.iterrows():
        norm = normalize_name(row[name_col])
        candidates = canonical_by_name.get(norm)
        if candidates:
            # prefer a position match among exact-name candidates
            pos_matches = [
                sid for sid in candidates
                if canonical.loc[canonical["sleeper_id"] == sid, "position"].iloc[0] == row.get("position")
            ]
            sleeper_ids.append(pos_matches[0] if pos_matches else candidates[0])
            continue

        result = process.extractOne(norm, choices, scorer=fuzz.WRatio, score_cutoff=FUZZY_THRESHOLD)
        if result:
            match_name, score, _ = result
            match_ids = canonical_by_name[match_name]
            pos_matches = [
                sid for sid in match_ids
                if canonical.loc[canonical["sleeper_id"] == sid, "position"].iloc[0] == row.get("position")
            ]
            sid = pos_matches[0] if pos_matches else match_ids[0]
            sleeper_ids.append(sid)
            fallback_log.append((row[name_col], match_name, score))
        else:
            sleeper_ids.append(None)

    df = df.copy()
    df["sleeper_id"] = sleeper_ids

    if fallback_log:
        print(f"\nFuzzy fallback matches for {label} ({len(fallback_log)}):")
        for orig, matched, score in fallback_log:
            print(f"  {score:5.1f}  {orig!r:30} -> {matched!r}")

    unmatched = df["sleeper_id"].isna().sum()
    if unmatched:
        print(f"  {unmatched} {label} rows unmatched to Sleeper canonical list")

    return df


def left_join_on_sleeper_id(left: pd.DataFrame, right: pd.DataFrame, right_cols: list) -> pd.DataFrame:
    """pandas merges NaN keys with each other by default, which explodes any
    row with an unmatched (NaN) sleeper_id against every other unmatched row
    on the right. Split matched/unmatched and only merge the matched half."""
    has_id = left["sleeper_id"].notna()
    matched = left[has_id].merge(right[right["sleeper_id"].notna()][right_cols], on="sleeper_id", how="left")
    unmatched = left[~has_id].copy()
    for col in right_cols:
        if col != "sleeper_id" and col not in unmatched.columns:
            unmatched[col] = pd.NA
    return pd.concat([matched, unmatched], ignore_index=True)


def main() -> None:
    canonical = load_sleeper_players()

    # --- ADP ---
    adp_raw = json.loads((DATA_DIR / "adp_raw.json").read_text())
    adp = pd.DataFrame(adp_raw["players"])
    adp = adp.sort_values("adp").reset_index(drop=True)
    adp["adp_rank"] = adp.index + 1
    adp = match_to_canonical(adp, "name", canonical, "ADP")

    # --- VBD tiers ---
    tiers = pd.read_csv(DATA_DIR / "tiers.csv")
    tiers = match_to_canonical(tiers, "player_name", canonical, "tiers")

    # --- modeled players: join on sleeper_id ---
    merged = left_join_on_sleeper_id(tiers, adp, ["sleeper_id", "adp_rank"])
    merged["value_gap"] = merged["adp_rank"] - merged["vbd_rank"]
    merged["sleeper_flag"] = merged["value_gap"] > 15
    merged["overvalued"] = merged["value_gap"] < -15
    merged["valuation_basis"] = "VBD"
    merged = merged.rename(columns={"player_name": "name", "shrunk_ppg": "shrunk_ppg"})
    modeled_out = merged[[
        "tier", "vbd_rank", "adp_rank", "value_gap", "sleeper_flag", "overvalued",
        "valuation_basis", "name", "position", "team", "shrunk_ppg",
    ]]

    n_no_adp = modeled_out["adp_rank"].isna().sum()
    if n_no_adp:
        print(f"\n{n_no_adp} modeled players had no ADP match (value_gap left blank)")

    # --- rookies / thin data: ADP-only ranking ---
    thin = pd.read_csv(DATA_DIR / "rookies_and_thin_data.csv")
    thin = match_to_canonical(thin, "player_name", canonical, "rookies/thin-data")
    thin_merged = left_join_on_sleeper_id(thin, adp, ["sleeper_id", "adp_rank"])
    thin_merged = thin_merged.sort_values("adp_rank", na_position="last")
    thin_merged["tier"] = pd.NA
    thin_merged["vbd_rank"] = pd.NA
    thin_merged["value_gap"] = pd.NA
    thin_merged["sleeper_flag"] = False
    thin_merged["overvalued"] = False
    thin_merged["valuation_basis"] = "ADP-only, no stat history"
    thin_merged = thin_merged.rename(columns={"player_name": "name"})
    thin_out = thin_merged[[
        "tier", "vbd_rank", "adp_rank", "value_gap", "sleeper_flag", "overvalued",
        "valuation_basis", "name", "position", "team",
    ]]
    thin_out["shrunk_ppg"] = pd.NA

    cheat_sheet = pd.concat([modeled_out, thin_out], ignore_index=True)
    cheat_sheet = cheat_sheet.sort_values(
        ["valuation_basis", "vbd_rank", "adp_rank"], na_position="last"
    )

    out_path = DATA_DIR.parent / "cheat_sheet.csv"
    cheat_sheet.to_csv(out_path, index=False)
    print(f"\nSaved {len(cheat_sheet)} players to {out_path}")

    sleepers = cheat_sheet[cheat_sheet["sleeper_flag"] == True].sort_values("vbd_rank")
    print(f"\n{len(sleepers)} sleeper-flagged players (value_gap > 15). Top 20:")
    print(sleepers[["vbd_rank", "adp_rank", "value_gap", "name", "position", "team"]].head(20).to_string(index=False))


if __name__ == "__main__":
    main()
