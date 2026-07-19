#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_watchlist_data.py  -  Watchlist OHLCV downloader (v1.0, 2026-07-19)
For: drphy68 pre-open watchlist scan (Weekend Mode run)

WHAT IT DOES
  Downloads ~2 years of daily OHLCV bars for 224 watchlist symbols from
  Stooq (primary) with Yahoo Finance as fallback, saves one CSV per symbol,
  writes a manifest of what came from where, and zips everything into
  watchlist_data.zip in the same folder.

HOW TO RUN (needs only Python 3.8+, no extra installs)
  Windows :  py fetch_watchlist_data.py
  Mac     :  python3 fetch_watchlist_data.py
  Takes roughly 3-6 minutes. Then upload watchlist_data.zip to the chat.

It only READS public price data and writes files into a new subfolder
"watchlist_data" next to itself. Safe to re-run; it skips completed symbols.
"""
import csv, io, json, os, ssl, sys, time, urllib.request, urllib.error, zipfile
from datetime import datetime, timedelta, timezone

SYMBOLS = [{"tv":"AMEX:SPY","stooq":["spy.us"],"yahoo":["SPY"]},{"tv":"NASDAQ:QQQ","stooq":["qqq.us"],"yahoo":["QQQ"]},{"tv":"AMEX:IWM","stooq":["iwm.us"],"yahoo":["IWM"]},{"tv":"AMEX:DIA","stooq":["dia.us"],"yahoo":["DIA"]},{"tv":"AMEX:XLF","stooq":["xlf.us"],"yahoo":["XLF"]},{"tv":"AMEX:XLE","stooq":["xle.us"],"yahoo":["XLE"]},{"tv":"NASDAQ:SOXX","stooq":["soxx.us"],"yahoo":["SOXX"]},{"tv":"CBOE:VIX","stooq":["^vix"],"yahoo":["^VIX"]},{"tv":"ICEUS:DXY","stooq":[],"yahoo":["DX-Y.NYB"]},{"tv":"OANDA:XAUUSD","stooq":["xauusd"],"yahoo":["XAUUSD=X","GC=F"]},{"tv":"NASDAQ:NVDA","stooq":["nvda.us"],"yahoo":["NVDA"]},{"tv":"NASDAQ:MSFT","stooq":["msft.us"],"yahoo":["MSFT"]},{"tv":"NASDAQ:AAPL","stooq":["aapl.us"],"yahoo":["AAPL"]},{"tv":"NASDAQ:AMZN","stooq":["amzn.us"],"yahoo":["AMZN"]},{"tv":"NASDAQ:META","stooq":["meta.us"],"yahoo":["META"]},{"tv":"NASDAQ:GOOGL","stooq":["googl.us"],"yahoo":["GOOGL"]},{"tv":"NASDAQ:AMD","stooq":["amd.us"],"yahoo":["AMD"]},{"tv":"NASDAQ:AVGO","stooq":["avgo.us"],"yahoo":["AVGO"]},{"tv":"NYSE:TSM","stooq":["tsm.us"],"yahoo":["TSM"]},{"tv":"NASDAQ:MU","stooq":["mu.us"],"yahoo":["MU"]},{"tv":"NYSE:VST","stooq":["vst.us"],"yahoo":["VST"]},{"tv":"NASDAQ:CEG","stooq":["ceg.us"],"yahoo":["CEG"]},{"tv":"NYSE:VRT","stooq":["vrt.us"],"yahoo":["VRT"]},{"tv":"NYSE:GEV","stooq":["gev.us"],"yahoo":["GEV"]},{"tv":"NYSE:ETN","stooq":["etn.us"],"yahoo":["ETN"]},{"tv":"NYSE:NRG","stooq":["nrg.us"],"yahoo":["NRG"]},{"tv":"NYSE:BE","stooq":["be.us"],"yahoo":["BE"]},{"tv":"NASDAQ:POWL","stooq":["powl.us"],"yahoo":["POWL"]},{"tv":"NASDAQ:ASML","stooq":["asml.us"],"yahoo":["ASML"]},{"tv":"NASDAQ:ARM","stooq":["arm.us"],"yahoo":["ARM"]},{"tv":"NASDAQ:MRVL","stooq":["mrvl.us"],"yahoo":["MRVL"]},{"tv":"NASDAQ:WDC","stooq":["wdc.us"],"yahoo":["WDC"]},{"tv":"NASDAQ:SNDK","stooq":["sndk.us"],"yahoo":["SNDK"]},{"tv":"NASDAQ:TER","stooq":["ter.us"],"yahoo":["TER"]},{"tv":"NASDAQ:PLTR","stooq":["pltr.us"],"yahoo":["PLTR"]},{"tv":"NASDAQ:CRWD","stooq":["crwd.us"],"yahoo":["CRWD"]},{"tv":"NYSE:NOW","stooq":["now.us"],"yahoo":["NOW"]},{"tv":"NYSE:CRM","stooq":["crm.us"],"yahoo":["CRM"]},{"tv":"NYSE:SNOW","stooq":["snow.us"],"yahoo":["SNOW"]},{"tv":"NASDAQ:HOOD","stooq":["hood.us"],"yahoo":["HOOD"]},{"tv":"NYSE:FCX","stooq":["fcx.us"],"yahoo":["FCX"]},{"tv":"AMEX:GDX","stooq":["gdx.us"],"yahoo":["GDX"]},{"tv":"NASDAQ:FANG","stooq":["fang.us"],"yahoo":["FANG"]},{"tv":"NYSE:SCCO","stooq":["scco.us"],"yahoo":["SCCO"]},{"tv":"NYSE:HBM","stooq":["hbm.us"],"yahoo":["HBM"]},{"tv":"NYSE:BAC","stooq":["bac.us"],"yahoo":["BAC"]},{"tv":"NYSE:JPM","stooq":["jpm.us"],"yahoo":["JPM"]},{"tv":"NYSE:GS","stooq":["gs.us"],"yahoo":["GS"]},{"tv":"NASDAQ:HONA","stooq":["hona.us"],"yahoo":["HONA"]},{"tv":"NYSE:VGNT","stooq":["vgnt.us"],"yahoo":["VGNT"]},{"tv":"NYSE:OKLO","stooq":["oklo.us"],"yahoo":["OKLO"]},{"tv":"NASDAQ:WULF","stooq":["wulf.us"],"yahoo":["WULF"]},{"tv":"NASDAQ:MSTR","stooq":["mstr.us"],"yahoo":["MSTR"]},{"tv":"NASDAQ:RKLB","stooq":["rklb.us"],"yahoo":["RKLB"]},{"tv":"NYSE:CVNA","stooq":["cvna.us"],"yahoo":["CVNA"]},{"tv":"NYSE:V","stooq":["v.us"],"yahoo":["V"]},{"tv":"NYSE:MA","stooq":["ma.us"],"yahoo":["MA"]},{"tv":"NYSE:ICE","stooq":["ice.us"],"yahoo":["ICE"]},{"tv":"NASDAQ:MNST","stooq":["mnst.us"],"yahoo":["MNST"]},{"tv":"NASDAQ:PAYX","stooq":["payx.us"],"yahoo":["PAYX"]},{"tv":"NASDAQ:ADP","stooq":["adp.us"],"yahoo":["ADP"]},{"tv":"NASDAQ:GILD","stooq":["gild.us"],"yahoo":["GILD"]},{"tv":"NYSE:DHR","stooq":["dhr.us"],"yahoo":["DHR"]},{"tv":"NASDAQ:ADI","stooq":["adi.us"],"yahoo":["ADI"]},{"tv":"NYSE:CB","stooq":["cb.us"],"yahoo":["CB"]},{"tv":"NYSE:TJX","stooq":["tjx.us"],"yahoo":["TJX"]},{"tv":"NASDAQ:COST","stooq":["cost.us"],"yahoo":["COST"]},{"tv":"NYSE:MCD","stooq":["mcd.us"],"yahoo":["MCD"]},{"tv":"NYSE:XYL","stooq":["xyl.us"],"yahoo":["XYL"]},{"tv":"NYSE:AWK","stooq":["awk.us"],"yahoo":["AWK"]},{"tv":"NYSE:WTRG","stooq":["wtrg.us"],"yahoo":["WTRG"]},{"tv":"NYSE:ECL","stooq":["ecl.us"],"yahoo":["ECL"]},{"tv":"NYSE:PNR","stooq":["pnr.us"],"yahoo":["PNR"]},{"tv":"NYSE:MWA","stooq":["mwa.us"],"yahoo":["MWA"]},{"tv":"NASDAQ:ERII","stooq":["erii.us"],"yahoo":["ERII"]},{"tv":"NYSE:VLTO","stooq":["vlto.us"],"yahoo":["VLTO"]},{"tv":"AMEX:FIW","stooq":["fiw.us"],"yahoo":["FIW"]},{"tv":"NYSE:BHP","stooq":["bhp.us"],"yahoo":["BHP"]},{"tv":"AMEX:COPX","stooq":["copx.us"],"yahoo":["COPX"]},{"tv":"NYSE:BAM","stooq":["bam.us"],"yahoo":["BAM"]},{"tv":"NYSE:BX","stooq":["bx.us"],"yahoo":["BX"]},{"tv":"SGX:D05","stooq":[],"yahoo":["D05.SI"]},{"tv":"SGX:ES3","stooq":[],"yahoo":["ES3.SI"]},{"tv":"SGX:C6L","stooq":[],"yahoo":["C6L.SI"]},{"tv":"HKEX:9926","stooq":["9926.hk"],"yahoo":["9926.HK"]},{"tv":"NASDAQ:TSLA","stooq":["tsla.us"],"yahoo":["TSLA"]},{"tv":"NASDAQ:TQQQ","stooq":["tqqq.us"],"yahoo":["TQQQ"]},{"tv":"BITSTAMP:BTCUSD","stooq":["btcusd"],"yahoo":["BTC-USD"]},{"tv":"NASDAQ:QUBT","stooq":["qubt.us"],"yahoo":["QUBT"]},{"tv":"NASDAQ:AXTI","stooq":["axti.us"],"yahoo":["AXTI"]},{"tv":"NASDAQ:LUNR","stooq":["lunr.us"],"yahoo":["LUNR"]},{"tv":"NASDAQ:MBLY","stooq":["mbly.us"],"yahoo":["MBLY"]},{"tv":"NASDAQ:DUOL","stooq":["duol.us"],"yahoo":["DUOL"]},{"tv":"NYSE:FOUR","stooq":["four.us"],"yahoo":["FOUR"]},{"tv":"NYSE:F","stooq":["f.us"],"yahoo":["F"]},{"tv":"NASDAQ:HON","stooq":["hon.us"],"yahoo":["HON"]},{"tv":"NASDAQ:GOOG","stooq":["goog.us"],"yahoo":["GOOG"]},{"tv":"NASDAQ:NDX","stooq":["^ndx"],"yahoo":["^NDX"]},{"tv":"SPCFD:SPX","stooq":["^spx"],"yahoo":["^SPX","^GSPC"]},{"tv":"NQ=F","stooq":["nq.f"],"yahoo":["NQ=F"]},{"tv":"CBOE:UVIX","stooq":["uvix.us"],"yahoo":["UVIX"]},{"tv":"NASDAQ:PHO","stooq":["pho.us"],"yahoo":["PHO"]},{"tv":"NASDAQ:PIO","stooq":["pio.us"],"yahoo":["PIO"]},{"tv":"AMEX:CGW","stooq":["cgw.us"],"yahoo":["CGW"]},{"tv":"NASDAQ:AQWA","stooq":["aqwa.us"],"yahoo":["AQWA"]},{"tv":"AMEX:CPER","stooq":["cper.us"],"yahoo":["CPER"]},{"tv":"LSE:BRK-A","stooq":["brk-a.us"],"yahoo":["BRK-A"]},{"tv":"NYSE:ANET","stooq":["anet.us"],"yahoo":["ANET"]},{"tv":"NASDAQ:QCOM","stooq":["qcom.us"],"yahoo":["QCOM"]},{"tv":"NYSE:UNH","stooq":["unh.us"],"yahoo":["UNH"]},{"tv":"NASDAQ:TXN","stooq":["txn.us"],"yahoo":["TXN"]},{"tv":"NASDAQ:ADBE","stooq":["adbe.us"],"yahoo":["ADBE"]},{"tv":"NYSE:AXP","stooq":["axp.us"],"yahoo":["AXP"]},{"tv":"LSE:BRK-B","stooq":["brk-b.us"],"yahoo":["BRK-B"]},{"tv":"NYSE:NVO","stooq":["nvo.us"],"yahoo":["NVO"]},{"tv":"NYSE:KO","stooq":["ko.us"],"yahoo":["KO"]},{"tv":"NASDAQ:PEP","stooq":["pep.us"],"yahoo":["PEP"]},{"tv":"NASDAQ:WMT","stooq":["wmt.us"],"yahoo":["WMT"]},{"tv":"NASDAQ:CSCO","stooq":["csco.us"],"yahoo":["CSCO"]},{"tv":"NYSE:FDX","stooq":["fdx.us"],"yahoo":["FDX"]},{"tv":"NASDAQ:PYPL","stooq":["pypl.us"],"yahoo":["PYPL"]},{"tv":"NASDAQ:WDAY","stooq":["wday.us"],"yahoo":["WDAY"]},{"tv":"NYSE:BSX","stooq":["bsx.us"],"yahoo":["BSX"]},{"tv":"NYSE:STE","stooq":["ste.us"],"yahoo":["STE"]},{"tv":"NYSE:BR","stooq":["br.us"],"yahoo":["BR"]},{"tv":"NASDAQ:INTC","stooq":["intc.us"],"yahoo":["INTC"]},{"tv":"NYSE:BA","stooq":["ba.us"],"yahoo":["BA"]},{"tv":"NYSE:HUM","stooq":["hum.us"],"yahoo":["HUM"]},{"tv":"NASDAQ:KHC","stooq":["khc.us"],"yahoo":["KHC"]},{"tv":"NYSE:ARE","stooq":["are.us"],"yahoo":["ARE"]},{"tv":"NYSE:MLM","stooq":["mlm.us"],"yahoo":["MLM"]},{"tv":"NYSE:COHR","stooq":["cohr.us"],"yahoo":["COHR"]},{"tv":"NASDAQ:LITE","stooq":["lite.us"],"yahoo":["LITE"]},{"tv":"NASDAQ:MCHP","stooq":["mchp.us"],"yahoo":["MCHP"]},{"tv":"NYSE:PPG","stooq":["ppg.us"],"yahoo":["PPG"]},{"tv":"NYSE:GDDY","stooq":["gddy.us"],"yahoo":["GDDY"]},{"tv":"NASDAQ:GEN","stooq":["gen.us"],"yahoo":["GEN"]},{"tv":"NYSE:CIEN","stooq":["cien.us"],"yahoo":["CIEN"]},{"tv":"NYSE:COR","stooq":["cor.us"],"yahoo":["COR"]},{"tv":"NYSE:BABA","stooq":["baba.us"],"yahoo":["BABA"]},{"tv":"NASDAQ:BIDU","stooq":["bidu.us"],"yahoo":["BIDU"]},{"tv":"NASDAQ:JD","stooq":["jd.us"],"yahoo":["JD"]},{"tv":"NASDAQ:BILI","stooq":["bili.us"],"yahoo":["BILI"]},{"tv":"NYSE:TME","stooq":["tme.us"],"yahoo":["TME"]},{"tv":"OTC:TCEHY","stooq":["tcehy.us"],"yahoo":["TCEHY"]},{"tv":"NYSE:EDU","stooq":["edu.us"],"yahoo":["EDU"]},{"tv":"NASDAQ:GRAB","stooq":["grab.us"],"yahoo":["GRAB"]},{"tv":"NASDAQ:ZLAB","stooq":["zlab.us"],"yahoo":["ZLAB"]},{"tv":"BGNE","stooq":["bgne.us","onc.us"],"yahoo":["BGNE","ONC"]},{"tv":"AMEX:FXI","stooq":["fxi.us"],"yahoo":["FXI"]},{"tv":"NASDAQ:MCHI","stooq":["mchi.us"],"yahoo":["MCHI"]},{"tv":"AMEX:KWEB","stooq":["kweb.us"],"yahoo":["KWEB"]},{"tv":"SSE:000300","stooq":[],"yahoo":["000300.SS"]},{"tv":"TPEX:00845B","stooq":[],"yahoo":["00845B.TWO"]},{"tv":"TWSE:00885","stooq":[],"yahoo":["00885.TW"]},{"tv":"HKEX:0700","stooq":["0700.hk"],"yahoo":["0700.HK"]},{"tv":"HKEX:1211","stooq":["1211.hk"],"yahoo":["1211.HK"]},{"tv":"HKEX:1477","stooq":["1477.hk"],"yahoo":["1477.HK"]},{"tv":"TSE:268A","stooq":["268a.jp"],"yahoo":["268A.T"]},{"tv":"HKEX:2801","stooq":["2801.hk"],"yahoo":["2801.HK"]},{"tv":"SZSE:300122","stooq":[],"yahoo":["300122.SZ"]},{"tv":"SZSE:300142","stooq":[],"yahoo":["300142.SZ"]},{"tv":"SZSE:300601","stooq":[],"yahoo":["300601.SZ"]},{"tv":"HKEX:3067","stooq":["3067.hk"],"yahoo":["3067.HK"]},{"tv":"HKEX:3088","stooq":["3088.hk"],"yahoo":["3088.HK"]},{"tv":"SSE:600196","stooq":[],"yahoo":["600196.SS"]},{"tv":"TSE:6125","stooq":["6125.jp"],"yahoo":["6125.T"]},{"tv":"SSE:688755","stooq":[],"yahoo":["688755.SS"]},{"tv":"HKEX:9626","stooq":["9626.hk"],"yahoo":["9626.HK"]},{"tv":"HKEX:9988","stooq":["9988.hk"],"yahoo":["9988.HK"]},{"tv":"LSE:ASC","stooq":["asc.uk"],"yahoo":["ASC.L"]},{"tv":"OTC:ASOMY","stooq":["asomy.us"],"yahoo":["ASOMY"]},{"tv":"MIL:BF-B","stooq":[],"yahoo":["BF-B.MI","BF.MI"]},{"tv":"BME:CLR","stooq":[],"yahoo":["CLR.MC"]},{"tv":"LSE:DEBS","stooq":["debs.uk"],"yahoo":["DEBS.L"]},{"tv":"SIX:NESN","stooq":[],"yahoo":["NESN.SW"]},{"tv":"LSE:SVT","stooq":["svt.uk"],"yahoo":["SVT.L"]},{"tv":"EURONEXT:VIE","stooq":[],"yahoo":["VIE.PA"]},{"tv":"OTC:RGAKF","stooq":["rgakf.us"],"yahoo":["RGAKF"]},{"tv":"QSE:MFMS","stooq":[],"yahoo":["MFMS.QA"]},{"tv":"NASDAQ:ZM","stooq":["zm.us"],"yahoo":["ZM"]},{"tv":"NASDAQ:BYND","stooq":["bynd.us"],"yahoo":["BYND"]},{"tv":"NASDAQ:MRNA","stooq":["mrna.us"],"yahoo":["MRNA"]},{"tv":"NASDAQ:BNTX","stooq":["bntx.us"],"yahoo":["BNTX"]},{"tv":"CFI:CVAC","stooq":["cvac.us"],"yahoo":["CVAC"]},{"tv":"NASDAQ:PACB","stooq":["pacb.us"],"yahoo":["PACB"]},{"tv":"NASDAQ:CRVS","stooq":["crvs.us"],"yahoo":["CRVS"]},{"tv":"NYSE:GME","stooq":["gme.us"],"yahoo":["GME"]},{"tv":"NASDAQ:SARK","stooq":["sark.us"],"yahoo":["SARK"]},{"tv":"ERUS","stooq":["erus.us"],"yahoo":["ERUS"]},{"tv":"MANA-USD","stooq":[],"yahoo":["MANA-USD"]},{"tv":"JJC","stooq":["jjc.us"],"yahoo":["JJC"]},{"tv":"CBOE:TMFC","stooq":["tmfc.us"],"yahoo":["TMFC"]},{"tv":"NASDAQ:ROKU","stooq":["roku.us"],"yahoo":["ROKU"]},{"tv":"NASDAQ:DKNG","stooq":["dkng.us"],"yahoo":["DKNG"]},{"tv":"NASDAQ:WYNN","stooq":["wynn.us"],"yahoo":["WYNN"]},{"tv":"NASDAQ:TTD","stooq":["ttd.us"],"yahoo":["TTD"]},{"tv":"NYSE:RBLX","stooq":["rblx.us"],"yahoo":["RBLX"]},{"tv":"NYSE:WSM","stooq":["wsm.us"],"yahoo":["WSM"]},{"tv":"NYSE:IVZ","stooq":["ivz.us"],"yahoo":["IVZ"]},{"tv":"NASDAQ:DJCO","stooq":["djco.us"],"yahoo":["DJCO"]},{"tv":"NASDAQ:EWBC","stooq":["ewbc.us"],"yahoo":["EWBC"]},{"tv":"NYSE:DIS","stooq":["dis.us"],"yahoo":["DIS"]},{"tv":"NYSE:C","stooq":["c.us"],"yahoo":["C"]},{"tv":"NYSE:GE","stooq":["ge.us"],"yahoo":["GE"]},{"tv":"NYSE:PFE","stooq":["pfe.us"],"yahoo":["PFE"]},{"tv":"NYSE:AMT","stooq":["amt.us"],"yahoo":["AMT"]},{"tv":"NYSE:MKL","stooq":["mkl.us"],"yahoo":["MKL"]},{"tv":"NYSE:OXY","stooq":["oxy.us"],"yahoo":["OXY"]},{"tv":"NYSE:MPLX","stooq":["mplx.us"],"yahoo":["MPLX"]},{"tv":"NYSE:KMI","stooq":["kmi.us"],"yahoo":["KMI"]},{"tv":"NYSE:CW","stooq":["cw.us"],"yahoo":["CW"]},{"tv":"NYSE:MP","stooq":["mp.us"],"yahoo":["MP"]},{"tv":"NYSE:HIMS","stooq":["hims.us"],"yahoo":["HIMS"]},{"tv":"NYSE:SG","stooq":["sg.us"],"yahoo":["SG"]},{"tv":"NYSE:CRCL","stooq":["crcl.us"],"yahoo":["CRCL"]},{"tv":"NASDAQ:SPCX","stooq":["spcx.us"],"yahoo":["SPCX"]},{"tv":"NYSE:NOK","stooq":["nok.us"],"yahoo":["NOK"]},{"tv":"AMEX:VWO","stooq":["vwo.us"],"yahoo":["VWO"]},{"tv":"AMEX:VEA","stooq":["vea.us"],"yahoo":["VEA"]},{"tv":"CBOE:IEFA","stooq":["iefa.us"],"yahoo":["IEFA"]},{"tv":"AMEX:IEUR","stooq":["ieur.us"],"yahoo":["IEUR"]},{"tv":"CBOE:ARKK","stooq":["arkk.us"],"yahoo":["ARKK"]},{"tv":"CBOE:ARKG","stooq":["arkg.us"],"yahoo":["ARKG"]}]

OUTDIR = os.path.join(os.getcwd(), "watchlist_data")
D1 = "20240601"           # start date for stooq (gives ~530 trading days)
YR = "3y"                 # yahoo range
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
CTX = ssl.create_default_context()

def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            return r.read().decode("utf-8", "replace")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        return ""
    except ssl.SSLError:
        ctx2 = ssl.create_default_context(); ctx2.check_hostname = False
        ctx2.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=timeout, context=ctx2) as r:
            return r.read().decode("utf-8", "replace")

def try_stooq(code):
    url = "https://stooq.com/q/d/l/?s={}&d1={}&d2={}&i=d".format(code, D1, datetime.now().strftime("%Y%m%d"))
    txt = http_get(url)
    low = txt.lower()
    if "exceeded the daily hits limit" in low:
        return "QUOTA", None
    if not txt or not txt.startswith("Date,") or txt.count("\n") < 30:
        return "EMPTY", None
    rows = []
    for r in csv.DictReader(io.StringIO(txt)):
        try:
            rows.append([r["Date"], float(r["Open"]), float(r["High"]),
                         float(r["Low"]), float(r["Close"]),
                         float(r.get("Volume") or 0)])
        except (ValueError, KeyError):
            continue
    return ("OK", rows) if len(rows) >= 30 else ("EMPTY", None)

def try_yahoo(code):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/{}"
           "?range={}&interval=1d&events=div%2Csplit".format(urllib.parse.quote(code), YR))
    txt = http_get(url)
    if not txt:
        return "EMPTY", None
    try:
        j = json.loads(txt)
        res = j["chart"]["result"][0]
        ts = res["timestamp"]
        q = res["indicators"]["quote"][0]
        off = res["meta"].get("gmtoffset", 0)
        rows = []
        for i, t in enumerate(ts):
            o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
            if None in (o, h, l, c):
                continue
            d = datetime.fromtimestamp(t + off, tz=timezone.utc).strftime("%Y-%m-%d")
            v = q["volume"][i] or 0
            rows.append([d, float(o), float(h), float(l), float(c), float(v)])
        return ("OK", rows) if len(rows) >= 30 else ("EMPTY", None)
    except Exception:
        return "EMPTY", None

def main():
    os.makedirs(OUTDIR, exist_ok=True)
    manifest_path = os.path.join(OUTDIR, "manifest.json")
    manifest = json.load(open(manifest_path)) if os.path.exists(manifest_path) else {}
    stooq_dead = False
    n = len(SYMBOLS)
    for i, s in enumerate(SYMBOLS, 1):
        tv = s["tv"]
        fname = tv.replace(":", "_").replace("=", "_").replace("/", "_") + ".csv"
        fpath = os.path.join(OUTDIR, fname)
        if tv in manifest and manifest[tv].get("status") == "ok" and os.path.exists(fpath):
            print("[{}/{}] {} already done, skipping".format(i, n, tv)); continue
        got, src, code_used = None, None, None
        if not stooq_dead:
            for code in s["stooq"]:
                try:
                    st, rows = try_stooq(code)
                except Exception:
                    st, rows = "EMPTY", None
                if st == "QUOTA":
                    stooq_dead = True
                    print("  !! Stooq daily quota hit - switching to Yahoo for the rest")
                    break
                if st == "OK":
                    got, src, code_used = rows, "stooq", code; break
                time.sleep(0.3)
        if got is None:
            for code in s["yahoo"]:
                try:
                    st, rows = try_yahoo(code)
                except Exception:
                    st, rows = "EMPTY", None
                if st == "OK":
                    got, src, code_used = rows, "yahoo", code; break
                time.sleep(0.3)
        if got is None:
            manifest[tv] = {"status": "failed", "file": None, "source": None}
            print("[{}/{}] {}  FAILED (no data from any source)".format(i, n, tv))
        else:
            with open(fpath, "w", newline="") as f:
                w = csv.writer(f); w.writerow(["Date", "Open", "High", "Low", "Close", "Volume"])
                w.writerows(got)
            manifest[tv] = {"status": "ok", "file": fname, "source": src,
                            "source_code": code_used, "rows": len(got),
                            "first": got[0][0], "last": got[-1][0]}
            print("[{}/{}] {}  {} rows from {} ({} .. {})".format(
                i, n, tv, len(got), src, got[0][0], got[-1][0]))
        json.dump(manifest, open(manifest_path, "w"), indent=1)
        time.sleep(0.35)
    manifest["_meta"] = {"generated_utc": datetime.now(timezone.utc).isoformat(),
                         "script_version": "1.1"}
    json.dump(manifest, open(manifest_path, "w"), indent=1)
    zpath = os.path.join(os.path.dirname(OUTDIR), "watchlist_data.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for fn in sorted(os.listdir(OUTDIR)):
            z.write(os.path.join(OUTDIR, fn), fn)
    ok = sum(1 for k, v in manifest.items() if isinstance(v, dict) and v.get("status") == "ok")
    fail = [k for k, v in manifest.items() if isinstance(v, dict) and v.get("status") == "failed"]
    print("\nDONE: {} ok, {} failed".format(ok, len(fail)))
    if fail:
        print("Failed symbols (will be flagged in the report):")
        for k in fail: print("  -", k)
    print("\n==> Upload this file to the chat:\n    " + zpath)

if __name__ == "__main__":
    try:
        import urllib.parse  # noqa
        main()
    except KeyboardInterrupt:
        print("\nInterrupted - re-run to resume where it stopped.")
