"""
Weekend Mode scan runner. Usage: python3 run_scan.py <data_dir>
data_dir must contain the per-symbol CSVs + manifest.json produced by
fetch_watchlist_data.py. Writes results.json (full computed detail per symbol).
Report rendering is done separately (render_reports.py).
"""
import json, os, sys
sys.path.insert(0, "/home/claude/scan")
from scan_engine import (classify, load_csv, sanity, MIN_ROWS, OPERATIONALIZATIONS,
                          half_day_dates, volume_module)

CONTEXT_ONLY = {"CBOE:VIX", "ICEUS:DXY", "OANDA:XAUUSD", "BITSTAMP:BTCUSD",
                "SPCFD:SPX", "NASDAQ:NDX", "NQ=F", "MANA-USD"}
NO_VOLUME_OK = CONTEXT_ONLY | {"SSE:000300"}

def main(data_dir):
    manifest = json.load(open(os.path.join(data_dir, "manifest.json")))
    symmap = {s["tv"]: s for s in json.load(open("/home/claude/scan/symbol_map.json"))}
    results = {}
    # Reference session = SPY's last completed daily bar (spec Section 3.3). Used to define
    # "completed bar" for 24/7 / foreign-calendar assets instead of a hardcoded date, so the
    # rule generalizes across runs. (OPERATIONALIZATION #11 — disclosed in scan_engine.py.)
    _spy = manifest.get("AMEX:SPY", {})
    ref_date = None
    if _spy.get("status") == "ok":
        ref_date = load_csv(os.path.join(data_dir, _spy["file"]))[-1]["date"]

    # Volume module (Section 4.2, v1.2): half-day dates derived by rule, computed once for a
    # window comfortably covering the ~300+ trading day (~14 month) lookback plus margin.
    ref_year = int(ref_date[:4]) if ref_date else 2026
    half_days = half_day_dates(range(ref_year - 2, ref_year + 2))

    for tv, m in manifest.items():
        if tv.startswith("_"):
            continue
        entry = dict(tv=tv, manifest=m, lists=symmap[tv]["lists"],
                     sections=symmap[tv]["sections"], note=symmap[tv]["note"],
                     context_only=tv in CONTEXT_ONLY)
        if m.get("status") != "ok":
            entry["status"] = "NO_DATA"
            results[tv] = entry
            continue
        rows = load_csv(os.path.join(data_dir, m["file"]))
        # completed-bars-only rule (spec 3.3, OPERATIONALIZATION #11): a 24/7 or foreign-calendar
        # asset can carry a bar dated after the last completed US session (a partial/in-progress
        # bar on the run day). Trim any bar strictly newer than SPY's last completed bar. Derived
        # from ref_date, never a literal, so future runs stay correct.
        if tv in ("BITSTAMP:BTCUSD", "MANA-USD") and ref_date:
            before = len(rows)
            rows = [r for r in rows if r["date"] <= ref_date]
            if len(rows) != before:
                entry["trimmed_partial_bars"] = before - len(rows)
        flags = sanity(rows, allow_zero_vol=tv in NO_VOLUME_OK)
        entry["integrity_flags"] = flags
        entry["rows"] = len(rows)
        entry["first_date"] = rows[0]["date"]
        entry["last_date"] = rows[-1]["date"]
        entry["source"] = m.get("source")
        hard_fail = len(rows) < 60
        if hard_fail:
            entry["status"] = "DATA_TOO_SHORT"
            results[tv] = entry
            continue
        r = classify(rows)
        entry["status"] = "OK"
        entry["cls"] = r["cls"]
        entry["why"] = r["why"]
        entry["detail"] = r["detail"]
        # Section 4.2 volume diagnostics (v1.2) — report-only, computed after and separate
        # from classify(); never fed back into cls/why/ranking (Section 8 no-effect rule).
        entry["detail"]["volume"] = volume_module(rows, half_days, r)
        results[tv] = entry
    json.dump(results, open("/home/claude/scan/results.json", "w"), indent=1, default=str)

    # console summary
    from collections import Counter
    c = Counter(v.get("cls") or v["status"] for v in results.values())
    print("CLASS COUNTS:", dict(c))
    spy = results.get("AMEX:SPY", {})
    print("SPY:", spy.get("cls"), "last bar:", spy.get("last_date"), "source:", spy.get("source"))
    ups = [tv for tv, v in results.items() if v.get("cls") == "UPTREND"]
    print(f"UPTREND ({len(ups)}):", " ".join(sorted(ups)))
    app = [tv for tv, v in results.items() if v.get("cls") == "UPTREND"
           and v["detail"].get("approaching")]
    print("APPROACHING:", " ".join(sorted(app)) or "none")
    rej = [tv for tv, v in results.items() if v.get("cls") == "UPTREND"
           and v["detail"].get("rejection")]
    print("REJECTION CANDLES:", " ".join(sorted(rej)) or "none")
    bad = [tv for tv, v in results.items() if v["status"] != "OK" or v.get("integrity_flags")]
    print("FLAGGED/FAILED:", len(bad))
    for tv in sorted(bad):
        v = results[tv]
        print("  ", tv, v["status"], v.get("integrity_flags", ""))

    # Volume module (v1.2) sanity summary — report-only, does not affect any category above.
    v3_tags = Counter(v["detail"]["volume"]["v3"]["tag"] for v in results.values()
                       if v.get("cls") == "UPTREND" and v.get("detail", {}).get("volume", {}).get("v3"))
    v2_verdicts = Counter(v["detail"]["volume"]["v2"]["verdict"] for v in results.values()
                          if v.get("detail", {}).get("volume", {}).get("v2"))
    print("V3 OBV TAGS (uptrends):", dict(v3_tags))
    print("V2 DEMAND-CONFIRMATION VERDICTS (rejection bars):", dict(v2_verdicts))
    print("HALF-DAYS IN WINDOW (rule-derived, sample):", half_days[:6], "..." if len(half_days) > 6 else "")

if __name__ == "__main__":
    main(sys.argv[1])
