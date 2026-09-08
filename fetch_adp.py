"""Fetch ADP data from FantasyFootballCalculator for the 2026 PPR draft prep."""
import json
import sys
from pathlib import Path

import requests

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

MIN_PLAYERS = 150


def fetch_adp(year: int) -> dict:
    url = f"https://fantasyfootballcalculator.com/api/v1/adp/ppr?teams=10&year={year}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def main() -> None:
    data = fetch_adp(2026)
    players = data.get("players", [])

    if len(players) < MIN_PLAYERS:
        print(f"2026 ADP data thin ({len(players)} players) — falling back to 2025.")
        data = fetch_adp(2025)
        players = data.get("players", [])

    if len(players) < MIN_PLAYERS:
        print(
            f"ERROR: player count ({len(players)}) is under the {MIN_PLAYERS} threshold "
            "even after falling back to 2025. Refusing to proceed on thin data.",
            file=sys.stderr,
        )
        sys.exit(1)

    out_path = DATA_DIR / "adp_raw.json"
    out_path.write_text(json.dumps(data, indent=2))

    print(f"Total player count: {len(players)}")
    print(f"Saved to {out_path}")
    print("\nFirst 10 rows:")
    for p in players[:10]:
        print(
            f"  {p.get('adp_rank', p.get('rank', '?')):>4}  "
            f"{p.get('name', '?'):<25} {p.get('position', '?'):<4} "
            f"{p.get('team', '?'):<4} adp={p.get('adp', '?')}"
        )


if __name__ == "__main__":
    main()
