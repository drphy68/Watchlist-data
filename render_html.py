"""Render visual HTML dashboards from results.json — companion to render_reports.py.

Emits one self-contained HTML file per list (no external assets; works offline,
mobile-first, dark-mode aware). The .md reports remain the machine-readable
archive; these are the human-readable view.

Pipeline: run after render_reports.py. Reads the same results.json/watchlists.json.
Outputs: Watchlist_Scan_<LAST_BAR_DATE>_<List>.html
"""
import json, html, os, sys

SCAN_DIR = os.environ.get("SCAN_DIR", "/home/claude/scan")
OUT_DIR = os.environ.get("HTML_OUT_DIR", SCAN_DIR)

# ---- EDIT PER RUN (mirrors render_reports.py; kept identical to its constants this run) ----
RUN_STAMP = "Sunday 2026-07-19, ~23:55 SGT (completed Monday 2026-07-20 ~01:00 SGT)"
LAST_BAR = "2026-07-17 (Friday)"
LAST_BAR_DATE = "2026-07-17"       # used in filenames
SOURCE_SHORT = "Yahoo Finance daily (split-adj.)"
SPEC_VER = "v1.2"
VOLUME_RUN_NO, VOLUME_RUN_TOTAL = 1, 10
DEMO_BANNER = ""                   # non-empty string renders a demo notice bar; MUST be "" in production

R = json.load(open(f"{SCAN_DIR}/results.json"))
WL = json.load(open(f"{SCAN_DIR}/watchlists.json"))

CONTEXT_ONLY = {"CBOE:VIX", "ICEUS:DXY", "OANDA:XAUUSD", "BITSTAMP:BTCUSD",
                "SPCFD:SPX", "NASDAQ:NDX", "NQ=F", "MANA-USD"}

E = html.escape
EMDASH = "\u2014"
def f2(x): return EMDASH if x is None else f"{x:,.2f}"

def cls_key(v):
    c = v.get("cls") or v.get("status")
    return {"UPTREND": "up", "RANGE/AMBIGUOUS": "rng", "DOWNTREND": "dn"}.get(c, "nd")

def cls_label(v):
    c = v.get("cls") or v.get("status")
    return {"UPTREND": "UPTREND", "RANGE/AMBIGUOUS": "RANGE", "DOWNTREND": "DOWNTREND",
            "NO_DATA": "NO DATA", "DATA_TOO_SHORT": "SHORT DATA"}.get(c, c)

def chip(text, key):  # key: up/rng/dn/nd/z (zone factor)/v (volume)
    return f'<span class="chip {key}">{E(str(text))}</span>'

def struct_chip(s):
    key = {"HHHL": "up", "MIXED": "rng", "LHLL": "dn"}.get(s, "nd")
    return chip(s, key)

def vol_of(v): return (v.get("detail") or {}).get("volume") or {}

def v3_chip(v):
    v3 = vol_of(v).get("v3")
    if not v3: return chip("OBV \u2014", "nd")
    key = {"ACCUM": "up", "NEUTRAL": "nd", "DIVERGENCE-WARNING": "dn"}[v3["tag"]]
    return chip("OBV " + v3["tag"], key)

def v1_chip(v):
    v1 = vol_of(v).get("v1")
    if not v1: return chip("pullback \u2014", "nd")
    if v1.get("status") == "leg too short":
        return chip(f"pullback: leg too short ({v1['n_bars']}b)", "nd")
    if v1["status"] == "quiet":
        mr = v1.get("mean_rvol")
        return chip("pullback quiet" + (f" ({mr:.2f}\u00d7)" if mr else ""), "up")
    return chip("distribution-pattern", "dn")

def v2_chip(v):
    v2 = vol_of(v).get("v2")
    if not v2 or v2.get("rvol") is None: return chip("rejection vol \u2014", "nd")
    key = {"CONFIRMED": "up", "UNCONFIRMED": "rng", "SUSPECT": "dn"}.get(v2.get("verdict"), "nd")
    t = f"rejection {v2['rvol']:.2f}\u00d7 {v2.get('verdict','')}"
    if v2.get("half_day"): t += " (half-day)"
    return chip(t, key)

def zone_chips(d):
    z = d.get("zone")
    if not z: return chip("no zone", "nd")
    names = {"structure": "structure", "ma50": "50DMA", "flip": "polarity flip"}
    return "".join(chip(names.get(k, k), "z") for k in z["keys"])

def zone_bar(d):
    """Visual: where the close sits relative to the zone (track = zone ±1 ATR)."""
    z, c, a = d.get("zone"), d.get("last_close"), d.get("atr14")
    if not z or c is None or not a: return ""
    lo, hi = z["lo"] - a, z["hi"] + a
    span = hi - lo
    zl, zw = (z["lo"] - lo) / span * 100, (z["hi"] - z["lo"]) / span * 100
    cp = min(max((c - lo) / span * 100, 0), 100)
    return (f'<div class="zbar"><div class="zone" style="left:{zl:.1f}%;width:{zw:.1f}%"></div>'
            f'<div class="mark" style="left:{cp:.1f}%"></div></div>'
            f'<div class="zlbl"><span>{f2(z["lo"])}</span><span>zone</span><span>{f2(z["hi"])}</span></div>')

def swings(sw):
    if not sw: return "\u2014"
    return "; ".join(f"{s['date'][5:]}@{float(s['px']):,.2f}" for s in sw)

def tvs_for(list_key):
    return [row["tv"] for row in WL[list_key]]

def counts(tvs):
    # "flags" MUST match the pipeline's one authoritative definition of flagged/failed
    # (run_scan.py console summary: status != OK OR non-empty integrity_flags) -- an
    # earlier version of this function only counted hard status failures (NO_DATA /
    # DATA_TOO_SHORT), silently dropping OK-status-but-integrity-flagged symbols (e.g.
    # OHLC-inconsistent bars). That undercounted flags 1 vs 3 (Swing) and 4 vs 24
    # (Excluded) against the same-run reference count -- caught by Task B's
    # reconciliation check, fixed here.
    up = appr = act = flags = 0
    for tv in tvs:
        v = R.get(tv)
        if not v: continue
        if v.get("status") != "OK" or v.get("integrity_flags"):
            flags += 1
        if v.get("status") != "OK": continue
        if tv in CONTEXT_ONLY: continue
        if v.get("cls") == "UPTREND":
            up += 1
            d = v["detail"]
            if d.get("rejection") and d.get("pre2r", {}).get("passes"): act += 1
            elif d.get("approaching"): appr += 1
    return up, appr, act, flags

def regime_state():
    ok = all(R.get(t, {}).get("cls") == "UPTREND" for t in ("AMEX:SPY", "NASDAQ:QQQ"))
    return ("pass", "MARKET REGIME: PASSING \u2014 setups may rank actionable") if ok else \
           ("fail", "MARKET REGIME: FAILING / MIXED \u2014 tighten standards or stand aside (\u00a75.1)")

def index_card(tv, name):
    v = R.get(tv)
    if not v or v.get("status") != "OK":
        return f'<div class="card"><div class="cardhead"><b>{E(name)}</b>{chip("NO DATA","nd")}</div></div>'
    d = v["detail"]
    below = d.get("price_vs_ma")
    ma_line = f"50DMA {f2(d.get('ma50'))} ({'rising' if d.get('ma50_rising') else 'falling/flat'})"
    return (f'<div class="card"><div class="cardhead"><b>{E(name)}</b>{chip(cls_label(v), cls_key(v))}</div>'
            f'<div class="krow">weekly {struct_chip(d["weekly_structure"])} daily {struct_chip(d["daily_structure"])}</div>'
            f'<div class="meta">close <b>{f2(d.get("last_close"))}</b> \u00b7 {E(ma_line)}'
            + (f' \u00b7 {below:+.2f} vs MA' if below is not None else '') + '</div></div>')

def watch_card(tv):
    v = R[tv]; d = v["detail"]
    dist = d.get("dist_atr")
    dist_s = "inside zone" if dist == 0 else (f"{dist:+.2f} ATR to zone" if dist is not None else "\u2014")
    return (f'<div class="card"><div class="cardhead"><b>{E(tv)}</b><span class="dist">{E(dist_s)}</span></div>'
            f'{zone_bar(d)}'
            f'<div class="krow">{zone_chips(d)}</div>'
            f'<div class="krow">{v1_chip(v)}{v3_chip(v)}</div>'
            f'<div class="meta">close {f2(d.get("last_close"))} \u00b7 ATR14 {f2(d.get("atr14"))}</div></div>')

def action_card(tv):
    v = R[tv]; d = v["detail"]; p = d.get("pre2r") or {}
    rej = d.get("rejection") or {}
    r = p.get("r_multiple")
    target_note = str(p.get("target_note") or EMDASH)  # extracted: backslash escapes are illegal
    bar_date = (rej.get("bar") or {}).get("date", "?")   # inside an f-string {} expr pre-3.12
    return (f'<div class="card act"><div class="cardhead"><b>{E(tv)}</b>'
            f'<span class="rmult">{("R %.2f" % r) if r else ""}</span></div>'
            f'{zone_bar(d)}'
            f'<div class="krow">{zone_chips(d)}</div>'
            f'<div class="meta">rejection: <b>{E(rej.get("type","?"))}</b> on {E(bar_date)}</div>'
            f'<div class="meta">entry~{f2(p.get("entry"))} \u00b7 stop {f2(p.get("stop"))} '
            f'(2\u00d7ATR {f2(p.get("two_atr"))}) \u00b7 target: {E(target_note)}</div>'
            f'<div class="krow">{v2_chip(v)}{v1_chip(v)}{v3_chip(v)}</div>'
            f'<div class="next">Next per plan: verify on TradingView; if confirmed, set alert at the hourly trigger '
            f'(break above most recent hourly lower high). Not a recommendation.</div></div>')

def d_row(tv):
    v = R.get(tv)
    if not v: return ""
    k = cls_key(v)
    if v.get("status") != "OK":
        return (f'<details class="drow" data-cls="nd"><summary><span class="sym">{E(tv)}</span>'
                f'{chip(cls_label(v), "nd")}<span class="why">see flags</span></summary></details>')
    d = v["detail"]
    ctx = " (context)" if tv in CONTEXT_ONLY else ""
    why = "eligible" if v.get("cls") == "UPTREND" else "; ".join(v.get("why") or [])
    slope = (d.get("ma50") or 0) - (d.get("ma50_prev5") or 0) if d.get("ma50") is not None and d.get("ma50_prev5") is not None else None
    return (f'<details class="drow" data-cls="{k}"><summary>'
            f'<span class="sym">{E(tv)}</span>{chip(cls_label(v), k)}'
            f'<span class="close">{f2(d.get("last_close"))}</span>'
            f'<span class="why">{E((why + ctx)[:80])}</span></summary>'
            f'<div class="dbody">'
            f'<div class="krow">weekly {struct_chip(d["weekly_structure"])} daily {struct_chip(d["daily_structure"])} {v3_chip(v)}</div>'
            f'<div class="meta">50DMA {f2(d.get("ma50"))}' + (f' ({slope:+.2f}/5d)' if slope is not None else '') +
            f' \u00b7 ATR14 {f2(d.get("atr14"))} \u00b7 AvgVol50 {f2(vol_of(v).get("avgvol50"))}</div>'
            f'<div class="meta">swing highs: {E(swings(d.get("daily_swing_highs")))}</div>'
            f'<div class="meta">swing lows: {E(swings(d.get("daily_swing_lows")))}</div>'
            + (f'<div class="krow">{zone_chips(d)}</div>{zone_bar(d)}' if d.get("zone") else '')
            + f'</div></details>')

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#1a2233;--mut:#5b6472;--line:#e3e7ee;
--up:#127a3f;--upbg:#e2f5e9;--rng:#9a5b00;--rngbg:#fdf0da;--dn:#b91f24;--dnbg:#fbe4e4;
--nd:#5b6472;--ndbg:#eceff3;--z:#2b4d9b;--zbg:#e5ecfb;--acc:#2b4d9b}
@media(prefers-color-scheme:dark){:root{--bg:#12161d;--card:#1a2029;--ink:#e8ecf2;--mut:#9aa4b2;
--line:#2a3340;--upbg:#123322;--rngbg:#3a2c10;--dnbg:#3a1a1a;--ndbg:#232b36;--zbg:#1b2a4a;
--up:#4cc38a;--rng:#e0a94e;--dn:#e5787f;--z:#8fb0f5}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;padding-bottom:40px}
.wrap{max-width:900px;margin:0 auto;padding:0 12px}
.banner{padding:12px 16px;font-weight:700;color:#fff;position:sticky;top:0;z-index:5}
.banner.fail{background:#a33b12}.banner.pass{background:#127a3f}
.demo{background:#5b21b6;color:#fff;padding:6px 16px;font-size:13px}
h1{font-size:20px;margin:14px 0 2px}h2{font-size:16px;margin:22px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}
.runmeta{color:var(--mut);font-size:13px;margin-bottom:10px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(105px,1fr));gap:8px;margin:12px 0}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px;text-align:center}
.stat b{display:block;font-size:22px}.stat span{font-size:12px;color:var(--mut)}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px}
.card.act{border:2px solid var(--up)}
.cardhead{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:6px}
.chip{display:inline-block;font-size:11.5px;font-weight:600;padding:2px 8px;border-radius:99px;margin:1px 3px 1px 0;white-space:nowrap}
.chip.up{background:var(--upbg);color:var(--up)}.chip.rng{background:var(--rngbg);color:var(--rng)}
.chip.dn{background:var(--dnbg);color:var(--dn)}.chip.nd{background:var(--ndbg);color:var(--nd)}
.chip.z{background:var(--zbg);color:var(--z)}
.krow{margin:4px 0}.meta{color:var(--mut);font-size:13px;margin:2px 0}
.dist{font-size:12.5px;font-weight:600;color:var(--acc)}.rmult{font-weight:700;color:var(--up)}
.next{font-size:12.5px;color:var(--mut);border-top:1px dashed var(--line);margin-top:8px;padding-top:6px}
.zbar{position:relative;height:10px;background:var(--ndbg);border-radius:6px;margin:8px 0 2px;overflow:hidden}
.zbar .zone{position:absolute;top:0;bottom:0;background:var(--zbg);border-left:1px solid var(--z);border-right:1px solid var(--z)}
.zbar .mark{position:absolute;top:-2px;bottom:-2px;width:3px;background:var(--ink);border-radius:2px}
.zlbl{display:flex;justify-content:space-between;font-size:11px;color:var(--mut)}
.callout{background:var(--card);border:1px dashed var(--line);border-radius:12px;padding:12px;color:var(--mut)}
.filters{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}
.filters button{border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:99px;padding:4px 12px;font-size:13px;cursor:pointer}
.filters button.on{background:var(--acc);border-color:var(--acc);color:#fff}
.drow{background:var(--card);border:1px solid var(--line);border-radius:10px;margin:5px 0;padding:0}
.drow summary{display:flex;align-items:center;gap:8px;padding:9px 12px;cursor:pointer;list-style:none}
.drow summary::-webkit-details-marker{display:none}
.sym{font-weight:700;min-width:110px}.close{margin-left:auto;font-variant-numeric:tabular-nums}
.why{color:var(--mut);font-size:12px;flex-basis:100%;order:9}
.dbody{padding:2px 12px 10px;border-top:1px solid var(--line)}
details.sect summary{font-size:16px;font-weight:700;margin:22px 0 8px;cursor:pointer}
pre{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px;font-size:12px;overflow-x:auto;white-space:pre-wrap}
"""

JS = """
function flt(k,btn){document.querySelectorAll('.filters button').forEach(b=>b.classList.remove('on'));
btn.classList.add('on');document.querySelectorAll('.drow').forEach(r=>{
r.style.display=(k==='all'||r.dataset.cls===k)?'':'none';});}
"""

def build(list_key, title):
    tvs = tvs_for(list_key)
    up, appr, act, flags = counts(tvs)
    rkey, rtext = regime_state()
    watch = [t for t in tvs if R.get(t, {}).get("status") == "OK" and t not in CONTEXT_ONLY
             and R[t].get("cls") == "UPTREND" and R[t]["detail"].get("approaching")
             and not (R[t]["detail"].get("rejection") and R[t]["detail"].get("pre2r", {}).get("passes"))]
    acts = [t for t in tvs if R.get(t, {}).get("status") == "OK" and t not in CONTEXT_ONLY
            and R[t].get("cls") == "UPTREND" and R[t]["detail"].get("rejection")
            and R[t]["detail"].get("pre2r", {}).get("passes")]
    sect2 = [t for t in tvs if t in ("AMEX:IWM", "AMEX:DIA", "AMEX:XLF", "AMEX:XLE", "NASDAQ:SOXX")
             or t in CONTEXT_ONLY]
    o = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width,initial-scale=1">',
         f'<title>Scan {E(LAST_BAR_DATE)} \u2014 {E(title)}</title><style>{CSS}</style></head><body>']
    if DEMO_BANNER:
        o.append(f'<div class="demo">{E(DEMO_BANNER)}</div>')
    o.append(f'<div class="banner {rkey}">{E(rtext)}</div><div class="wrap">')
    o.append(f'<h1>Watchlist Scan \u2014 {E(title)}</h1>'
             f'<div class="runmeta">{E(RUN_STAMP)} \u00b7 last bar {E(LAST_BAR)} \u00b7 {E(SOURCE_SHORT)} '
             f'\u00b7 spec {E(SPEC_VER)} \u00b7 volume module report-only run {VOLUME_RUN_NO}/{VOLUME_RUN_TOTAL}</div>')
    o.append('<div class="stats">'
             f'<div class="stat"><b>{up}</b><span>uptrends</span></div>'
             f'<div class="stat"><b>{appr}</b><span>approaching</span></div>'
             f'<div class="stat"><b>{act}</b><span>action candidates</span></div>'
             f'<div class="stat"><b>{flags}</b><span>data flags</span></div></div>')
    o.append('<h2>A \u00b7 Market regime</h2><div class="cards">')
    o.append(index_card("AMEX:SPY", "SPY")); o.append(index_card("NASDAQ:QQQ", "QQQ"))
    o.append('</div><div class="krow" style="margin-top:8px">')
    for t in sect2:
        v = R.get(t)
        if v and v.get("status") == "OK":
            o.append(chip(f"{t.split(':')[-1]} {cls_label(v)}", cls_key(v)))  # [-1]: some
            # context tickers (NQ=F, MANA-USD) have no ':' — [1] crashed on the Excluded list
    o.append('</div>')
    o.append('<h2>B \u00b7 Action candidates</h2>')
    if acts:
        o.append('<div class="cards">' + "".join(action_card(t) for t in acts) + '</div>')
    else:
        o.append('<div class="callout">None this run \u2014 a normal, successful outcome. '
                 'No threshold is lowered to populate this section.</div>')
    o.append('<h2>C \u00b7 Evening watch</h2>')
    if watch:
        o.append('<div class="cards">' + "".join(watch_card(t) for t in watch) + '</div>')
    else:
        o.append('<div class="callout">No uptrend names approaching zones.</div>')
    o.append('<h2>D \u00b7 All symbols</h2>'
             '<div class="filters">'
             '<button class="on" onclick="flt(\'all\',this)">All</button>'
             '<button onclick="flt(\'up\',this)">Uptrend</button>'
             '<button onclick="flt(\'rng\',this)">Range</button>'
             '<button onclick="flt(\'dn\',this)">Downtrend</button>'
             '<button onclick="flt(\'nd\',this)">No data</button></div>')
    o.append("".join(d_row(t) for t in tvs))
    o.append('<details class="sect"><summary>E \u00b7 Data quality &amp; verification flags</summary>'
             '<pre>See the .md report of the same date for the full Section E narrative \u2014 '
             'the archive of record. Symbols with retrieval failures appear above as NO DATA.</pre></details>')
    o.append(f'<script>{JS}</script></div></body></html>')
    fn = f"{OUT_DIR}/Watchlist_Scan_{LAST_BAR_DATE}_{title.replace(' ', '_')}.html"
    open(fn, "w").write("".join(o))
    return fn

if __name__ == "__main__":
    for k, t in (("swing", "Swing"), ("investor", "Investor"), ("excluded", "Excluded")):
        if k in WL:
            print("wrote", build(k, t))
