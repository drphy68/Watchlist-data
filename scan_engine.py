"""
Mechanical scan engine implementing Section 4 of the standing instructions
(Cowork_Watchlist_Scan_Prompt_v1.md) exactly, with every operationalization
of an unquantified phrase recorded in OPERATIONALIZATIONS for Section E.

All computation is on completed daily bars from CSVs; nothing is estimated.
"""
import csv, json, math, os
from datetime import datetime, timedelta

# ---- Ratified parameters (Section 4) ----
SWING_K = 2                 # bars each side, strict inequality [ratified v1.0]
MA_LEN = 50
MA_SLOPE_LOOKBACK = 5       # rising = value now > value 5 trading days ago
ATR_LEN = 14                # Wilder
APPROACH_ATR = 1.0          # approaching = within 1.0 x ATR of zone boundary [ratified]
WICK_BODY_RATIO = 1.5       # rejection candle [ratified]
STRONG_BODY_FRAC = 0.60     # rejection candle alt condition [ratified]
MIN_ROWS = 300

# ---- Operationalizations of unquantified plan language (flagged in Section E) ----
OPERATIONALIZATIONS = [
    "'pullback slightly through the 50DMA' -> close >= MA50 - 0.5*ATR(14) still counts as 'at or above'",
    "'price at/near the rising 50DMA' (zone factor 2) -> band = MA50 +/- 0.5*ATR(14)",
    "structural HL zone (zone factor 1) -> band = last confirmed daily swing low +/- 0.5*ATR(14)",
    "polarity-flip level (zone factor 3) -> most recent daily swing high broken by a later close within the last 120 bars, band +/- 0.5*ATR(14)",
    "zone = union of overlapping factor bands (>=2 factors overlapping)",
    "'pulled back from a higher high' -> last close below the most recent confirmed daily swing high",
    "rejection 'opening in/near the zone' -> open <= zone_hi + 0.25*ATR(14)",
    "stop buffer -> 0.1*ATR(14) below the structural level",
    "hypothetical entry for 2R pre-check -> last close",
    "nearest overhead structural target -> lowest daily swing high (of last 120 bars) above last close; if none, name is at highs and target test passes by absence of overhead structure (noted per name)",
    "'completed daily bar' for a 24/7 or foreign-calendar asset -> last bar dated on or before SPY's last completed session (spec Section 3.3 names SPY as the reference but does not define this for 24/7/non-US instruments); partial run-day bars are trimmed. Applied in run_scan.py via ref_date, not a literal date.",
]

def load_csv(path):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            rows.append(dict(date=r["Date"], o=float(r["Open"]), h=float(r["High"]),
                             l=float(r["Low"]), c=float(r["Close"]), v=float(r["Volume"])))
    return rows

def sanity(rows, allow_zero_vol=False):
    """Return list of integrity flags."""
    flags = []
    if len(rows) < MIN_ROWS:
        flags.append(f"only {len(rows)} bars (<{MIN_ROWS} required)")
    prev = None
    dup = bad_ohlc = zvol = 0
    max_gap = 0
    for r in rows:
        d = datetime.strptime(r["date"], "%Y-%m-%d")
        if prev is not None:
            if d <= prev:
                dup += 1
            gd = (d - prev).days
            if gd > max_gap:
                max_gap = gd
        prev = d
        if not (r["h"] >= max(r["o"], r["c"]) - 1e-9 and r["l"] <= min(r["o"], r["c"]) + 1e-9
                and r["h"] >= r["l"] and r["l"] > 0):
            bad_ohlc += 1
        if r["v"] == 0:
            zvol += 1
    if dup:
        flags.append(f"{dup} non-increasing dates")
    if bad_ohlc:
        flags.append(f"{bad_ohlc} bars fail OHLC consistency")
    if max_gap > 7:
        flags.append(f"largest date gap {max_gap} calendar days")
    if zvol > len(rows) * 0.3 and not allow_zero_vol:
        flags.append(f"{zvol}/{len(rows)} zero-volume bars")
    return flags

def swings(rows, k=SWING_K):
    """Strict fractal swings. Confirmed only (needs k bars after).
    Returns (highs, lows) as lists of dict(date, px, idx), chronological."""
    hs, ls = [], []
    n = len(rows)
    for i in range(k, n - k):
        h = rows[i]["h"]; l = rows[i]["l"]
        if all(h > rows[i + d]["h"] and h > rows[i - d]["h"] for d in range(1, k + 1)):
            hs.append(dict(date=rows[i]["date"], px=h, idx=i))
        if all(l < rows[i + d]["l"] and l < rows[i - d]["l"] for d in range(1, k + 1)):
            ls.append(dict(date=rows[i]["date"], px=l, idx=i))
    return hs, ls

def hh_hl(hs, ls):
    """Returns (verdict, detail): verdict in {'HHHL','LHLL','MIXED','INSUFFICIENT'}"""
    if len(hs) < 2 or len(ls) < 2:
        return "INSUFFICIENT", "fewer than 2 confirmed swing highs/lows"
    hh = hs[-1]["px"] > hs[-2]["px"]
    hl = ls[-1]["px"] > ls[-2]["px"]
    lh = hs[-1]["px"] < hs[-2]["px"]
    ll = ls[-1]["px"] < ls[-2]["px"]
    if hh and hl: return "HHHL", ""
    if lh and ll: return "LHLL", ""
    return "MIXED", f"HH={hh} HL={hl}"

def weekly_bars(rows):
    """Resample to weekly bars (weeks ending Friday; ISO week grouping).
    Only completed weeks: last week included only if its last bar is a Friday
    or data clearly extends past it (here: include all; the caller knows the
    final bar date)."""
    wk = {}
    order = []
    for i, r in enumerate(rows):
        d = datetime.strptime(r["date"], "%Y-%m-%d")
        key = d.isocalendar()[:2]  # (year, week)
        if key not in wk:
            wk[key] = dict(date=r["date"], o=r["o"], h=r["h"], l=r["l"], c=r["c"], v=r["v"])
            order.append(key)
        else:
            b = wk[key]
            b["h"] = max(b["h"], r["h"]); b["l"] = min(b["l"], r["l"])
            b["c"] = r["c"]; b["v"] += r["v"]; b["date"] = r["date"]  # date = last bar of week
    return [wk[k] for k in order]

def sma(vals, n):
    out = [None] * len(vals)
    s = 0.0
    for i, v in enumerate(vals):
        s += v
        if i >= n:
            s -= vals[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out

def atr_wilder(rows, n=ATR_LEN):
    trs = []
    for i, r in enumerate(rows):
        if i == 0:
            trs.append(r["h"] - r["l"])
        else:
            pc = rows[i - 1]["c"]
            trs.append(max(r["h"] - r["l"], abs(r["h"] - pc), abs(r["l"] - pc)))
    out = [None] * len(rows)
    if len(rows) < n + 1:
        return out
    a = sum(trs[1:n + 1]) / n
    out[n] = a
    for i in range(n + 1, len(rows)):
        a = (a * (n - 1) + trs[i]) / n
        out[i] = a
    return out

def classify(rows):
    """Full Section 4 classification. Returns a result dict."""
    res = dict(cls=None, why=[], detail={})
    n = len(rows)
    closes = [r["c"] for r in rows]
    ma = sma(closes, MA_LEN)
    atr = atr_wilder(rows)
    last = rows[-1]
    A = atr[-1]
    res["detail"]["last_close"] = last["c"]
    res["detail"]["last_date"] = last["date"]
    res["detail"]["atr14"] = A
    res["detail"]["ma50"] = ma[-1]
    res["detail"]["ma50_prev5"] = ma[-1 - MA_SLOPE_LOOKBACK] if n > MA_LEN + MA_SLOPE_LOOKBACK else None

    d_hs, d_ls = swings(rows)
    w = weekly_bars(rows)
    w_hs, w_ls = swings(w)
    res["detail"]["daily_swing_highs"] = d_hs[-2:] if len(d_hs) >= 2 else d_hs
    res["detail"]["daily_swing_lows"] = d_ls[-2:] if len(d_ls) >= 2 else d_ls
    res["detail"]["weekly_swing_highs"] = w_hs[-2:] if len(w_hs) >= 2 else w_hs
    res["detail"]["weekly_swing_lows"] = w_ls[-2:] if len(w_ls) >= 2 else w_ls

    dv, ddet = hh_hl(d_hs, d_ls)
    wv, wdet = hh_hl(w_hs, w_ls)
    res["detail"]["daily_structure"] = dv
    res["detail"]["weekly_structure"] = wv

    ma_ok = ma[-1] is not None and res["detail"]["ma50_prev5"] is not None
    ma_rising = ma_ok and ma[-1] > res["detail"]["ma50_prev5"]
    price_at_above = ma_ok and A is not None and last["c"] >= ma[-1] - 0.5 * A
    res["detail"]["ma50_rising"] = ma_rising if ma_ok else None
    res["detail"]["price_vs_ma"] = (last["c"] - ma[-1]) if ma_ok else None

    if dv == "LHLL":
        res["cls"] = "DOWNTREND"
        res["why"].append("daily lower-highs/lower-lows")
    elif wv == "HHHL" and dv == "HHHL" and ma_rising and price_at_above:
        res["cls"] = "UPTREND"
        res["why"].append("weekly HH/HL + daily HH/HL + rising 50DMA with price at/above")
    else:
        res["cls"] = "RANGE/AMBIGUOUS"
        for cond, msg in [(wv != "HHHL", f"weekly structure={wv}{(' ('+wdet+')') if wdet else ''}"),
                          (dv != "HHHL", f"daily structure={dv}{(' ('+ddet+')') if ddet else ''}"),
                          (ma_ok and not ma_rising, "50DMA not rising"),
                          (ma_ok and not price_at_above, "price below 50DMA beyond tolerance"),
                          (not ma_ok, "insufficient bars for 50DMA slope")]:
            if cond:
                res["why"].append(msg)

    # ---- Confluence zone (UPTREND names; computed regardless, used if UPTREND) ----
    factors = []
    if A is not None:
        if d_ls:
            lvl = d_ls[-1]["px"]
            factors.append(dict(name="structural HL (last swing low %s @ %.2f)" % (d_ls[-1]["date"], lvl),
                                lo=lvl - 0.5 * A, hi=lvl + 0.5 * A, key="structure"))
        if ma_ok and ma_rising:
            factors.append(dict(name="rising 50DMA (%.2f)" % ma[-1],
                                lo=ma[-1] - 0.5 * A, hi=ma[-1] + 0.5 * A, key="ma50"))
        # polarity flip: most recent swing high broken by later close, within last 120 bars
        flip = None
        for shp in reversed(d_hs):
            if shp["idx"] < n - 120:
                break
            broken = any(rows[j]["c"] > shp["px"] for j in range(shp["idx"] + 1, n))
            if broken and shp["px"] < last["c"]:
                flip = shp
                break
        if flip:
            factors.append(dict(name="polarity flip (broken res %s @ %.2f)" % (flip["date"], flip["px"]),
                                lo=flip["px"] - 0.5 * A, hi=flip["px"] + 0.5 * A, key="flip"))
    zone = None
    best = []
    for i in range(len(factors)):
        cluster = [factors[i]]
        for j in range(len(factors)):
            if i != j and not (factors[j]["hi"] < min(f["lo"] for f in cluster)
                               or factors[j]["lo"] > max(f["hi"] for f in cluster)):
                cluster.append(factors[j])
        if len(cluster) >= 2 and len(cluster) > len(best):
            best = cluster
    if best:
        zone = dict(lo=min(f["lo"] for f in best), hi=max(f["hi"] for f in best),
                    factors=[f["name"] for f in best], keys=[f["key"] for f in best])
    res["detail"]["zone"] = zone
    res["detail"]["zone_factors_all"] = [f["name"] for f in factors]

    # ---- Approaching / rejection / 2R (only meaningful for UPTREND) ----
    res["detail"]["approaching"] = False
    res["detail"]["rejection"] = None
    res["detail"]["dist_atr"] = None
    if zone and A:
        pulled_back = bool(d_hs) and last["c"] < d_hs[-1]["px"]
        if last["c"] > zone["hi"]:
            dist = (last["c"] - zone["hi"]) / A
        elif last["c"] < zone["lo"]:
            dist = (last["c"] - zone["lo"]) / A  # negative = below zone
        else:
            dist = 0.0
        res["detail"]["dist_atr"] = dist
        res["detail"]["pulled_back"] = pulled_back
        res["detail"]["approaching"] = pulled_back and 0 <= dist <= APPROACH_ATR

        # rejection candle on the last completed bar
        b = last
        touched = (b["l"] <= zone["hi"]) and (b["h"] >= zone["lo"])
        body = abs(b["c"] - b["o"])
        rng = b["h"] - b["l"]
        lower_wick = min(b["o"], b["c"]) - b["l"]
        cond_wick = (rng > 0 and body > 0 and lower_wick >= WICK_BODY_RATIO * body
                     and b["c"] >= b["l"] + 0.5 * rng and b["c"] >= zone["lo"])
        # allow doji-ish: if body==0 treat wick test as body<=... keep strict: body>0 required (flag if relevant)
        cond_body = (rng > 0 and b["c"] >= b["h"] - rng / 3.0 and body >= STRONG_BODY_FRAC * rng
                     and b["o"] <= zone["hi"] + 0.25 * A)
        if touched and pulled_back and (cond_wick or cond_body):
            res["detail"]["rejection"] = dict(
                type=("demand wick" if cond_wick else "strong bullish body"),
                bar=dict(date=b["date"], o=b["o"], h=b["h"], l=b["l"], c=b["c"]),
                lower_wick=lower_wick, body=body, range=rng)

        # 2R pre-check
        if res["detail"]["rejection"]:
            entry = last["c"]
            structural = min(zone["lo"], d_ls[-1]["px"] if d_ls else zone["lo"])
            stop = min(structural - 0.1 * A, entry - 2.0 * A)
            risk = entry - stop
            overhead = [h["px"] for h in d_hs if h["px"] > entry and h["idx"] >= n - 120]
            target = min(overhead) if overhead else None
            if target is None:
                r_mult = None
                pass2r = True
                tgt_note = "no overhead structure in last 120 bars (at highs)"
            else:
                r_mult = (target - entry) / risk if risk > 0 else None
                pass2r = r_mult is not None and r_mult >= 2.0
                tgt_note = f"nearest overhead swing high {target:.2f}"
            res["detail"]["pre2r"] = dict(entry=entry, stop=stop, risk=risk,
                                          two_atr=2.0 * A, structural_stop=structural - 0.1 * A,
                                          target=target, target_note=tgt_note,
                                          r_multiple=r_mult, passes=pass2r)
    return res

if __name__ == "__main__":
    print("scan_engine module - import and call classify(rows)")
