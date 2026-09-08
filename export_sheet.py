"""Combine cheat_sheet.csv + k_dst_simple.csv into a clean, tiered, printable
draft-day view: draft_cheat_sheet.csv and draft_cheat_sheet.html."""
import html
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"

RISKY_STATUSES = {"Out", "IR", "PUP"}


def status_flag(active, injury_status) -> str:
    if active is False:
        return "INACTIVE"
    if isinstance(injury_status, str) and injury_status in RISKY_STATUSES:
        return injury_status.upper()
    if isinstance(injury_status, str) and injury_status not in ("", "nan"):
        return injury_status
    return ""


def build_csv(cheat_sheet: pd.DataFrame, k_dst: pd.DataFrame) -> pd.DataFrame:
    modeled = cheat_sheet[cheat_sheet["valuation_basis"] == "VBD"].copy()
    modeled = modeled.sort_values(["tier", "vbd_rank"])

    thin = cheat_sheet[cheat_sheet["valuation_basis"] != "VBD"].copy()
    thin = thin.sort_values("adp_rank", na_position="last")

    k_dst = k_dst.copy()
    k_dst["tier"] = pd.NA
    k_dst["vbd_rank"] = pd.NA
    k_dst["adp_rank"] = pd.NA
    k_dst["value_gap"] = pd.NA
    k_dst["sleeper_flag"] = False
    k_dst["overvalued"] = False
    k_dst["valuation_basis"] = "K/DST simple (2025 raw points)"
    k_dst["active"] = pd.NA
    k_dst["injury_status"] = pd.NA
    k_dst = k_dst.rename(columns={"total_points": "shrunk_ppg"})

    cols = ["tier", "vbd_rank", "adp_rank", "value_gap", "sleeper_flag", "overvalued",
            "valuation_basis", "name", "position", "team", "shrunk_ppg", "active", "injury_status"]
    for df in (modeled, thin, k_dst):
        for c in cols:
            if c not in df.columns:
                df[c] = pd.NA

    combined = pd.concat([modeled[cols], thin[cols], k_dst[cols]], ignore_index=True)
    return combined


def render_html(cheat_sheet: pd.DataFrame, k_dst_ranked: pd.DataFrame, generated_at: str) -> str:
    modeled = cheat_sheet[cheat_sheet["valuation_basis"] == "VBD"].copy()
    modeled = modeled.sort_values(["tier", "vbd_rank"])
    thin = cheat_sheet[cheat_sheet["valuation_basis"] != "VBD"].copy()
    thin = thin.sort_values("adp_rank", na_position="last").head(40)

    def esc(v) -> str:
        return html.escape(str(v)) if pd.notna(v) else ""

    def player_row(row) -> str:
        sleeper = bool(row.get("sleeper_flag"))
        overvalued = bool(row.get("overvalued"))
        risk = status_flag(row.get("active"), row.get("injury_status"))
        row_class = "sleeper" if sleeper else ("overvalued" if overvalued else "")
        badges = []
        if sleeper:
            badges.append('<span class="badge sleeper-badge">SLEEPER</span>')
        if overvalued:
            badges.append('<span class="badge overvalued-badge">OVERVALUED</span>')
        if risk:
            badges.append(f'<span class="badge risk-badge">{esc(risk)}</span>')
        gap = row.get("value_gap")
        gap_str = f"{gap:+.0f}" if pd.notna(gap) else "-"
        adp = row.get("adp_rank")
        adp_str = f"{adp:.0f}" if pd.notna(adp) else "-"
        ppg = row.get("shrunk_ppg")
        ppg_str = f"{ppg:.1f}" if pd.notna(ppg) else "-"
        vbd_rank = row.get("vbd_rank")
        vbd_rank_str = f"{vbd_rank:.0f}" if pd.notna(vbd_rank) else "-"
        return f"""<tr class="{row_class}">
          <td class="rank">{vbd_rank_str}</td>
          <td class="name">{esc(row['name'])} {''.join(badges)}</td>
          <td class="pos pos-{esc(row['position'])}">{esc(row['position'])}</td>
          <td class="team">{esc(row['team'])}</td>
          <td class="num">{ppg_str}</td>
          <td class="num">{adp_str}</td>
          <td class="num">{gap_str}</td>
        </tr>"""

    tier_sections = []
    for tier, grp in modeled.groupby("tier"):
        rows = "\n".join(player_row(r) for _, r in grp.iterrows())
        tier_sections.append(f"""
        <section class="tier">
          <h2>Tier {int(tier)}</h2>
          <table>
            <thead><tr><th>#</th><th>Player</th><th>Pos</th><th>Team</th><th>PPG</th><th>ADP</th><th>Gap</th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </section>""")

    thin_rows = "\n".join(f"""<tr>
        <td class="name">{esc(r['name'])}</td>
        <td class="pos pos-{esc(r['position'])}">{esc(r['position'])}</td>
        <td class="team">{esc(r['team'])}</td>
        <td class="num">{f"{r['adp_rank']:.0f}" if pd.notna(r['adp_rank']) else '-'}</td>
      </tr>""" for _, r in thin.iterrows())

    k_rows = "\n".join(f"""<tr>
        <td class="rank">{int(r['rank'])}</td>
        <td class="name">{esc(r['name'])}</td>
        <td class="num">{r['total_points']:.0f}</td>
      </tr>""" for _, r in k_dst_ranked[k_dst_ranked["position"] == "K"].iterrows())
    dst_rows = "\n".join(f"""<tr>
        <td class="rank">{int(r['rank'])}</td>
        <td class="name">{esc(r['name'])}</td>
        <td class="num">{r['total_points']:.0f}</td>
      </tr>""" for _, r in k_dst_ranked[k_dst_ranked["position"] == "DST"].iterrows())

    return f"""<title>2026 Draft Cheat Sheet</title>
<style>
:root {{
  --bg: #f7f5f0; --panel: #ffffff; --text: #1c1b19; --muted: #6b6459;
  --border: #e4dfd4; --accent: #b5471b; --sleeper: #1c6e4a; --sleeper-bg: #e4f3ec;
  --overvalued: #a3341f; --overvalued-bg: #fbeae6; --risk: #b8860b; --risk-bg: #fdf3d8;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --bg: #17140f; --panel: #211d17; --text: #f1ece1; --muted: #a89c88;
    --border: #3a3327; --accent: #e0824a; --sleeper: #6fd1a0; --sleeper-bg: #16302392;
    --overvalued: #e79184; --overvalued-bg: #3a1712; --risk: #e8c468; --risk-bg: #3a2e0f;
  }}
}}
:root[data-theme="dark"] {{
  --bg: #17140f; --panel: #211d17; --text: #f1ece1; --muted: #a89c88;
  --border: #3a3327; --accent: #e0824a; --sleeper: #6fd1a0; --sleeper-bg: #16302392;
  --overvalued: #e79184; --overvalued-bg: #3a1712; --risk: #e8c468; --risk-bg: #3a2e0f;
}}
body {{ background: var(--bg); color: var(--text); font-family: -apple-system, Segoe UI, Roboto, sans-serif; padding: 24px 32px 80px; }}
h1 {{ font-size: 22px; margin: 0 0 4px; }}
.subtitle {{ color: var(--muted); font-size: 13px; margin-bottom: 20px; }}
.legend {{ display: flex; gap: 16px; margin-bottom: 20px; font-size: 12px; color: var(--muted); flex-wrap: wrap; }}
.legend span {{ display: inline-flex; align-items: center; gap: 6px; }}
.dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
section.tier {{ background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 14px 18px; margin-bottom: 16px; }}
h2 {{ font-size: 15px; margin: 0 0 8px; color: var(--accent); }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th {{ text-align: left; color: var(--muted); font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: .04em; padding: 4px 8px; border-bottom: 1px solid var(--border); }}
td {{ padding: 5px 8px; border-bottom: 1px solid var(--border); }}
td.num, td.rank {{ text-align: right; font-variant-numeric: tabular-nums; color: var(--muted); }}
td.name {{ font-weight: 500; }}
tr.sleeper {{ background: var(--sleeper-bg); }}
tr.overvalued {{ background: var(--overvalued-bg); }}
.badge {{ font-size: 9px; font-weight: 700; padding: 1px 6px; border-radius: 8px; margin-left: 6px; letter-spacing: .03em; vertical-align: middle; }}
.sleeper-badge {{ background: var(--sleeper); color: #04140c; }}
.overvalued-badge {{ background: var(--overvalued); color: #2a0a04; }}
.risk-badge {{ background: var(--risk); color: #2a1c00; }}
.pos {{ font-size: 11px; font-weight: 700; color: var(--muted); }}
.bottom-grid {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; margin-top: 24px; }}
.bottom-grid section.tier {{ margin-bottom: 0; }}
@media print {{ body {{ padding: 8px; }} section.tier {{ break-inside: avoid; }} }}
@media (max-width: 700px) {{ .bottom-grid {{ grid-template-columns: 1fr; }} }}
</style>
<h1>2026 Draft Cheat Sheet</h1>
<div class="subtitle" style="font-weight:700;color:var(--accent)">GENERATED {esc(generated_at)} &mdash; if this doesn't match your last pipeline run, hard-refresh (Ctrl+Shift+R) before trusting anything below</div>
<div class="subtitle">10-team PPR &middot; QB/RB/WR/TE tiered by VBD, sleepers flagged vs. ADP, rookies/thin-data ranked by ADP, K/DST by 2025 raw points</div>
<div class="legend">
  <span><span class="dot" style="background:var(--sleeper)"></span>Sleeper (ADP rank &gt; VBD rank by 15+)</span>
  <span><span class="dot" style="background:var(--overvalued)"></span>Overvalued (VBD rank &gt; ADP rank by 15+)</span>
  <span><span class="badge risk-badge">STATUS</span>Inactive / Out / IR / PUP &mdash; verify before drafting</span>
</div>
{''.join(tier_sections)}
<div class="bottom-grid">
  <section class="tier">
    <h2>Rookies / Thin Data (ADP-only)</h2>
    <table><thead><tr><th>Player</th><th>Pos</th><th>Team</th><th>ADP</th></tr></thead><tbody>{thin_rows}</tbody></table>
  </section>
  <section class="tier">
    <h2>Kickers (2025 raw pts)</h2>
    <table><thead><tr><th>#</th><th>Team</th><th>Pts</th></tr></thead><tbody>{k_rows}</tbody></table>
  </section>
  <section class="tier">
    <h2>DST (2025 raw pts)</h2>
    <table><thead><tr><th>#</th><th>Team</th><th>Pts</th></tr></thead><tbody>{dst_rows}</tbody></table>
  </section>
</div>
"""


def main() -> None:
    cheat_sheet = pd.read_csv(ROOT / "cheat_sheet.csv")
    k_dst = pd.read_csv(DATA_DIR / "k_dst_simple.csv")

    combined = build_csv(cheat_sheet, k_dst)
    csv_path = ROOT / "draft_cheat_sheet.csv"
    combined.to_csv(csv_path, index=False)
    print(f"Saved {len(combined)} rows to {csv_path}")

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    html_str = render_html(cheat_sheet, k_dst, generated_at)
    html_path = ROOT / "draft_cheat_sheet.html"
    html_path.write_text(html_str, encoding="utf-8")
    print(f"Saved printable sheet to {html_path}")


if __name__ == "__main__":
    main()
