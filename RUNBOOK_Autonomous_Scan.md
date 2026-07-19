# RUNBOOK — Autonomous Daily Pre-Open Watchlist Scan (v1.2, 2026-07-20)

**Purpose:** lets any fresh Claude session reproduce the full scan with zero rebuilding.
Governing document: `Cowork_Watchlist_Scan_Prompt_v1.md` (project knowledge). This runbook is
plumbing only — it changes nothing in the trading plan's mechanical definitions.

## Architecture

1. **Data leg (user-owned GitHub repo, free):** a GitHub Actions workflow (`fetch.yml`) runs
   Tue–Sat 09:30 SGT on GitHub's servers, fetches ~530 daily bars for all 224 watchlist symbols
   (Yahoo chart API; Stooq attempted first), and commits `watchlist_data.zip` + `manifest.json`
   to the repo. GitHub's raw URLs ARE reachable from the Cowork sandbox, unlike market-data domains.
2. **Scan leg (Claude scheduled task):** a scheduled task fires weekday evenings SGT in a fresh
   session. Its prompt tells the session to follow this runbook.
3. **Human leg (unchanged):** all trade decisions, TradingView verification, hourly triggers,
   and any parameter ratification remain with the owner. Category B empty is a normal outcome.

## Fresh-session procedure (what a scheduled run must do)

1. Fetch the toolchain from the data repo (works in ANY session — needs only shell access):
   for F in scan_engine.py run_scan.py render_reports.py symbol_map.json watchlists.json; do
     curl -sL -o "$F" "https://raw.githubusercontent.com/drphy68/Watchlist-data/main/$F"; done
   (scan_engine.py holds the Section 4 mechanics — DO NOT MODIFY; amendments only via the owner's
   written instruction. Mirror copies exist in project knowledge under claude/autonomy/ when
   project access is available, but the repo is the canonical runtime source.)
2. Download data (shell, allowlisted domain):
   `curl -L -o data.zip https://raw.githubusercontent.com/drphy68/Watchlist-data/main/watchlist_data.zip`
   Unzip; freshness rule: `_meta.generated_utc` must be <= 4 days old AND SPY's last bar must be
   the most recent completed US session (note: on Mondays the newest manifest is Saturday's, which
   correctly holds Friday's close - that PASSES). If either check fails, STOP and notify the owner
   rather than scanning stale data.
3. `python3 run_scan.py <data_dir>` — integrity checks + full classification (results.json).
4. Confirm SPY's last bar date == the most recent completed US session. Weekend runs (Sat/Sun SGT)
   use Weekend Mode per Section 8; weekday runs produce the standard daily brief per Section 6.
5. Cross-verify at least SPY + 2 random names, last 3 daily bars each. VERIFICATION SOURCE ORDER
   (web first, connector last — so an unattended run never stalls on an MCP permission card):
   a. WebFetch a public history page — try stockanalysis.com/stocks/<sym>/history/ (and /etf/<sym>/
      for ETFs); these worked in the manual build run;
   b. if WebFetch is blocked/empty, try one alternate web source before giving up;
   c. ONLY if all web routes fail AND the Alpha Vantage connector is already permitted this session,
      use it — do NOT trigger a fresh connector-permission prompt in an unattended run;
   d. if nothing verifies, ship the reports anyway and state in Section E that live cross-verification
      was unavailable this run (carried-forward, single-source Yahoo). Never block delivery on it.
   Say in Section E exactly which source verified which symbols.
6. Earnings filter: only for names reaching Category B (and evening-watch courtesy checks). Same
   source order — WebSearch first (query "<TICKER> next earnings date"); use the Alpha Vantage
   earnings calendar only if already permitted this session. AV's calendar has gaps (e.g. UNH
   returned no date on 3/6/12-month horizons on 2026-07-20) — if a date can't be verified from any
   source, mark it UNVERIFIED and flag it; never fabricate. Free AV tier: 25 calls/day, 5/min.
7. `render_reports.py` (adjust RUN_STAMP/LAST_BAR constants) → three dated reports.
   DELIVERY ORDER (durable first, cosmetic last):
   a. SendUserFile the three .md reports immediately (always available in Cowork sessions);
   b. IF the Projects tool is available: project_write the .md files and update
      claude/latest_scan_summary.md with a 10-line digest; if it is NOT available, say so
      explicitly in the final message — do not fail the run over it;
   c. only then produce landscape .docx versions (pandoc + sectPr patch) and send those too.
8. Honesty rules of Section 7 apply verbatim: flag every data failure, never populate an empty
   category, recompute everything fresh, report verified-live vs carried-forward.

## Known operational facts (learned 2026-07-19 run)

- TEST FIRE LESSON (2026-07-19): a scheduled fresh session was created with a restricted tool
  context (no project access). v1.1 therefore makes the GitHub repo the canonical source for
  scripts and requires delivery via SendUserFile first, project writes best-effort.
- v1.2 LESSON (2026-07-20): test fire #2 PASSED (9 uptrends, 4 approaching, 0 rejection candles,
  regime FAILING/MIXED — matched the manual run) but chose the Alpha Vantage connector for
  cross-verification and hit "Claude wants to use Time Series" permission cards an unattended run
  can't tap. v1.2 therefore makes cross-verification and earnings checks WEB-FIRST, connector
  optional/only-if-already-permitted, and never a blocker on delivery (step 5/6 above).

- Data repo (LIVE, verified 2026-07-20): https://github.com/drphy68/Watchlist-data - fetch Action
  runs Tue-Sat 09:30 SGT; dress rehearsal reproduced the manual run's classifications exactly.
- In the sandbox, api.github.com is SESSION-SCOPED (only repos added to the session); use
  raw.githubusercontent.com URLs instead - they work for any public repo.

- Stooq blocks cloud IPs (Colab, likely GH runners) → Yahoo is the de-facto sole source; flag
  this in Section E every run. Yahoo chart API = split-adjusted, not dividend-adjusted.
- Sandbox egress is proxy-locked to package registries + GitHub; WebFetch obeys robots.txt, which
  blocks Stooq/Yahoo endpoints and finance.yahoo.com pages for automated fetchers.
- Permanent data flags: HONA (listed Jun 2026, too new), CVAC/ERUS/JJC/SPCX (no data/delisted),
  MIL:BF-B (unusable mapping), VGNT/CRCL/RGAKF/MFMS/688755 short series, crypto weekend partial
  bar must be trimmed, QSE has no Friday session, China A-share LNY gaps are benign.
- 10 operationalizations of unquantified plan language are embedded in scan_engine.py
  (OPERATIONALIZATIONS list) and must be printed in Section E until the owner ratifies them.
- Watchlist changes: owner uploads new TradingView export .txt files to the project; then
  regenerate watchlists.json/symbol_map.json (build scripts in claude/autonomy/) and update the
  GitHub copy of fetch_watchlist_data.py (symbol list is embedded in it).
