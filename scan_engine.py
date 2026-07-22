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
    "half-day session dates (Section 3.5, v1.2) -> derived by RULE each run (day before the observed July 4th holiday; Friday after Thanksgiving = day after the 4th Thursday of November; Dec 24 only if it falls Mon-Fri), not a hardcoded per-year list, so the exclusion generalizes to any year without manual maintenance. See half_day_dates() in scan_engine.py.",
    "volume/price split-adjustment consistency check (Section 3.5, v1.2) -> no maintained corporate-actions calendar is cross-checked; instead, days where close-to-close price moves >=35% are surfaced as split-candidate dates for manual review (volume_adjustment_candidates()). This is a coarse heuristic, not a definitive audit -- Section E must say so explicitly, and OBV/RVOL figures spanning a flagged date are tagged suspect.",
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


# =====================================================================================
# Section 4.2 — Volume module (added v1.2, 2026-07-22, drafted-and-owner-incorporated).
# REPORT-ONLY per Section 8: nothing below may alter cls_result['cls'] or any category
# admission/ranking decision made in classify(). Called separately, after classify(),
# and merged into detail['volume'] by the caller (run_scan.py) — classify() itself is
# left byte-for-byte unchanged, per the "never alter Section 4.1" rule.
# =====================================================================================
V1_QUIET_RVOL = 0.9         # quiet-pullback mean-RVOL ceiling [PARAMETER — pending ratification]
V1_SPIKE_RVOL = 2.0         # quiet-pullback down-day spike floor [PARAMETER — pending ratification]
V2_CONFIRM_RVOL = 1.5       # demand-confirmation RVOL floor [PARAMETER — pending ratification]
V3_SLOPE_LOOKBACK = 20      # OBV slope lookback, trading days [PARAMETER — pending ratification]
SPLIT_CANDIDATE_MOVE = 0.35 # close-to-close |chg| flagged as a possible unadjusted split artifact

def half_day_dates(years):
    """NYSE scheduled 1pm-ET early closes, derived by RULE (not a hardcoded per-year table):
      - the business day before the OBSERVED July 4th holiday (if July 4 falls on a Saturday,
        the holiday is observed the preceding Friday and the half day falls on the Thursday
        before that; if July 4 is a Sunday, the holiday is observed the following Monday and
        the half day is the Friday before the actual July 4th; otherwise the half day is the
        weekday immediately before July 4th itself);
      - the Friday after Thanksgiving (Thanksgiving = 4th Thursday of November);
      - December 24th, only if it falls Monday-Friday (no separate half day if it's a weekend).
    Operationalizes Section 3.5's 'typically July 3 or the weekday before/after July 4' language;
    logged in OPERATIONALIZATIONS and Section E, pending ratification."""
    out = []
    for y in years:
        jul4 = datetime(y, 7, 4)
        wd = jul4.weekday()  # Mon=0 ... Sun=6
        if wd == 5:  # Saturday -> observed Friday July 3; half day Thursday July 2
            half = jul4 - timedelta(days=2)
        elif wd == 6:  # Sunday -> observed Monday July 5; half day is the preceding Friday July 2
            half = jul4 - timedelta(days=2)
        else:
            half = jul4 - timedelta(days=1)
            while half.weekday() >= 5:
                half -= timedelta(days=1)
        out.append(half.strftime("%Y-%m-%d"))

        d = datetime(y, 11, 1)
        thu_count = 0
        thanksgiving = None
        while d.month == 11:
            if d.weekday() == 3:
                thu_count += 1
                if thu_count == 4:
                    thanksgiving = d
                    break
            d += timedelta(days=1)
        if thanksgiving:
            out.append((thanksgiving + timedelta(days=1)).strftime("%Y-%m-%d"))

        xmas_eve = datetime(y, 12, 24)
        if xmas_eve.weekday() < 5:
            out.append(xmas_eve.strftime("%Y-%m-%d"))
    return sorted(set(out))

def volume_adjustment_candidates(rows, threshold=SPLIT_CANDIDATE_MOVE):
    """Coarse split-artifact scan (Section 3.5): dates where close-to-close price moved by
    >= threshold. NOT a definitive split-adjustment audit (no corporate-actions calendar is
    cross-checked) -- flags candidate dates for manual review; Section E must disclose this
    is a heuristic, not a verification."""
    flags = []
    for i in range(1, len(rows)):
        pc = rows[i - 1]["c"]
        if pc <= 0:
            continue
        chg = (rows[i]["c"] - pc) / pc
        if abs(chg) >= threshold:
            flags.append(dict(date=rows[i]["date"], chg=chg))
    return flags

def avgvol50(rows, half_days):
    """Simple 50-day average of daily volume, excluding half-day sessions (Section 3.5).
    avgvol50[i] uses the 50 eligible days ending the day BEFORE bar i, so a bar never dilutes
    its own benchmark (Section 4.2). Returns a list aligned to rows (None until 50 eligible
    prior days exist)."""
    hd = set(half_days)
    out = [None] * len(rows)
    eligible_vols = []
    for i, r in enumerate(rows):
        if len(eligible_vols) >= 50:
            out[i] = sum(eligible_vols[-50:]) / 50.0
        if r["date"] not in hd:
            eligible_vols.append(r["v"])
    return out

def rvol_series(rows, av):
    return [(rows[i]["v"] / av[i]) if av[i] else None for i in range(len(rows))]

def obv(rows):
    """On-Balance Volume, seeded at 0 at the start of the data window (Section 4.2 V3).
    Absolute level is meaningless / source-dependent; only slope and swing-to-swing
    comparisons are used."""
    out = [0.0] * len(rows)
    cum = 0.0
    for i in range(1, len(rows)):
        if rows[i]["c"] > rows[i - 1]["c"]:
            cum += rows[i]["v"]
        elif rows[i]["c"] < rows[i - 1]["c"]:
            cum -= rows[i]["v"]
        out[i] = cum
    return out

def volume_module(rows, half_days, cls_result):
    """Section 4.2 diagnostics (V1/V2/V3 + AvgVol50/RVOL). REPORT-ONLY: returns a dict to be
    stashed at detail['volume'] by the caller; never mutates cls_result['cls'] or ranking."""
    d = cls_result["detail"]
    hd_set = set(half_days)
    av = avgvol50(rows, half_days)
    rv = rvol_series(rows, av)
    n = len(rows)
    vol = dict(
        avgvol50=av[-1],
        last_rvol=rv[-1],
        half_days_in_window=[h for h in half_days if rows[0]["date"] <= h <= rows[-1]["date"]],
        split_candidates=volume_adjustment_candidates(rows),
    )

    is_uptrend = cls_result.get("cls") == "UPTREND"
    d_hs = d.get("daily_swing_highs") or []

    # V3 — OBV accumulation tag (every UPTREND name)
    if is_uptrend:
        ob = obv(rows)
        slope_ok = n > V3_SLOPE_LOOKBACK and ob[-1] > ob[n - 1 - V3_SLOPE_LOOKBACK]
        divergence = False
        if len(d_hs) >= 2 and "idx" in d_hs[-1] and "idx" in d_hs[-2]:
            i_last, i_prev = d_hs[-1]["idx"], d_hs[-2]["idx"]
            price_hh = d_hs[-1]["px"] > d_hs[-2]["px"]
            obv_hh = ob[i_last] > ob[i_prev]
            divergence = price_hh and not obv_hh
        tag = "DIVERGENCE-WARNING" if divergence else ("ACCUM" if slope_ok else "NEUTRAL")
        vol["v3"] = dict(tag=tag, slope_pass=slope_ok, divergence=divergence,
                          obv_last=ob[-1],
                          obv_lookback=ob[n - 1 - V3_SLOPE_LOOKBACK] if n > V3_SLOPE_LOOKBACK else None)

    # V1 — quiet-pullback test (Approaching or has-rejection UPTREND names only; leg >= 3 bars)
    if is_uptrend and (d.get("approaching") or d.get("rejection")) and d_hs and "idx" in d_hs[-1]:
        i_sh = d_hs[-1]["idx"]
        leg = list(range(i_sh + 1, n))
        if len(leg) < 3:
            vol["v1"] = dict(status="leg too short", n_bars=len(leg))
        else:
            rvols = [rv[i] for i in leg if rv[i] is not None]
            mean_rv = (sum(rvols) / len(rvols)) if rvols else None
            spike = None
            for i in leg:
                r = rows[i]
                if r["c"] < r["o"] and rv[i] is not None and rv[i] >= V1_SPIKE_RVOL:
                    if spike is None or rv[i] > spike[1]:
                        spike = (r["date"], rv[i])
            passed = mean_rv is not None and mean_rv <= V1_QUIET_RVOL and spike is None
            vol["v1"] = dict(status=("quiet" if passed else "distribution-pattern"),
                              mean_rvol=mean_rv, n_bars=len(leg), coverage=len(rvols),
                              spike_date=spike[0] if spike else None,
                              spike_rvol=spike[1] if spike else None)

    # V2 — demand-confirmation test (rejection bar only)
    if d.get("rejection"):
        r_last = rv[-1]
        half_day_bar = rows[-1]["date"] in hd_set
        if half_day_bar:
            verdict = "UNCONFIRMED"
        elif r_last is None:
            verdict = None
        elif r_last >= V2_CONFIRM_RVOL:
            verdict = "CONFIRMED"
        elif r_last >= 1.0:
            verdict = "UNCONFIRMED"
        else:
            verdict = "SUSPECT"
        vol["v2"] = dict(rvol=r_last, verdict=verdict, half_day=half_day_bar)

    return vol


if __name__ == "__main__":
    print("scan_engine module - import and call classify(rows)")
