"""Render the three Weekend Mode reports from results.json."""
import json, sys
import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scan_engine import OPERATIONALIZATIONS

R = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.json")))
WL = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchlists.json")))

RUN_STAMP = "Sunday 2026-07-19, ~23:55 SGT (completed Monday 2026-07-20 ~01:00 SGT)"
LAST_BAR = "2026-07-17 (Friday)"
SOURCE = ("Yahoo Finance daily chart API (split-adjusted, not dividend-adjusted), "
          "sole source for ALL symbols - see Section E flag on Stooq")

CONTEXT_ONLY = {"CBOE:VIX", "ICEUS:DXY", "OANDA:XAUUSD", "BITSTAMP:BTCUSD",
                "SPCFD:SPX", "NASDAQ:NDX", "NQ=F", "MANA-USD"}

def f2(x):
    return "-" if x is None else f"{x:,.2f}"

def swings_str(sw):
    if not sw:
        return "-"
    return "; ".join(f"{s['date'][5:]}@{float(s['px']):,.2f}" for s in sw)

def zone_str(d):
    z = d.get("zone")
    if not z:
        return "-"
    return f"{z['lo']:,.2f}-{z['hi']:,.2f} [{'+'.join(z['keys'])}]"

def dist_str(d):
    x = d.get("dist_atr")
    if x is None:
        return "-"
    return f"{x:+.2f}"

def cls_short(v):
    c = v.get("cls") or v["status"]
    return {"RANGE/AMBIGUOUS": "RANGE", "UPTREND": "UP", "DOWNTREND": "DOWN",
            "NO_DATA": "NO DATA", "DATA_TOO_SHORT": "SHORT DATA"}.get(c, c)

def why_str(v):
    if v.get("cls") == "UPTREND":
        return "eligible"
    w = v.get("why") or [v["status"]]
    return "; ".join(w)[:110]

def weekend_table(tvs, list_name):
    hdr = ("| Symbol | D-cls | W-cls | Close (07-17) | 50DMA (Δ5d) | ATR14 | "
           "Daily swing highs | Daily swing lows | Zone [factors] | Dist(ATR) | Failed condition / note |\n"
           "|---|---|---|---|---|---|---|---|---|---|---|\n")
    out = hdr
    for tv in tvs:
        v = R[tv]
        if v["status"] not in ("OK",):
            out += f"| {tv} | {cls_short(v)} | - | - | - | - | - | - | - | - | see Section E |\n"
            continue
        d = v["detail"]
        slope = ""
        if d.get("ma50") is not None and d.get("ma50_prev5") is not None:
            slope = f" ({d['ma50']-d['ma50_prev5']:+.2f})"
        ctx = " (context)" if tv in CONTEXT_ONLY else ""
        out += ("| {sym} | {dc} | {wc} | {c} | {ma}{sl} | {atr} | {sh} | {sl2} | {z} | {di} | {why}{ctx} |\n"
                .format(sym=tv, dc=d["daily_structure"], wc=d["weekly_structure"],
                        c=f2(d["last_close"]), ma=f2(d["ma50"]), sl=slope,
                        atr=f2(d["atr14"]), sh=swings_str(d["daily_swing_highs"]),
                        sl2=swings_str(d["daily_swing_lows"]), z=zone_str(d),
                        di=dist_str(d), why=("UPTREND - eligible" if v["cls"] == "UPTREND"
                                             else why_str(v)), ctx=ctx))
    return out

def flag_lists(tvs):
    green, orange = [], []
    for tv in tvs:
        v = R[tv]
        if v["status"] != "OK" or tv in CONTEXT_ONLY:
            continue
        if v.get("cls") == "UPTREND":
            d = v["detail"]
            if d.get("rejection") and d.get("pre2r", {}).get("passes"):
                green.append(tv)
            elif d.get("approaching"):
                orange.append(tv)
    return green, orange

def ambiguous(tvs):
    out = []
    for tv in tvs:
        v = R[tv]
        if v["status"] != "OK" or tv in CONTEXT_ONLY:
            continue
        d = v["detail"]
        A = d.get("atr14") or 0
        reasons = []
        if v["cls"] != "UPTREND":
            # one-sided structure failure with small margin
            if d["daily_structure"] == "MIXED" and len(d["daily_swing_lows"]) == 2:
                lows = [float(x["px"]) for x in d["daily_swing_lows"]]
                highs = [float(x["px"]) for x in d["daily_swing_highs"]] if len(d["daily_swing_highs"]) == 2 else None
                if highs and highs[1] > highs[0] and lows[1] < lows[0] and A and (lows[0]-lows[1]) < 0.15*A:
                    reasons.append(f"HL failed by only {lows[0]-lows[1]:.2f} ({(lows[0]-lows[1])/A:.2f} ATR)")
            if (d["daily_structure"] == "HHHL" and d["weekly_structure"] != "HHHL"
                    and d["weekly_structure"] != "LHLL"):
                reasons.append("daily HH/HL intact but weekly " + d["weekly_structure"])
            if d["weekly_structure"] == "HHHL" and d["daily_structure"] == "MIXED":
                reasons.append("weekly HH/HL intact, daily MIXED")
            pv = d.get("price_vs_ma")
            if pv is not None and A and -0.5*A <= pv < 0:
                reasons.append("price below 50DMA but inside tolerance band")
        if reasons:
            out.append((tv, "; ".join(sorted(set(reasons)))))
    return out

def sector_table():
    rows = ["AMEX:IWM", "AMEX:DIA", "AMEX:XLF", "AMEX:XLE", "NASDAQ:SOXX",
            "CBOE:VIX", "ICEUS:DXY", "OANDA:XAUUSD"]
    out = "| Symbol | Regime | 50DMA direction | Close | Note |\n|---|---|---|---|---|\n"
    for tv in rows:
        v = R[tv]
        d = v["detail"]
        dirn = "rising" if d.get("ma50_rising") else "falling/flat"
        note = "context series (not tradeable per plan)" if tv in CONTEXT_ONLY else ""
        out += f"| {tv} | {v['cls']} | {dirn} | {f2(d['last_close'])} | {note} |\n"
    return out

def regime_verdict():
    spy, qqq = R["AMEX:SPY"], R["NASDAQ:QQQ"]
    t = "## A. Market regime verdict\n\n"
    t += "**MARKET REGIME FILTER: FAILING / MIXED — plan says tighten standards or stand aside.**\n\n"
    t += (f"- SPY: **{spy['cls']}** — weekly {spy['detail']['weekly_structure']}, daily "
          f"{spy['detail']['daily_structure']} (last two daily swing lows "
          f"{swings_str(spy['detail']['daily_swing_lows'])}: HL failed by 0.52). Close "
          f"{f2(spy['detail']['last_close'])} vs rising 50DMA {f2(spy['detail']['ma50'])} — Friday 07-17 "
          f"closed below the 50DMA on the week's highest volume.\n")
    t += (f"- QQQ: **{qqq['cls']}** — weekly {qqq['detail']['weekly_structure']}, daily "
          f"{qqq['detail']['daily_structure']}; close {f2(qqq['detail']['last_close'])} is "
          f"{(qqq['detail']['ma50']-qqq['detail']['last_close']):,.2f} below its rising 50DMA "
          f"({f2(qqq['detail']['ma50'])}), beyond tolerance. Tech-led selloff (Nasdaq -1.4% Friday).\n\n"
          "Because the Layer-1 filter is not passing, nothing in any list is ranked actionable this run, "
          "regardless of individual setups (per Section 5.1).\n\n")
    t += "**Layer-2 / context table (from Swing list regime section):**\n\n" + sector_table()
    return t

def section_B(tvs, label):
    g, _ = flag_lists(tvs)
    t = "\n## B. Action candidates\n\n"
    if not g:
        t += ("**None.** No name in the " + label + " list printed a completed rejection candle at a valid "
              "confluence zone on 2026-07-17. Per the plan, an empty Category B is a normal, successful "
              "scan — no threshold was lowered to populate it. (The market regime filter is failing "
              "anyway, which would have suppressed ranking.)\n")
    else:
        for tv in g:
            d = R[tv]["detail"]; p = d["pre2r"]
            t += (f"- **{tv}** — zone {zone_str(d)}; rejection: {d['rejection']['type']} on "
                  f"{d['rejection']['bar']['date']}; entry~{f2(p['entry'])}, stop {f2(p['stop'])} "
                  f"(2xATR={f2(p['two_atr'])}), target {p['target_note']}, R={p['r_multiple'] and round(p['r_multiple'],2)}. "
                  "Next step per plan: verify on TradingView; if confirmed, set alert at the hourly "
                  "trigger — break above the most recent hourly lower high.\n")
    return t

def section_C(tvs, label, extra_earn=None):
    _, o = flag_lists(tvs)
    t = "\n## C. Evening watch (uptrend, approaching zone, no rejection candle yet)\n\n"
    if not o:
        t += "None in the " + label + " list.\n"
    for tv in o:
        d = R[tv]["detail"]
        earn = ""
        if extra_earn and tv in extra_earn:
            earn = " " + extra_earn[tv]
        t += (f"- **{tv}** — close {f2(d['last_close'])}, distance to zone {dist_str(d)} ATR "
              f"(ATR14 {f2(d['atr14'])}); zone {zone_str(d)}.{earn}\n")
    return t

def section_D(tvs):
    t = "\n## D. Ineligible summary + full Weekend Mode classification table\n\n"
    t += ("Weekend Mode (Section 8): every symbol below shows its last two confirmed daily swing "
          "highs/lows (MM-DD@price), weekly and daily class, 50DMA value and 5-day change, ATR(14), "
          "and identified zone boundaries with contributing factors "
          "(structure = higher-low area, ma50 = rising 50DMA, flip = polarity flip). "
          "Dist(ATR) is distance from close to the nearest zone boundary in ATR units "
          "(0.00 = inside zone; negative = below zone).\n\n")
    t += weekend_table(tvs, "")
    return t

def section_flags(tvs, label):
    g, o = flag_lists(tvs)
    amb = ambiguous(tvs)
    t = "\n## TradingView flag-colour suggestion (Section 8)\n\n"
    t += "- **GREEN (action candidate):** " + (", ".join(g) if g else "none") + "\n"
    t += "- **ORANGE (approaching / evening watch):** " + (", ".join(o) if o else "none") + "\n"
    t += "- **NO FLAG:** all remaining names in this list\n"
    t += "\n**Deserves manual review on TradingView (ambiguous mechanical call):**\n\n"
    if not amb:
        t += "None.\n"
    for tv, why in amb:
        t += f"- {tv}: {why}\n"
    return t

E_COMMON = """
## E. Data quality & verification flags

**Source deviation (protocol Section 3.1).** Stooq (named primary) was unreachable from both this
sandbox (network policy) and the Colab fetch environment (blocked cloud IPs). Yahoo Finance chart API
(the named fallback) was therefore the SOLE source for all 219 retrieved symbols - consistent within
the run, no per-symbol mixing. Yahoo chart data is split-adjusted but NOT dividend-adjusted; long-lookback
levels on high-yield names sit slightly higher than dividend-adjusted charts.

**Verified live vs carried forward (Section 7.1).** Cross-checked to the cent against stockanalysis.com:
SPY (last 5 daily bars), NVDA (last 3), AMD (last 3) - all OHLC values match exactly; volumes differ
<0.2% (vendor revisions). Friday's tape shape independently corroborated (S&P -1.0%, Nasdaq -1.4%,
NFLX -7% on guidance). ALL OTHER SYMBOLS are single-source Yahoo, sanity-checked programmatically
(date continuity, OHLC consistency, volume) but not independently price-verified. The earnings dates for
AMD and GS were verified live via the Alpha Vantage earnings calendar; no other earnings dates were checked
(none required - Category B empty).

**Retrieval failures (never silently skipped):**
- NASDAQ:HONA - Honeywell Aerospace, only began trading on Nasdaq in June 2026 (spin-off); ~20 bars exist,
  below the fetch script's 30-bar floor and far below the plan's 300-bar minimum. Cannot be scanned
  mechanically; watch manually on TradingView.
- CFI:CVAC - no data from either source; CureVac was subject to acquisition by BioNTech - listing likely
  terminated. Recommend removing or re-pointing this row.
- ERUS, JJC - delisted instruments (Russia ETF; copper ETN); permanent failures.
- NASDAQ:SPCX - no data; likely delisted ETF. Recommend review.

**Short / degraded series (classified where possible, below the 300-bar standard):**
- NYSE:VGNT 77 bars (recent listing) - weekly structure INSUFFICIENT by construction.
- NYSE:CRCL 280 bars (June-2025 IPO) - marginally short; 50DMA/ATR stable, weekly swings thin.
- OTC:RGAKF 111 bars + a 146-day quote gap - OTC illiquidity; treat classification as unreliable.
- QSE:MFMS 147 bars; last bar 2026-07-16 because Qatar has no Friday session (benign).
- SSE:688755 286 bars.
- MIL:BF-B - 499/500 zero-volume bars; instrument mapping ambiguous in the TradingView export.
  Data unusable. Please confirm what this row is meant to be.

**Mechanical-integrity notes (classification proceeded; affected bars are historical):**
- Small counts of OHLC-inconsistent bars (high/low vs open/close rounding) in HKEX:1477 (12),
  HKEX:2801 (9), HKEX:3067 (1), HKEX:3088 (23), LSE:ASC (4), LSE:DEBS (3), LSE:SVT (2),
  SZSE:300601 (1), TPEX:00845B (1), OANDA:XAUUSD (1) - typical vendor artifacts on non-US series.
- China A-share series show an 11-12 day gap in Feb 2026 - Lunar New Year closure (benign).
- BITSTAMP:BTCUSD and MANA-USD: partial Sunday bar (2026-07-19) trimmed to honour the
  completed-bars-only rule; Saturday 07-18 is their true last completed bar (24/7 assets).
- LSE:BRK-A / LSE:BRK-B rows were mapped to the US Berkshire listings (assumption; the TV export's
  LSE prefix appears to be an artifact).
- BGNE retrieved under its current Nasdaq ticker lineage (BeiGene renamed BeOne Medicines/ONC in 2025;
  the BGNE symbol still resolved on Yahoo).

**Definitions applied with judgment rather than mechanically (per Section 7.3 these are proposals,
NOT changes; they take effect only if you ratify them in writing):**
""" + "".join(f"- {x}\n" for x in OPERATIONALIZATIONS) + """
**Base-rate sanity check.** 9 uptrends / 219 classified (4%) vs the plan's expected 10-15 of 36 (28-42%)
in normal weeks. This is a regime effect, not a threshold artifact: the scan week ended with a tech-led
selloff and both Layer-1 ETFs out of UPTREND. Empty Category B is the expected outcome in this tape.

**Differences from last run:** first run under these standing instructions; nothing carried forward
(Section 7.5 - all values computed fresh from raw bars this run).
"""

def header(title, list_label, n):
    return (f"# {title}\n\n"
            f"**Run:** {RUN_STAMP} · **Mode: WEEKEND** (Section 8) · **List:** {list_label} ({n} symbols)\n\n"
            f"**Data source:** {SOURCE}\n\n"
            f"**Last completed daily bar (SPY):** {LAST_BAR}. All analysis uses completed daily bars only.\n\n"
            f"**Standing instructions:** Cowork_Watchlist_Scan_Prompt_v1.md (v1.0). Watchlist versions: "
            f"as uploaded 2026-07-19 (3 TradingView export files).\n\n---\n\n")

def build(list_key, title, label, earn=None):
    tvs = [e["tv"] for e in WL[list_key]]
    # preserve original watchlist order, dedupe
    seen = set(); ordered = []
    for tv in tvs:
        if tv not in seen:
            seen.add(tv); ordered.append(tv)
    t = header(title, label, len(ordered))
    t += regime_verdict()
    t += section_B(ordered, label)
    t += section_C(ordered, label, extra_earn=earn)
    t += section_D(ordered)
    t += section_flags(ordered, label)
    t += E_COMMON
    return t

earn_notes = {
    "NASDAQ:AMD": "Next earnings **2026-08-04 post-market** (Alpha Vantage earnings calendar, verified live) - outside the 5-trading-day exclusion.",
    "NYSE:GS": "Next earnings **2026-10-13** (Alpha Vantage earnings calendar, verified live) - Q2 already reported; no conflict.",
}

swing = build("swing", "Watchlist Scan 2026-07-19 — SWING TRADER list", "Swing Trader", earn=earn_notes)
inv = build("investor", "Watchlist Scan 2026-07-19 — INVESTOR list", "Investor", earn=earn_notes)
exc = build("excluded", "Watchlist Scan 2026-07-19 — EXCLUDED list (informational only)", "Excluded", earn=earn_notes)
exc = exc.replace("## B. Action candidates\n\n**None.**",
                  "## B. Action candidates (informational only — these names are excluded by your own rulings)\n\n**None.**")

open("Watchlist_Scan_2026-07-19_Swing.md", "w").write(swing)
open("Watchlist_Scan_2026-07-19_Investor.md", "w").write(inv)
open("Watchlist_Scan_2026-07-19_Excluded.md", "w").write(exc)
print("written:",
      len(swing.splitlines()), "/", len(inv.splitlines()), "/", len(exc.splitlines()), "lines")
