#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_watchlist_data.py  -  Watchlist OHLCV downloader (v1.3, 2026-07-25)
For: drphy68 pre-open watchlist scan (Weekend Mode run)

WHAT IT DOES
  Downloads ~2 years of daily OHLCV bars for 224 watchlist symbols from
  Yahoo Finance (sole source - Stooq formally retired v1.3, see changelog),
  saves one CSV per symbol, writes a manifest of what came from where, and
  zips everything into watchlist_data.zip in the same folder.

HOW TO RUN (needs only Python 3.8+, no extra installs)
  Windows :  py fetch_watchlist_data.py
  Mac     :  python3 fetch_watchlist_data.py
  Takes roughly 3-6 minutes. Then upload watchlist_data.zip to the chat.

It only READS public price data and writes files into a new subfolder
"watchlist_data" next to itself.

v1.3 (2026-07-25) - STOOQ RETIRED (OWNER RULING: "try once to repair, failing
  which retire it")
  ONE repair attempt was made and failed, so Stooq is now formally retired:
    - Every production run this pipeline has ever recorded shows
      source_counts = {"yahoo": 219} - zero symbols from Stooq, not a recent
      blip (see Pipeline_Lag_2026-07-25.md).
    - The request code was reviewed for a fixable defect and none was found:
      try_stooq() uses the correct CSV endpoint, the same browser User-Agent
      that succeeds for Yahoo from the identical GitHub Actions run, and
      correct CSV parsing. Same header, same code path, same host class -
      only Stooq fails, which points at Stooq itself (its own
      rate limiting / anti-bot policy against shared cloud IP ranges,
      consistent with the historical "exceeded the daily hits limit"
      message this script already had to special-case), not a bug here.
    - Two independent network paths were tested live on 2026-07-25 and both
      were inconclusive by policy, not by evidence: this session's own
      sandbox blocks the market-data domain class outright (Yahoo included,
      so it cannot isolate a Stooq-specific problem), and Anthropic's
      WebFetch tool refuses stooq.com under its own robots.txt policy. This
      pipeline's actual execution host is GitHub Actions, which the manifest
      evidence above already covers directly - no live retest was needed
      there because the production record already answers the question with
      a large, cost-free sample (every run, not one probe).
  CHANGE: `stooq_dead` now starts True, so try_stooq() is never called and
  Yahoo is attempted first for every symbol. The `stooq` key stays in
  SYMBOLS and try_stooq()/fetch_one() are left in place, dormant, so this
  is reversible in one line if a genuinely working replacement is ever
  needed. No change to the Yahoo request path, the CSV schema, any manifest
  key's meaning, or any file this script does not own. classify() and every
  ratified scan parameter are untouched (this script never imports or calls
  either).

v1.2 (2026-07-25) - US-SESSION FRESHNESS GUARD
  On 2026-07-25 a run at 09:13 UTC produced a manifest in which all 185
  US-listed symbols ended at Thursday 2026-07-23 while all 31 non-US
  symbols ended at Friday 2026-07-24 - i.e. the US leg was exactly one
  session behind. The downstream scan's freshness gate (SPY last bar ==
  most recent completed US session) therefore blocked every run.
  v1.2 does three things about that:
    (a) computes the most recent COMPLETED US session itself;
    (b) after the first pass, re-fetches ONLY the US symbols that fall
        short, in bounded rounds, rotating the Yahoo host and adding a
        cache-buster, never accepting a result older than what it holds;
    (c) records the outcome in manifest["_meta"] so the scan and the
        owner can tell "source lag" from "pipeline broken" without
        reading Action logs.
  It does NOT change the CSV schema or any existing manifest key, and it
  never synthesises a bar. If the source does not have the session, the
  manifest says so.

  The resume-skip that made this script safe to re-run by hand is now
  OPT-IN (set WL_RESUME=1). In CI it was inert only because the CSVs are
  not committed; had they ever been committed it would have frozen the
  data permanently while still refreshing generated_utc.
"""
import csv, io, json, os, ssl, sys, time, urllib.request, urllib.error, zipfile
from datetime import datetime, timedelta, timezone

SYMBOLS = [{"tv":"AMEX:SPY","stooq":["spy.us"],"yahoo":["SPY"]},{"tv":"NASDAQ:QQQ","stooq":["qqq.us"],"yahoo":["QQQ"]},{"tv":"AMEX:IWM","stooq":["iwm.us"],"yahoo":["IWM"]},{"tv":"AMEX:DIA","stooq":["dia.us"],"yahoo":["DIA"]},{"tv":"AMEX:XLF","stooq":["xlf.us"],"yahoo":["XLF"]},{"tv":"AMEX:XLE","stooq":["xle.us"],"yahoo":["XLE"]},{"tv":"NASDAQ:SOXX","stooq":["soxx.us"],"yahoo":["SOXX"]},{"tv":"CBOE:VIX","stooq":["^vix"],"yahoo":["^VIX"]},{"tv":"ICEUS:DXY","stooq":[],"yahoo":["DX-Y.NYB"]},{"tv":"OANDA:XAUUSD","stooq":["xauusd"],"yahoo":["XAUUSD=X","GC=F"]},{"tv":"NASDAQ:NVDA","stooq":["nvda.us"],"yahoo":["NVDA"]},{"tv":"NASDAQ:MSFT","stooq":["msft.us"],"yahoo":["MSFT"]},{"tv":"NASDAQ:AAPL","stooq":["aapl.us"],"yahoo":["AAPL"]},{"tv":"NASDAQ:AMZN","stooq":["amzn.us"],"yahoo":["AMZN"]},{"tv":"NASDAQ:META","stooq":["meta.us"],"yahoo":["META"]},{"tv":"NASDAQ:GOOGL","stooq":["googl.us"],"yahoo":["GOOGL"]},{"tv":"NASDAQ:AMD","stooq":["amd.us"],"yahoo":["AMD"]},{"tv":"NASDAQ:AVGO","stooq":["avgo.us"],"yahoo":["AVGO"]},{"tv":"NYSE:TSM","stooq":["tsm.us"],"yahoo":["TSM"]},{"tv":"NASDAQ:MU","stooq":["mu.us"],"yahoo":["MU"]},{"tv":"NYSE:VST","stooq":["vst.us"],"yahoo":["VST"]},{"tv":"NASDAQ:CEG","stooq":["ceg.us"],"yahoo":["CEG"]},{"tv":"NYSE:VRT","stooq":["vrt.us"],"yahoo":["VRT"]},{"tv":"NYSE:GEV","stooq":["gev.us"],"yahoo":["GEV"]},{"tv":"NYSE:ETN","stooq":["etn.us"],"yahoo":["ETN"]},{"tv":"NYSE:NRG","stooq":["nrg.us"],"yahoo":["NRG"]},{"tv":"NYSE:BE","stooq":["be.us"],"yahoo":["BE"]},{"tv":"NASDAQ:POWL","stooq":["powl.us"],"yahoo":["POWL"]},{"tv":"NASDAQ:ASML","stooq":["asml.us"],"yahoo":["ASML"]},{"tv":"NASDAQ:ARM","stooq":["arm.us"],"yahoo":["ARM"]},{"tv":"NASDAQ:MRVL","stooq":["mrvl.us"],"yahoo":["MRVL"]},{"tv":"NASDAQ:WDC","stooq":["wdc.us"],"yahoo":["WDC"]},{"tv":"NASDAQ:SNDK","stooq":["sndk.us"],"yahoo":["SNDK"]},{"tv":"NASDAQ:TER","stooq":["ter.us"],"yahoo":["TER"]},{"tv":"NASDAQ:PLTR","stooq":["pltr.us"],"yahoo":["PLTR"]},{"tv":"NASDAQ:CRWD","stooq":["crwd.us"],"yahoo":["CRWD"]},{"tv":"NYSE:NOW","stooq":["now.us"],"yahoo":["NOW"]},{"tv":"NYSE:CRM","stooq":["crm.us"],"yahoo":["CRM"]},{"tv":"NYSE:SNOW","stooq":["snow.us"],"yahoo":["SNOW"]},{"tv":"NASDAQ:HOOD","stooq":["hood.us"],"yahoo":["HOOD"]},{"tv":"NYSE:FCX","stooq":["fcx.us"],"yahoo":["FCX"]},{"tv":"AMEX:GDX","stooq":["gdx.us"],"yahoo":["GDX"]},{"tv":"NASDAQ:FANG","stooq":["fang.us"],"yahoo":["FANG"]},{"tv":"NYSE:SCCO","stooq":["scco.us"],"yahoo":["SCCO"]},{"tv":"NYSE:HBM","stooq":["hbm.us"],"yahoo":["HBM"]},{"tv":"NYSE:BAC","stooq":["bac.us"],"yahoo":["BAC"]},{"tv":"NYSE:JPM","stooq":["jpm.us"],"yahoo":["JPM"]},{"tv":"NYSE:GS","stooq":["gs.us"],"yahoo":["GS"]},{"tv":"NASDAQ:HONA","stooq":["hona.us"],"yahoo":["HONA"]},{"tv":"NYSE:VGNT","stooq":["vgnt.us"],"yahoo":["VGNT"]},{"tv":"NYSE:OKLO","stooq":["oklo.us"],"yahoo":["OKLO"]},{"tv":"NASDAQ:WULF","stooq":["wulf.us"],"yahoo":["WULF"]},{"tv":"NASDAQ:MSTR","stooq":["mstr.us"],"yahoo":["MSTR"]},{"tv":"NASDAQ:RKLB","stooq":["rklb.us"],"yahoo":["RKLB"]},{"tv":"NYSE:CVNA","stooq":["cvna.us"],"yahoo":["CVNA"]},{"tv":"NYSE:V","stooq":["v.us"],"yahoo":["V"]},{"tv":"NYSE:MA","stooq":["ma.us"],"yahoo":["MA"]},{"tv":"NYSE:ICE","stooq":["ice.us"],"yahoo":["ICE"]},{"tv":"NASDAQ:MNST","stooq":["mnst.us"],"yahoo":["MNST"]},{"tv":"NASDAQ:PAYX","stooq":["payx.us"],"yahoo":["PAYX"]},{"tv":"NASDAQ:ADP","stooq":["adp.us"],"yahoo":["ADP"]},{"tv":"NASDAQ:GILD","stooq":["gild.us"],"yahoo":["GILD"]},{"tv":"NYSE:DHR","stooq":["dhr.us"],"yahoo":["DHR"]},{"tv":"NASDAQ:ADI","stooq":["adi.us"],"yahoo":["ADI"]},{"tv":"NYSE:CB","stooq":["cb.us"],"yahoo":["CB"]},{"tv":"NYSE:TJX","stooq":["tjx.us"],"yahoo":["TJX"]},{"tv":"NASDAQ:COST","stooq":["cost.us"],"yahoo":["COST"]},{"tv":"NYSE:MCD","stooq":["mcd.us"],"yahoo":["MCD"]},{"tv":"NYSE:XYL","stooq":["xyl.us"],"yahoo":["XYL"]},{"tv":"NYSE:AWK","stooq":["awk.us"],"yahoo":["AWK"]},{"tv":"NYSE:WTRG","stooq":["wtrg.us"],"yahoo":["WTRG"]},{"tv":"NYSE:ECL","stooq":["ecl.us"],"yahoo":["ECL"]},{"tv":"NYSE:PNR","stooq":["pnr.us"],"yahoo":["PNR"]},{"tv":"NYSE:MWA","stooq":["mwa.us"],"yahoo":["MWA"]},{"tv":"NASDAQ:ERII","stooq":["erii.us"],"yahoo":["ERII"]},{"tv":"NYSE:VLTO","stooq":["vlto.us"],"yahoo":["VLTO"]},{"tv":"AMEX:FIW","stooq":["fiw.us"],"yahoo":["FIW"]},{"tv":"NYSE:BHP","stooq":["bhp.us"],"yahoo":["BHP"]},{"tv":"AMEX:COPX","stooq":["copx.us"],"yahoo":["COPX"]},{"tv":"NYSE:BAM","stooq":["bam.us"],"yahoo":["BAM"]},{"tv":"NYSE:BX","stooq":["bx.us"],"yahoo":["BX"]},{"tv":"SGX:D05","stooq":[],"yahoo":["D05.SI"]},{"tv":"SGX:ES3","stooq":[],"yahoo":["ES3.SI"]},{"tv":"SGX:C6L","stooq":[],"yahoo":["C6L.SI"]},{"tv":"HKEX:9926","stooq":["9926.hk"],"yahoo":["9926.HK"]},{"tv":"NASDAQ:TSLA","stooq":["tsla.us"],"yahoo":["TSLA"]},{"tv":"NASDAQ:TQQQ","stooq":["tqqq.us"],"yahoo":["TQQQ"]},{"tv":"BITSTAMP:BTCUSD","stooq":["btcusd"],"yahoo":["BTC-USD"]},{"tv":"NASDAQ:QUBT","stooq":["qubt.us"],"yahoo":["QUBT"]},{"tv":"NASDAQ:AXTI","stooq":["axti.us"],"yahoo":["AXTI"]},{"tv":"NASDAQ:LUNR","stooq":["lunr.us"],"yahoo":["LUNR"]},{"tv":"NASDAQ:MBLY","stooq":["mbly.us"],"yahoo":["MBLY"]},{"tv":"NASDAQ:DUOL","stooq":["duol.us"],"yahoo":["DUOL"]},{"tv":"NYSE:FOUR","stooq":["four.us"],"yahoo":["FOUR"]},{"tv":"NYSE:F","stooq":["f.us"],"yahoo":["F"]},{"tv":"NASDAQ:HON","stooq":["hon.us"],"yahoo":["HON"]},{"tv":"NASDAQ:GOOG","stooq":["goog.us"],"yahoo":["GOOG"]},{"tv":"NASDAQ:NDX","stooq":["^ndx"],"yahoo":["^NDX"]},{"tv":"SPCFD:SPX","stooq":["^spx"],"yahoo":["^SPX","^GSPC"]},{"tv":"NQ=F","stooq":["nq.f"],"yahoo":["NQ=F"]},{"tv":"CBOE:UVIX","stooq":["uvix.us"],"yahoo":["UVIX"]},{"tv":"NASDAQ:PHO","stooq":["pho.us"],"yahoo":["PHO"]},{"tv":"NASDAQ:PIO","stooq":["pio.us"],"yahoo":["PIO"]},{"tv":"AMEX:CGW","stooq":["cgw.us"],"yahoo":["CGW"]},{"tv":"NASDAQ:AQWA","stooq":["aqwa.us"],"yahoo":["AQWA"]},{"tv":"AMEX:CPER","stooq":["cper.us"],"yahoo":["CPER"]},{"tv":"LSE:BRK-A","stooq":["brk-a.us"],"yahoo":["BRK-A"]},{"tv":"NYSE:ANET","stooq":["anet.us"],"yahoo":["ANET"]},{"tv":"NASDAQ:QCOM","stooq":["qcom.us"],"yahoo":["QCOM"]},{"tv":"NYSE:UNH","stooq":["unh.us"],"yahoo":["UNH"]},{"tv":"NASDAQ:TXN","stooq":["txn.us"],"yahoo":["TXN"]},{"tv":"NASDAQ:ADBE","stooq":["adbe.us"],"yahoo":["ADBE"]},{"tv":"NYSE:AXP","stooq":["axp.us"],"yahoo":["AXP"]},{"tv":"LSE:BRK-B","stooq":["brk-b.us"],"yahoo":["BRK-B"]},{"tv":"NYSE:NVO","stooq":["nvo.us"],"yahoo":["NVO"]},{"tv":"NYSE:KO","stooq":["ko.us"],"yahoo":["KO"]},{"tv":"NASDAQ:PEP","stooq":["pep.us"],"yahoo":["PEP"]},{"tv":"NASDAQ:WMT","stooq":["wmt.us"],"yahoo":["WMT"]},{"tv":"NASDAQ:CSCO","stooq":["csco.us"],"yahoo":["CSCO"]},{"tv":"NYSE:FDX","stooq":["fdx.us"],"yahoo":["FDX"]},{"tv":"NASDAQ:PYPL","stooq":["pypl.us"],"yahoo":["PYPL"]},{"tv":"NASDAQ:WDAY","stooq":["wday.us"],"yahoo":["WDAY"]},{"tv":"NYSE:BSX","stooq":["bsx.us"],"yahoo":["BSX"]},{"tv":"NYSE:STE","stooq":["ste.us"],"yahoo":["STE"]},{"tv":"NYSE:BR","stooq":["br.us"],"yahoo":["BR"]},{"tv":"NASDAQ:INTC","stooq":["intc.us"],"yahoo":["INTC"]},{"tv":"NYSE:BA","stooq":["ba.us"],"yahoo":["BA"]},{"tv":"NYSE:HUM","stooq":["hum.us"],"yahoo":["HUM"]},{"tv":"NASDAQ:KHC","stooq":["khc.us"],"yahoo":["KHC"]},{"tv":"NYSE:ARE","stooq":["are.us"],"yahoo":["ARE"]},{"tv":"NYSE:MLM","stooq":["mlm.us"],"yahoo":["MLM"]},{"tv":"NYSE:COHR","stooq":["cohr.us"],"yahoo":["COHR"]},{"tv":"NASDAQ:LITE","stooq":["lite.us"],"yahoo":["LITE"]},{"tv":"NASDAQ:MCHP","stooq":["mchp.us"],"yahoo":["MCHP"]},{"tv":"NYSE:PPG","stooq":["ppg.us"],"yahoo":["PPG"]},{"tv":"NYSE:GDDY","stooq":["gddy.us"],"yahoo":["GDDY"]},{"tv":"NASDAQ:GEN","stooq":["gen.us"],"yahoo":["GEN"]},{"tv":"NYSE:CIEN","stooq":["cien.us"],"yahoo":["CIEN"]},{"tv":"NYSE:COR","stooq":["cor.us"],"yahoo":["COR"]},{"tv":"NYSE:BABA","stooq":["baba.us"],"yahoo":["BABA"]},{"tv":"NASDAQ:BIDU","stooq":["bidu.us"],"yahoo":["BIDU"]},{"tv":"NASDAQ:JD","stooq":["jd.us"],"yahoo":["JD"]},{"tv":"NASDAQ:BILI","stooq":["bili.us"],"yahoo":["BILI"]},{"tv":"NYSE:TME","stooq":["tme.us"],"yahoo":["TME"]},{"tv":"OTC:TCEHY","stooq":["tcehy.us"],"yahoo":["TCEHY"]},{"tv":"NYSE:EDU","stooq":["edu.us"],"yahoo":["EDU"]},{"tv":"NASDAQ:GRAB","stooq":["grab.us"],"yahoo":["GRAB"]},{"tv":"NASDAQ:ZLAB","stooq":["zlab.us"],"yahoo":["ZLAB"]},{"tv":"BGNE","stooq":["bgne.us","onc.us"],"yahoo":["BGNE","ONC"]},{"tv":"AMEX:FXI","stooq":["fxi.us"],"yahoo":["FXI"]},{"tv":"NASDAQ:MCHI","stooq":["mchi.us"],"yahoo":["MCHI"]},{"tv":"AMEX:KWEB","stooq":["kweb.us"],"yahoo":["KWEB"]},{"tv":"SSE:000300","stooq":[],"yahoo":["000300.SS"]},{"tv":"TPEX:00845B","stooq":[],"yahoo":["00845B.TWO"]},{"tv":"TWSE:00885","stooq":[],"yahoo":["00885.TW"]},{"tv":"HKEX:0700","stooq":["0700.hk"],"yahoo":["0700.HK"]},{"tv":"HKEX:1211","stooq":["1211.hk"],"yahoo":["1211.HK"]},{"tv":"HKEX:1477","stooq":["1477.hk"],"yahoo":["1477.HK"]},{"tv":"TSE:268A","stooq":["268a.jp"],"yahoo":["268A.T"]},{"tv":"HKEX:2801","stooq":["2801.hk"],"yahoo":["2801.HK"]},{"tv":"SZSE:300122","stooq":[],"yahoo":["300122.SZ"]},{"tv":"SZSE:300142","stooq":[],"yahoo":["300142.SZ"]},{"tv":"SZSE:300601","stooq":[],"yahoo":["300601.SZ"]},{"tv":"HKEX:3067","stooq":["3067.hk"],"yahoo":["3067.HK"]},{"tv":"HKEX:3088","stooq":["3088.hk"],"yahoo":["3088.HK"]},{"tv":"SSE:600196","stooq":[],"yahoo":["600196.SS"]},{"tv":"TSE:6125","stooq":["6125.jp"],"yahoo":["6125.T"]},{"tv":"SSE:688755","stooq":[],"yahoo":["688755.SS"]},{"tv":"HKEX:9626","stooq":["9626.hk"],"yahoo":["9626.HK"]},{"tv":"HKEX:9988","stooq":["9988.hk"],"yahoo":["9988.HK"]},{"tv":"LSE:ASC","stooq":["asc.uk"],"yahoo":["ASC.L"]},{"tv":"OTC:ASOMY","stooq":["asomy.us"],"yahoo":["ASOMY"]},{"tv":"MIL:BF-B","stooq":[],"yahoo":["BF-B.MI","BF.MI"]},{"tv":"BME:CLR","stooq":[],"yahoo":["CLR.MC"]},{"tv":"LSE:DEBS","stooq":["debs.uk"],"yahoo":["DEBS.L"]},{"tv":"SIX:NESN","stooq":[],"yahoo":["NESN.SW"]},{"tv":"LSE:SVT","stooq":["svt.uk"],"yahoo":["SVT.L"]},{"tv":"EURONEXT:VIE","stooq":[],"yahoo":["VIE.PA"]},{"tv":"OTC:RGAKF","stooq":["rgakf.us"],"yahoo":["RGAKF"]},{"tv":"QSE:MFMS","stooq":[],"yahoo":["MFMS.QA"]},{"tv":"NASDAQ:ZM","stooq":["zm.us"],"yahoo":["ZM"]},{"tv":"NASDAQ:BYND","stooq":["bynd.us"],"yahoo":["BYND"]},{"tv":"NASDAQ:MRNA","stooq":["mrna.us"],"yahoo":["MRNA"]},{"tv":"NASDAQ:BNTX","stooq":["bntx.us"],"yahoo":["BNTX"]},{"tv":"CFI:CVAC","stooq":["cvac.us"],"yahoo":["CVAC"]},{"tv":"NASDAQ:PACB","stooq":["pacb.us"],"yahoo":["PACB"]},{"tv":"NASDAQ:CRVS","stooq":["crvs.us"],"yahoo":["CRVS"]},{"tv":"NYSE:GME","stooq":["gme.us"],"yahoo":["GME"]},{"tv":"NASDAQ:SARK","stooq":["sark.us"],"yahoo":["SARK"]},{"tv":"ERUS","stooq":["erus.us"],"yahoo":["ERUS"]},{"tv":"MANA-USD","stooq":[],"yahoo":["MANA-USD"]},{"tv":"JJC","stooq":["jjc.us"],"yahoo":["JJC"]},{"tv":"CBOE:TMFC","stooq":["tmfc.us"],"yahoo":["TMFC"]},{"tv":"NASDAQ:ROKU","stooq":["roku.us"],"yahoo":["ROKU"]},{"tv":"NASDAQ:DKNG","stooq":["dkng.us"],"yahoo":["DKNG"]},{"tv":"NASDAQ:WYNN","stooq":["wynn.us"],"yahoo":["WYNN"]},{"tv":"NASDAQ:TTD","stooq":["ttd.us"],"yahoo":["TTD"]},{"tv":"NYSE:RBLX","stooq":["rblx.us"],"yahoo":["RBLX"]},{"tv":"NYSE:WSM","stooq":["wsm.us"],"yahoo":["WSM"]},{"tv":"NYSE:IVZ","stooq":["ivz.us"],"yahoo":["IVZ"]},{"tv":"NASDAQ:DJCO","stooq":["djco.us"],"yahoo":["DJCO"]},{"tv":"NASDAQ:EWBC","stooq":["ewbc.us"],"yahoo":["EWBC"]},{"tv":"NYSE:DIS","stooq":["dis.us"],"yahoo":["DIS"]},{"tv":"NYSE:C","stooq":["c.us"],"yahoo":["C"]},{"tv":"NYSE:GE","stooq":["ge.us"],"yahoo":["GE"]},{"tv":"NYSE:PFE","stooq":["pfe.us"],"yahoo":["PFE"]},{"tv":"NYSE:AMT","stooq":["amt.us"],"yahoo":["AMT"]},{"tv":"NYSE:MKL","stooq":["mkl.us"],"yahoo":["MKL"]},{"tv":"NYSE:OXY","stooq":["oxy.us"],"yahoo":["OXY"]},{"tv":"NYSE:MPLX","stooq":["mplx.us"],"yahoo":["MPLX"]},{"tv":"NYSE:KMI","stooq":["kmi.us"],"yahoo":["KMI"]},{"tv":"NYSE:CW","stooq":["cw.us"],"yahoo":["CW"]},{"tv":"NYSE:MP","stooq":["mp.us"],"yahoo":["MP"]},{"tv":"NYSE:HIMS","stooq":["hims.us"],"yahoo":["HIMS"]},{"tv":"NYSE:SG","stooq":["sg.us"],"yahoo":["SG"]},{"tv":"NYSE:CRCL","stooq":["crcl.us"],"yahoo":["CRCL"]},{"tv":"NASDAQ:SPCX","stooq":["spcx.us"],"yahoo":["SPCX"]},{"tv":"NYSE:NOK","stooq":["nok.us"],"yahoo":["NOK"]},{"tv":"AMEX:VWO","stooq":["vwo.us"],"yahoo":["VWO"]},{"tv":"AMEX:VEA","stooq":["vea.us"],"yahoo":["VEA"]},{"tv":"CBOE:IEFA","stooq":["iefa.us"],"yahoo":["IEFA"]},{"tv":"AMEX:IEUR","stooq":["ieur.us"],"yahoo":["IEUR"]},{"tv":"CBOE:ARKK","stooq":["arkk.us"],"yahoo":["ARKK"]},{"tv":"CBOE:ARKG","stooq":["arkg.us"],"yahoo":["ARKG"]}]

OUTDIR = os.path.join(os.getcwd(), "watchlist_data")
D1 = "20240601"           # start date for stooq (gives ~530 trading days)
YR = "3y"                 # yahoo range
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
CTX = ssl.create_default_context()

# --------------------------------------------------------------------------
# v1.2 US-session freshness guard
# --------------------------------------------------------------------------
# US market holidays that fall on weekdays. Extend each year. A date listed
# here is treated as "no session"; being wrong in the conservative direction
# (listing a day that did trade) would make the guard demand an older bar,
# which is visible in _meta rather than silent.
US_HOLIDAYS = {
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
    "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31",
    "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
}
# A US session is treated as COMPLETE this many hours after 00:00 UTC on its
# own date. 21:15 UTC covers both a 20:00 UTC close (EDT) and a 21:00 UTC
# close (EST) with a small margin.
US_CLOSE_UTC_HOUR = 21.25
REF_US = "AMEX:SPY"                                  # the scan gates on this
MAX_ROUNDS = int(os.environ.get("WL_MAX_ROUNDS", "3"))
ROUND_WAIT = int(os.environ.get("WL_ROUND_WAIT", "600"))     # seconds
RESUME = os.environ.get("WL_RESUME", "") == "1"
YHOSTS = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]


def expected_us_session(now_utc=None):
    """Most recent COMPLETED US equity session, as YYYY-MM-DD."""
    now = now_utc or datetime.now(timezone.utc)
    d = now.date()
    # today only counts once its close has passed
    hours = now.hour + now.minute / 60.0
    if hours < US_CLOSE_UTC_HOUR:
        d = d - timedelta(days=1)
    for _ in range(12):
        s = d.strftime("%Y-%m-%d")
        if d.weekday() < 5 and s not in US_HOLIDAYS:
            return s
        d = d - timedelta(days=1)
    return d.strftime("%Y-%m-%d")


# Symbols the suffix rule below gets wrong. DXY (Yahoo "DX-Y.NYB") carries an
# exchange suffix but trades the US session and is a regime input for the scan.
US_FORCE = {"ICEUS:DXY"}
US_EXCLUDE = set()


def is_us_symbol(sym):
    """True if this symbol trades on the US equity session.

    Derived from the Yahoo code: US listings carry no exchange suffix.
    Anything with a dot suffix (.SI .HK .L .T .SS .SZ .MI .MC .SW .PA .TW
    .TWO .QA .NYB), a currency pair (=X), a future (=F) or a crypto pair
    (-USD) is excluded - those follow other calendars and are not what the
    scan's freshness gate keys on. Conservative by design: a US name wrongly
    excluded merely loses the retry, it is never fabricated.
    """
    if sym["tv"] in US_FORCE:
        return True
    if sym["tv"] in US_EXCLUDE:
        return False
    codes = sym.get("yahoo") or []
    if not codes:
        return False
    c = codes[0].upper()
    if c.endswith("=X") or c.endswith("=F") or c.endswith("-USD"):
        return False
    if c.startswith("^"):
        c = c[1:]
    return "." not in c


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

def try_yahoo(code, host=None, bust=None):
    url = ("https://{}/v8/finance/chart/{}"
           "?range={}&interval=1d&events=div%2Csplit".format(
               host or YHOSTS[0], urllib.parse.quote(code), YR))
    if bust:
        # defeat any CDN/edge cache holding a pre-close snapshot
        url += "&corsDomain=finance.yahoo.com&_={}".format(bust)
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

def fetch_one(sym, stooq_dead, yahoo_only=False, host=None, bust=None):
    """Return (rows, source, code_used, stooq_dead)."""
    got = src_used = code_used = None
    if not yahoo_only and not stooq_dead:
        for code in sym["stooq"]:
            try:
                st, rows = try_stooq(code)
            except Exception:
                st, rows = "EMPTY", None
            if st == "QUOTA":
                stooq_dead = True
                print("  !! Stooq daily quota hit - switching to Yahoo for the rest")
                break
            if st == "OK":
                got, src_used, code_used = rows, "stooq", code
                break
            time.sleep(0.3)
    if got is None:
        for code in sym["yahoo"]:
            try:
                st, rows = try_yahoo(code, host=host, bust=bust)
            except Exception:
                st, rows = "EMPTY", None
            if st == "OK":
                got, src_used, code_used = rows, "yahoo", code
                break
            time.sleep(0.3)
    return got, src_used, code_used, stooq_dead


def write_symbol(manifest, manifest_path, sym, rows, source, code_used, fpath, fname):
    with open(fpath, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Date", "Open", "High", "Low", "Close", "Volume"])
        w.writerows(rows)
    manifest[sym["tv"]] = {"status": "ok", "file": fname, "source": source,
                           "source_code": code_used, "rows": len(rows),
                           "first": rows[0][0], "last": rows[-1][0]}
    json.dump(manifest, open(manifest_path, "w"), indent=1)


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    manifest_path = os.path.join(OUTDIR, "manifest.json")
    manifest = json.load(open(manifest_path)) if os.path.exists(manifest_path) else {}
    expected = expected_us_session()
    print("Expected most recent COMPLETED US session: {}".format(expected))
    if RESUME:
        print("WL_RESUME=1: completed symbols will be skipped (manual-run mode)")

    stooq_dead = True  # v1.3: Stooq formally retired by owner ruling 2026-07-25 -
                        # repair attempt failed (see module docstring); Yahoo is
                        # now attempted first for every symbol. Flip to False only
                        # if a genuinely working fix or replacement is deployed.
    kept_previous = 0
    n = len(SYMBOLS)
    fname_of, fpath_of = {}, {}
    for s in SYMBOLS:
        fn = s["tv"].replace(":", "_").replace("=", "_").replace("/", "_") + ".csv"
        fname_of[s["tv"]] = fn
        fpath_of[s["tv"]] = os.path.join(OUTDIR, fn)

    # ---- pass 1: everything ------------------------------------------------
    for i, s in enumerate(SYMBOLS, 1):
        tv = s["tv"]
        fpath, fname = fpath_of[tv], fname_of[tv]
        if (RESUME and tv in manifest and manifest[tv].get("status") == "ok"
                and os.path.exists(fpath)):
            print("[{}/{}] {} already done, skipping".format(i, n, tv))
            continue
        held = manifest.get(tv) if isinstance(manifest.get(tv), dict) else {}
        prev_last = held.get("last") if held.get("status") == "ok" else None
        rows, source, code_used, stooq_dead = fetch_one(s, stooq_dead)
        if rows is None:
            if prev_last and os.path.exists(fpath):
                # a transient source outage must not destroy good held data
                kept_previous += 1
                print("[{}/{}] {}  fetch failed - KEEPING held data to {}".format(
                    i, n, tv, prev_last))
            else:
                manifest[tv] = {"status": "failed", "file": None, "source": None}
                json.dump(manifest, open(manifest_path, "w"), indent=1)
                print("[{}/{}] {}  FAILED (no data from any source)".format(i, n, tv))
        elif prev_last and os.path.exists(fpath) and rows[-1][0] < prev_last:
            # NEVER REGRESS: the source came back a session short of what the
            # last good zip already holds. Keep the held data.
            kept_previous += 1
            print("[{}/{}] {}  fetched {} < held {} - KEEPING held data".format(
                i, n, tv, rows[-1][0], prev_last))
        else:
            write_symbol(manifest, manifest_path, s, rows, source, code_used,
                         fpath, fname)
            print("[{}/{}] {}  {} rows from {} ({} .. {})".format(
                i, n, tv, len(rows), source, rows[0][0], rows[-1][0]))
        time.sleep(0.35)

    # ---- passes 2..N: US symbols that are short of the expected session ----
    us_syms = [s for s in SYMBOLS if is_us_symbol(s)]

    def short_list():
        out = []
        for s in us_syms:
            m = manifest.get(s["tv"])
            if isinstance(m, dict) and m.get("status") == "ok" and m.get("last") \
                    and m["last"] < expected:
                out.append(s)
        return out

    rounds_used = 1
    short = short_list()
    print("\nAfter pass 1: {} of {} US symbols short of {}".format(
        len(short), len(us_syms), expected))
    while short and rounds_used < MAX_ROUNDS:
        print("Waiting {}s before retry round {} ({} symbols, Yahoo only)".format(
            ROUND_WAIT, rounds_used + 1, len(short)))
        sys.stdout.flush()
        time.sleep(ROUND_WAIT)
        rounds_used += 1
        host = YHOSTS[(rounds_used - 1) % len(YHOSTS)]
        bust = int(time.time())
        for s in short:
            tv = s["tv"]
            rows, source, code_used, stooq_dead = fetch_one(
                s, stooq_dead, yahoo_only=True, host=host, bust=bust)
            if rows is None:
                print("  retry {}  {}: no data".format(rounds_used, tv))
            elif rows[-1][0] <= manifest[tv].get("last", ""):
                # never regress and never rewrite with the same stale tail
                print("  retry {}  {}: still {}".format(
                    rounds_used, tv, rows[-1][0]))
            else:
                write_symbol(manifest, manifest_path, s, rows, source,
                             code_used, fpath_of[tv], fname_of[tv])
                print("  retry {}  {}: advanced to {}".format(
                    rounds_used, tv, rows[-1][0]))
            time.sleep(0.35)
        short = short_list()
        print("After round {}: {} US symbols still short".format(
            rounds_used, len(short)))

    # ---- manifest _meta ----------------------------------------------------
    srcs = {}
    for k, v in manifest.items():
        if isinstance(v, dict) and v.get("status") == "ok":
            srcs[v.get("source")] = srcs.get(v.get("source"), 0) + 1
    ref = manifest.get(REF_US) if isinstance(manifest.get(REF_US), dict) else {}
    manifest["_meta"] = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "script_version": "1.3",
        "expected_last_us_session": expected,
        "reference_symbol": REF_US,
        "reference_symbol_last": ref.get("last"),
        "reference_symbol_at_expected": ref.get("last") == expected,
        "us_symbols_total": len(us_syms),
        "us_symbols_short": len(short),
        "us_symbols_short_examples": [s["tv"] for s in short[:10]],
        "retry_rounds_used": rounds_used,
        "kept_previous": kept_previous,
        "source_counts": srcs,
        "stooq_retired": True,
        "stooq_retired_date": "2026-07-25",
    }
    json.dump(manifest, open(manifest_path, "w"), indent=1)

    zpath = os.path.join(os.path.dirname(OUTDIR), "watchlist_data.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for fn in sorted(os.listdir(OUTDIR)):
            z.write(os.path.join(OUTDIR, fn), fn)

    ok = sum(1 for k, v in manifest.items()
             if isinstance(v, dict) and v.get("status") == "ok")
    fail = [k for k, v in manifest.items()
            if isinstance(v, dict) and v.get("status") == "failed"]
    print("\nDONE: {} ok, {} failed".format(ok, len(fail)))
    print("Sources: {}".format(srcs))
    print("US session expected {} | {} last bar {} | {} US symbols short".format(
        expected, REF_US, ref.get("last"), len(short)))
    if fail:
        print("Failed symbols (will be flagged in the report):")
        for k in fail:
            print("  -", k)
    if short and ref.get("last") == expected:
        print("WARNING: {} US symbols lag {} even though {} is current - the "
              "scan will run and flag them individually.".format(
                  len(short), expected, REF_US))
    print("\n==> Data file:\n    " + zpath)
    # Exit code mirrors the DOWNSTREAM gate, which keys on the reference
    # symbol alone: 0 = the scan can run, 3 = it will hard-stop on freshness.
    # The commit step runs before this is checked, so partial data still lands
    # and a red run is a notification, not a rollback.
    return 0 if ref.get("last") == expected else 3


if __name__ == "__main__":
    try:
        import urllib.parse  # noqa
        sys.exit(main() or 0)
    except KeyboardInterrupt:
        print("\nInterrupted - re-run to resume where it stopped.")
