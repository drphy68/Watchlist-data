# RUNBOOK — Autonomous Daily Pre-Open Watchlist Scan (v1.4, 2026-07-22)

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
   (scan_engine.py holds the Section 4.1 mechanics — DO NOT MODIFY; amendments only via the owner's
   written instruction. Section 4.2 (volume module, v1.2) is computed automatically by run_scan.py —
   no manual step is needed to produce V1/V2/V3/AvgVol50; they land in results.json under
   detail['volume'] for every symbol and render.py already reads them. Mirror copies exist in project
   knowledge under claude/autonomy/ when project access is available, but the repo is the canonical
   runtime source — CONFIRM the repo copies are v1.2-current (grep for "volume_module" in
   scan_engine.py) before trusting them; if the repo still holds pre-v1.2 files, use the project
   mirror instead and flag the repo as stale in the final message.)
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
7. `render_reports.py` (adjust RUN_STAMP/LAST_BAR constants, AND — new in v1.4 — VOLUME_RUN_NO) →
   three dated reports.
   VOLUME_RUN_NO (Section 8 report-only counter, v1.2): determine N by reading the most recent
   PREVIOUS delivered report's header line "Volume module (v1.2, Section 8): report-only, run N of
   10" — check, in order: (a) project doc claude/latest_scan_summary.md if Projects is available;
   (b) the most recently created Watchlist_Scan_*.md in the Google Drive "Watchlist Scans" folder
   (search_files, sort by createdTime) if the Drive connector is available; (c) if neither is
   reachable or no prior v1.2 report is found, this is the FIRST run since v1.2 deployment
   (2026-07-22) — set VOLUME_RUN_NO = 1. Otherwise set it to (found N) + 1, capping display at "10 of
   10" — do not silently roll past 10; if N was already 10, state in the final message that the
   Section 8 calibration review is due and ask the owner for a promotion/extension/amend decision
   rather than guessing which. State in Section E which method (a/b/c) determined N this run.
   DELIVERY ORDER (durable first, cosmetic last):
   a. SendUserFile the three .md reports immediately (always available in Cowork sessions);
   b. IF the Projects tool is available: project_write the .md files and update
      claude/latest_scan_summary.md with a 10-line digest; if it is NOT available, say so
      explicitly in the final message — do not fail the run over it;
   c. only then produce landscape .docx versions (pandoc + sectPr patch) and send those too.
   d. DEPOSIT TO GOOGLE DRIVE (owner's archive): folder "Watchlist Scans", folder id
      `17lVei5BDbMdN7XC1jGlEDyZ4L5NtzXI8` (account phyinvest21@gmail.com), via the Google Drive
      connector create_file, parentId = that id, disableConversionToGoogleType=true.
      SIZE-SAFE RULES (learned 2026-07-20 — a large .docx truncated into a corrupt partial):
      - .md files: upload via **textContent** (raw UTF-8), NOT base64. The text path handled a 40 KB
        .md fine; use it for all three .md, contentMimeType text/markdown.
      - .docx files: upload via base64Content, contentMimeType
        application/vnd.openxmlformats-officedocument.wordprocessingml.document — but ONLY IF the
        base64 string length is ≤ 28,000 chars (~20 KB binary; the connector's per-call ceiling sits
        ~30 KB base64). If a .docx's base64 exceeds that, DO NOT UPLOAD IT (a partial upload creates
        a corrupt file the connector cannot delete). Skip it cleanly and note in the final message
        which .docx were skipped for size — the matching .md carries the full content and the .docx is
        already delivered to chat/project. NEVER upload a truncated/partial payload.
      - After each successful create_file, confirm the returned viewUrl AND that the returned fileSize
        equals the local file's byte size; if they differ, treat the upload as failed and say so.
      - The connector has NO delete tool: if a bad file already exists from a prior run, you cannot
        remove it — flag it for the owner to delete manually (give the file id).
      If the Google Drive connector is unavailable/unpermitted, do NOT fail the run — reports are
      already delivered via (a)-(c); note the skip and why. (For guaranteed deposit of ALL sizes/formats,
      the upgrade path is Route B: a GitHub Actions + rclone bridge, server-side, no payload ceiling —
      would also enable OneDrive. Not built; noted for future.)
8. Honesty rules of Section 7 apply verbatim: flag every data failure, never populate an empty
   category, recompute everything fresh, report verified-live vs carried-forward.

## Known operational facts (learned 2026-07-19 run)

- v1.4 (2026-07-22): owner ratified and incorporated spec v1.2 (volume module — AvgVol50/RVOL, V1
  quiet-pullback, V2 demand-confirmation, V3 OBV accumulation tag; REPORT-ONLY for 10 runs per
  Section 8 sunset clause, see VOLUME_RUN_NO procedure in step 7 above). scan_engine.py gained
  half_day_dates() (NYSE early-close dates derived by RULE, not hardcoded per year — see its
  docstring), avgvol50(), obv(), volume_adjustment_candidates() (coarse split-artifact heuristic,
  NOT a corporate-actions audit — always disclosed as such), and volume_module() — the last is
  called AFTER classify() and merged into detail['volume'] by run_scan.py; classify() itself
  (Section 4.1) was left byte-for-byte unchanged, so the ratified price-structure mechanics cannot
  be affected even by accident. render_reports.py's weekend_table/section_B/section_C/header now
  show the volume columns/lines the spec requires; a new volume_e_section() adds the Section
  3.5/7.6/8 disclosures dynamically from results.json every run (unlike the older E_COMMON block,
  which is frozen narrative from the first run and must still be hand-updated per run as before).
  test_engine.py gained a full volume-module test block (half-day rule spot-checks across three
  July-4 weekday configurations, AvgVol50 windowing, OBV arithmetic, V1/V2/V3 boundary cases) — full
  suite re-run and passing before v1.4 was declared ready. ACTION NEEDED: the owner must push the
  updated scan_engine.py / run_scan.py / render_reports.py / test_engine.py / this runbook to the
  `drphy68/Watchlist-data` GitHub repo — until that happens, the repo copies are pre-v1.2 and a
  fresh unattended session pulling from raw.githubusercontent.com will run the OLD engine with no
  volume module. The live scheduled task's prompt has been updated (2026-07-22) to warn the session
  to check for this and use the project mirror if the repo is stale.
- TEST FIRE LESSON (2026-07-19): a scheduled fresh session was created with a restricted tool
  context (no project access). v1.1 therefore makes the GitHub repo the canonical source for
  scripts and requires delivery via SendUserFile first, project writes best-effort.
- v1.3 (2026-07-20): added Google Drive deposit of all six report files to folder "Watchlist Scans"
  (id 17lVei5BDbMdN7XC1jGlEDyZ4L5NtzXI8, account phyinvest21@gmail.com) as delivery step 7d. Connector
  needed WRITE re-authorization (read-only grant returned 403 on create_file until re-consented). Deposit
  is best-effort: never blocks the already-delivered reports. OneDrive was not used — the Microsoft 365
  connector publishes only read/search tools (no file upload), so OneDrive deposit is not currently
  possible through it; revisit if MS adds an upload tool or via a GitHub-Actions+rclone bridge.
- v1.3.1 (2026-07-20): first live Drive deposit — 5/6 files landed & verified; Excluded.docx (139-row
  table, base64 36.5k chars) exceeded the connector's per-call ceiling and uploaded as a CORRUPT
  truncated partial that could not be deleted (no delete tool). Fix in step 7d: .md via textContent
  (handles 40KB+), .docx via base64 only if base64 <= 28k chars else SKIP CLEAN (never partial),
  verify returned fileSize == local size. Owner had to delete the corrupt file + README manually.
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
- 13 operationalizations of unquantified plan language are embedded in scan_engine.py
  (OPERATIONALIZATIONS list, +2 added with the v1.2 volume module) and must be printed in Section E
  until the owner ratifies them.
- Watchlist changes: owner uploads new TradingView export .txt files to the project; then
  regenerate watchlists.json/symbol_map.json (build scripts in claude/autonomy/) and update the
  GitHub copy of fetch_watchlist_data.py (symbol list is embedded in it).
