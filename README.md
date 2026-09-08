# ff-draft-2026

Draft-day cheat sheet pipeline for a 10-team PPR league (1pt/rec, 0.04/pass yd, 4pt pass TD, -2 INT, 0.1/rush yd, 6pt rush TD, 0.1/rec yd, 6pt rec TD; starters 1QB/2RB/2WR/1TE/1FLEX/1DST/1K).

Blends 2023-2025 weekly stats (nflverse) into a recency-weighted, games-shrunk points-per-game model, computes value-based draft rank against a 10-team replacement level, merges it against FantasyFootballCalculator ADP via a Sleeper-ID name crosswalk, flags sleepers/overvalued players and injury risks, and exports a tiered, printable cheat sheet.

## Pipeline

Run in order from an activated venv (`pip install -r requirements.txt`):

1. `fetch_adp.py` — pulls ADP from FantasyFootballCalculator → `data/adp_raw.json`
2. `compute_points.py` — multi-year blended/shrunk PPG model → `data/blended_points.csv`
3. `vbd.py` — VBD, tiers, rookie carve-out, K/DST simple ranking → `data/tiers.csv`, `data/rookies_and_thin_data.csv`, `data/k_dst_simple.csv`
4. `merge_value.py` — merges ADP vs. model via Sleeper crosswalk, flags sleepers → `cheat_sheet.csv`
5. `check_status.py` — adds injury/active status, flags risky top-150 players
6. `export_sheet.py` — final tiered printable sheet → `draft_cheat_sheet.csv`, `draft_cheat_sheet.html`

## Notes

- `data/sleeper_players.json` (Sleeper's full player DB, ~16MB) is gitignored — it's a fetch cache, regenerated automatically on first run of `merge_value.py`.
- K/DST scoring isn't specified by the league rules, so `vbd.py` uses standard default conventions (see comments in that file).
- Tier gap threshold in `vbd.py` was calibrated down from the literal 15%-of-range spec to 3%, since shrinkage smoothing made the raw spec produce a single degenerate tier — see comment in `assign_tiers`.
