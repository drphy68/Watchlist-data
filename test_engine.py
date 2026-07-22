"""Unit tests for scan_engine with hand-constructed synthetic series."""
import sys, math
sys.path.insert(0, "/home/claude/scan")
from scan_engine import (swings, hh_hl, weekly_bars, sma, atr_wilder, classify,
                          half_day_dates, avgvol50, rvol_series, obv, volume_module,
                          volume_adjustment_candidates, V1_QUIET_RVOL, V1_SPIKE_RVOL,
                          V2_CONFIRM_RVOL, V3_SLOPE_LOOKBACK)
from datetime import datetime, timedelta

def mkrows(prices, start="2025-01-06"):
    """prices: list of (o,h,l,c) or c floats -> daily rows skipping weekends"""
    rows = []
    d = datetime.strptime(start, "%Y-%m-%d")
    for p in prices:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        if isinstance(p, tuple):
            o, h, l, c = p
        else:
            o = h = l = c = float(p); h += 0.5; l -= 0.5
        rows.append(dict(date=d.strftime("%Y-%m-%d"), o=o, h=h, l=l, c=c, v=1000.0))
        d += timedelta(days=1)
    return rows

fails = []

def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (" | " + extra if extra else ""))
    if not cond:
        fails.append(name)

# --- swings: strict 2-bar fractal ---
# highs: sequence with clear peak at index 3 (value 15) surrounded by lower highs
seq = [10, 11, 12, 15, 12, 11, 10, 9, 12, 13, 18, 13, 12, 11, 10]
rows = mkrows(seq)
hs, ls = swings(rows)
check("swing high detection", [h["idx"] for h in hs] == [3, 10], str([h["idx"] for h in hs]))
# low at idx 7 (9): neighbors 10,12 above and 12,13 after -> swing low
check("swing low detection", 7 in [l["idx"] for l in ls], str([l["idx"] for l in ls]))

# strictness: plateau must NOT count
seq2 = [10, 11, 12, 12, 11, 10, 9, 8, 7, 6, 5]
hs2, _ = swings(mkrows(seq2))
check("plateau rejected (strict >)", all(h["idx"] not in (2, 3) for h in hs2), str([h["idx"] for h in hs2]))

# --- hh_hl ---
hsA = [dict(px=10, date="a", idx=0), dict(px=12, date="b", idx=5)]
lsA = [dict(px=8, date="a", idx=2), dict(px=9, date="b", idx=7)]
check("HHHL verdict", hh_hl(hsA, lsA)[0] == "HHHL")
lsB = [dict(px=8, date="a", idx=2), dict(px=7, date="b", idx=7)]
check("MIXED verdict", hh_hl(hsA, lsB)[0] == "MIXED")
hsC = [dict(px=12, date="a", idx=0), dict(px=10, date="b", idx=5)]
check("LHLL verdict", hh_hl(hsC, lsB)[0] == "LHLL")

# --- weekly bars: ISO week grouping, close = last day's close ---
rows_w = mkrows(list(range(1, 11)))  # 10 days = 2 weeks
wb = weekly_bars(rows_w)
check("weekly count", len(wb) == 2, str(len(wb)))
check("weekly close = Friday close", wb[0]["c"] == 5 and wb[1]["c"] == 10)
check("weekly high", wb[0]["h"] == 5.5 and wb[1]["h"] == 10.5)

# --- sma ---
s = sma([1, 2, 3, 4, 5], 3)
check("sma", s == [None, None, 2.0, 3.0, 4.0], str(s))

# --- ATR Wilder vs hand computation ---
bars = mkrows([(10, 11, 9, 10.5), (10.5, 12, 10, 11.5), (11.5, 12.5, 11, 12)] * 10)
a = atr_wilder(bars, 14)
# TR for bar i>0: max(h-l, |h-pc|, |l-pc|)
trs = []
for i in range(1, len(bars)):
    pc = bars[i - 1]["c"]
    b = bars[i]
    trs.append(max(b["h"] - b["l"], abs(b["h"] - pc), abs(b["l"] - pc)))
seed = sum(trs[:14]) / 14
cur = seed
for t in trs[14:]:
    cur = (cur * 13 + t) / 14
check("ATR Wilder", abs(a[-1] - cur) < 1e-9, f"{a[-1]} vs {cur}")

# --- classify: constructed uptrend with pullback to confluence + rejection wick ---
# Build: rise to 120, pullback, HL, rise to 140, pullback toward 50DMA/last swing low
up = []
px = 100.0
import random
random.seed(7)
pattern = ([1.0] * 30 + [-0.8] * 6 + [1.0] * 25 + [-0.7] * 5 + [1.1] * 25 + [-0.9] * 6
           + [1.0] * 30 + [-0.8] * 7 + [1.0] * 30 + [-0.75] * 8 + [1.0] * 35 + [-0.9] * 6
           + [1.0] * 30 + [-0.85] * 42)
for step in pattern[:320]:
    px += step
    up.append((px - 0.3, px + 0.6, px - 0.7, px))
rows_up = mkrows(up)
res = classify(rows_up)
print("constructed series class:", res["cls"], "| why:", res["why"])
print("zone:", res["detail"]["zone"])
print("dist_atr:", res["detail"]["dist_atr"], "approaching:", res["detail"]["approaching"])
check("classify runs and yields a class", res["cls"] in ("UPTREND", "RANGE/AMBIGUOUS", "DOWNTREND"))

# --- classify: clear downtrend ---
dn = [(200 - i * 0.8 + 0.2, 200 - i * 0.8 + 0.9, 200 - i * 0.8 - 0.9, 200 - i * 0.8)
      for i in range(320)]
# add wiggles so swings exist
dn2 = []
for i, b in enumerate(dn):
    w = 8.0 * math.sin(i / 5.0)
    dn2.append((b[0] + w, b[1] + w, b[2] + w, b[3] + w))
res_dn = classify(mkrows(dn2))
check("downtrend classified", res_dn["cls"] == "DOWNTREND", res_dn["cls"] + " " + str(res_dn["why"]))

# --- rejection candle logic direct test ---
# Make an uptrend whose LAST bar dips into zone and closes strong with long lower wick
rows_rj = mkrows(up[:300])
res0 = classify(rows_rj)
if res0["detail"]["zone"]:
    z = res0["detail"]["zone"]
    zone_mid = (z["lo"] + z["hi"]) / 2
    lastc = rows_rj[-1]["c"]
    # craft bar: opens slightly above zone, dips to zone mid, closes near top
    o = z["hi"] + 0.1
    l = zone_mid
    c = o + 0.4
    h = c + 0.1
    rows_rj.append(dict(date="2026-07-17", o=o, h=h, l=l, c=c, v=1000.0))
    res_rj = classify(rows_rj)
    print("crafted rejection:", res_rj["detail"]["rejection"], "cls:", res_rj["cls"])
    if res_rj["cls"] == "UPTREND" and res_rj["detail"]["zone"]:
        check("rejection wick detected on crafted bar", res_rj["detail"]["rejection"] is not None)
        if res_rj["detail"]["rejection"]:
            print("pre2r:", res_rj["detail"].get("pre2r"))
else:
    print("NOTE: no zone in synthetic base series; rejection craft skipped")

# --- REJECTION + 2R PATH (committed; the earlier fixture classified RANGE and skipped these) ---
def build_uptrend_with_rejection():
    """Genuine staircase uptrend, wide bars (big ATR -> wide factor bands so >=2 overlap),
    pulled back so close sits at the 50DMA, then a demand-wick bar into the zone."""
    from datetime import datetime, timedelta
    rows = []
    d = datetime(2025, 1, 6)
    def add(o, h, l, c):
        nonlocal d
        while d.weekday() >= 5:
            d += timedelta(days=1)
        rows.append(dict(date=d.strftime("%Y-%m-%d"), o=o, h=h, l=l, c=c, v=1e6))
        d += timedelta(days=1)
    px = 100.0
    for leg in range(6):
        for _ in range(22):
            px += 1.0; add(px - 0.6, px + 1.6, px - 2.2, px)
        for _ in range(6):
            px -= 1.1; add(px + 0.6, px + 1.8, px - 2.0, px)
    for _ in range(30):
        ma = sma([r["c"] for r in rows], 50)[-1]
        if rows[-1]["c"] - ma <= 2.0:
            break
        px -= 1.0; add(px + 0.5, px + 1.5, px - 1.8, px)
    base = classify(rows)
    z = base["detail"]["zone"]
    # demand-wick bar: opens near zone hi, dips deep into zone, closes back near open
    add(z["hi"] - 0.5, z["hi"] + 0.3, z["lo"] + 0.2, z["hi"] + 0.1)
    return rows

rows_rej = build_uptrend_with_rejection()
res_rej = classify(rows_rej)
d = res_rej["detail"]
check("rejection-path: base is UPTREND with a zone", res_rej["cls"] == "UPTREND" and d["zone"] is not None,
      f"{res_rej['cls']} zone={bool(d['zone'])}")
check("rejection-path: demand-wick rejection detected", d["rejection"] is not None,
      str(d["rejection"] and d["rejection"]["type"]))
check("rejection-path: 2R pre-check populated", d.get("pre2r") is not None)
if d.get("pre2r"):
    p = d["pre2r"]
    # doubly-constrained stop: the WIDER of (structural-buffer) vs (entry - 2*ATR)
    expect_stop = min(p["structural_stop"], p["entry"] - p["two_atr"])
    check("rejection-path: stop = wider of structural vs 2xATR", abs(p["stop"] - expect_stop) < 1e-9,
          f"{p['stop']} vs {expect_stop}")
    if p.get("target") is not None and p["risk"] > 0:
        expect_r = (p["target"] - p["entry"]) / p["risk"]
        check("rejection-path: R-multiple recomputes", abs(p["r_multiple"] - expect_r) < 1e-9,
              f"{p['r_multiple']} vs {expect_r}")
        check("rejection-path: passes flag consistent with 2R", p["passes"] == (expect_r >= 2.0))

# =====================================================================================
# Volume module tests (Section 4.2, v1.2)
# =====================================================================================

# --- half_day_dates: rule-derived, spot-check known weekday configurations ---
# 2026: July 4 is a Saturday -> observed Friday July 3, half day Thursday July 2.
hd2026 = half_day_dates([2026])
check("half-day: July 4 on Saturday -> half day Thu July 2", "2026-07-02" in hd2026, str(hd2026))
# 2025: July 4 is a Friday -> half day Thursday July 3.
hd2025 = half_day_dates([2025])
check("half-day: July 4 on Friday -> half day Thu July 3", "2025-07-03" in hd2025, str(hd2025))
# 2027: July 4 is a Sunday -> half day Friday July 3 (day before actual July 4th).
hd2027 = half_day_dates([2027])
check("half-day: July 4 on Sunday -> half day Fri July 2", "2027-07-02" in hd2027, str(hd2027))
# Thanksgiving Friday: 2026 Thanksgiving is Nov 26 (4th Thursday) -> Nov 27.
check("half-day: Friday after Thanksgiving 2026", "2026-11-27" in hd2026, str(hd2026))
# Christmas Eve: 2026-12-24 is a Thursday (weekday) -> included.
check("half-day: Dec 24 2026 (weekday) included", "2026-12-24" in hd2026, str(hd2026))
# 2025-12-24 is a Wednesday (weekday) -> included; sanity on a second year.
check("half-day: Dec 24 2025 (weekday) included", "2025-12-24" in hd2025, str(hd2025))

# --- avgvol50: simple average, half-days excluded, offset by one day ---
vol_rows = [dict(date=(datetime(2026, 1, 1) + timedelta(days=i)).strftime("%Y-%m-%d"),
                 o=1, h=1, l=1, c=1, v=100.0) for i in range(60)]
av = avgvol50(vol_rows, half_days=[])
check("avgvol50: None until 50 eligible prior days", av[49] is None and av[50] is not None,
      f"av[49]={av[49]} av[50]={av[50]}")
check("avgvol50: simple average value", av[50] == 100.0, str(av[50]))
# bump one bar's volume and confirm it dilutes the FOLLOWING day's average, not its own
vol_rows2 = [dict(r) for r in vol_rows]
vol_rows2[10]["v"] = 5000.0
av2 = avgvol50(vol_rows2, half_days=[])
check("avgvol50: a bar's own volume does not inflate its own benchmark",
      av2[10] is None or av2[10] != 5000.0)
check("avgvol50: the spike shows up in a later window", av2[55] > av[50], f"{av2[55]} vs {av[50]}")
# half-day exclusion: mark day 10 as a half day and confirm its volume is skipped from the window
hd_date = vol_rows[10]["date"]
av3 = avgvol50(vol_rows2, half_days=[hd_date])
check("avgvol50: half-day bar excluded from the rolling window", av3[55] < av2[55],
      f"{av3[55]} vs {av2[55]}")

# --- obv: up day adds, down day subtracts, flat day no change ---
obv_rows = mkrows([10, 12, 12, 9, 11])  # up, flat, down, up
o = obv(obv_rows)
check("obv seeds at 0", o[0] == 0.0)
check("obv up day adds volume", o[1] == 1000.0, str(o[1]))
check("obv flat day no change", o[2] == o[1], str(o[2]))
check("obv down day subtracts volume", o[3] == o[2] - 1000.0, str(o[3]))
check("obv up day adds again", o[4] == o[3] + 1000.0, str(o[4]))

# --- volume_module: V1 quiet-pullback classification on a constructed leg ---
quiet_leg_rows = build_uptrend_with_rejection()  # reuse the rejection-path fixture (has a zone + pullback)
res_v = classify(quiet_leg_rows)
half_days_test = half_day_dates([2025, 2026])
vol_res = volume_module(quiet_leg_rows, half_days_test, res_v)
check("volume_module: V3 computed for UPTREND name", "v3" in vol_res, str(vol_res.get("v3")))
if "v3" in vol_res:
    check("volume_module: V3 tag is one of the defined states",
          vol_res["v3"]["tag"] in ("ACCUM", "NEUTRAL", "DIVERGENCE-WARNING"), vol_res["v3"]["tag"])
check("volume_module: V2 computed for rejection bar", "v2" in vol_res, str(vol_res.get("v2")))
if "v2" in vol_res:
    check("volume_module: V2 verdict is one of the defined states",
          vol_res["v2"]["verdict"] in ("CONFIRMED", "UNCONFIRMED", "SUSPECT", None), vol_res["v2"]["verdict"])

# --- V2 boundary tests via direct construction (RVOL thresholds) ---
def make_rejection_case(rvol_last):
    """50 quiet days (RVOL~1.0) then a rejection-style last bar whose volume yields rvol_last."""
    rows = [dict(date=(datetime(2026, 1, 1) + timedelta(days=i)).strftime("%Y-%m-%d"),
                o=100, h=101, l=99, c=100, v=1000.0) for i in range(55)]
    rows.append(dict(date=(datetime(2026, 1, 1) + timedelta(days=55)).strftime("%Y-%m-%d"),
                     o=100, h=102, l=98, c=101, v=1000.0 * rvol_last))
    return rows

for rvol_in, expect in [(2.0, "CONFIRMED"), (1.2, "UNCONFIRMED"), (0.5, "SUSPECT")]:
    rows_v2 = make_rejection_case(rvol_in)
    fake_result = dict(cls="UPTREND", detail=dict(rejection=dict(type="test"), daily_swing_highs=[]))
    v = volume_module(rows_v2, [], fake_result)
    check(f"V2 boundary: RVOL={rvol_in}x -> {expect}", v["v2"]["verdict"] == expect,
          f"got {v['v2']['verdict']}")

# half-day forces UNCONFIRMED regardless of RVOL
rows_hd = make_rejection_case(3.0)
hd_last = rows_hd[-1]["date"]
fake_result_hd = dict(cls="UPTREND", detail=dict(rejection=dict(type="test"), daily_swing_highs=[]))
v_hd = volume_module(rows_hd, [hd_last], fake_result_hd)
check("V2: half-day session forces UNCONFIRMED regardless of RVOL",
      v_hd["v2"]["verdict"] == "UNCONFIRMED", str(v_hd["v2"]))

print("\n" + ("ALL PASS" if not fails else f"FAILURES: {fails}"))
