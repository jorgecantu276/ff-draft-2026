"""Add injury/active status to cheat_sheet.csv and flag anyone risky in the top 150."""
import json
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent / "data"
ROOT = Path(__file__).parent

RISKY_STATUSES = {"Out", "IR", "PUP"}


def main() -> None:
    cheat_sheet = pd.read_csv(ROOT / "cheat_sheet.csv")

    raw = json.loads((DATA_DIR / "sleeper_players.json").read_text(encoding="utf-8"))
    status_by_id = {
        pid: {"active": p.get("active"), "injury_status": p.get("injury_status")}
        for pid, p in raw.items()
    }

    # merge_value.py matched via sleeper_id but didn't carry it into cheat_sheet.csv,
    # so re-run the same crosswalk match here rather than re-deriving sleeper_id.
    import re
    from rapidfuzz import fuzz, process

    def normalize_name(name: str) -> str:
        name = str(name).lower()
        name = name.replace(".", "").replace("'", "").replace("-", " ")
        name = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", name)
        name = re.sub(r"\s+", " ", name).strip()
        return name

    canonical_rows = []
    for pid, p in raw.items():
        pos = p.get("position")
        if pos not in {"QB", "RB", "WR", "TE"}:
            continue
        name = p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
        if not name:
            continue
        canonical_rows.append({
            "sleeper_id": pid, "norm_name": normalize_name(name), "position": pos,
        })
    canonical = pd.DataFrame(canonical_rows)
    canonical_by_name = canonical.groupby("norm_name")["sleeper_id"].apply(list).to_dict()
    choices = canonical["norm_name"].tolist()

    def find_sleeper_id(name, position):
        norm = normalize_name(name)
        candidates = canonical_by_name.get(norm)
        if not candidates:
            result = process.extractOne(norm, choices, scorer=fuzz.WRatio, score_cutoff=90)
            if not result:
                return None
            candidates = canonical_by_name[result[0]]
        pos_matches = [
            sid for sid in candidates
            if canonical.loc[canonical["sleeper_id"] == sid, "position"].iloc[0] == position
        ]
        return pos_matches[0] if pos_matches else candidates[0]

    active_list, injury_list = [], []
    for _, row in cheat_sheet.iterrows():
        sid = find_sleeper_id(row["name"], row["position"])
        info = status_by_id.get(sid, {})
        active_list.append(info.get("active"))
        injury_list.append(info.get("injury_status"))

    cheat_sheet["active"] = active_list
    cheat_sheet["injury_status"] = injury_list
    cheat_sheet.to_csv(ROOT / "cheat_sheet.csv", index=False)
    print(f"Added injury_status/active to {ROOT / 'cheat_sheet.csv'}")

    # "top 150 overall" = ADP rank, since it's the one rank that's comparable
    # across every position (vbd_rank only covers modeled QB/RB/WR/TE).
    top150 = cheat_sheet[cheat_sheet["adp_rank"].fillna(9999).astype(float) <= 150]
    risky = top150[
        (top150["active"] == False)
        | (top150["injury_status"].isin(RISKY_STATUSES))
    ]
    print(f"\n{len(risky)} players in top 150 overall (by ADP) flagged inactive or Out/IR/PUP:")
    if len(risky):
        print(risky[["adp_rank", "name", "position", "team", "active", "injury_status"]].sort_values("adp_rank").to_string(index=False))
    else:
        print("  (none)")


if __name__ == "__main__":
    main()
