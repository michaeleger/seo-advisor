# seo-advisor — Claude build plan (post triple-review)

**Project:** `/home/aiuser/projects/seo-advisor` on 5by5  
**Ops promote target (later):** `~/aiscripts/seo-advisor/` — **do not promote until Phase C**  
**Owner workflow:** Automation leads; Claude Code implements/fixes; Grok Build judges; Antigravity for Google/API questions.

**Prior reviews (read-only evidence):**
- Claude Opus/high: `/home/aiuser/tmp/seo-advisor-claude-review-opus.md`
- Antigravity Gemini 3.8 Flash/high (API focus): `/home/aiuser/tmp/seo-advisor-agy-flash-high-api-review.md`
- Grok Build grok-4.6/high (merge judge): `/home/aiuser/tmp/seo-advisor-grok-build-review.md`
- Live artifact: `reports/seo_report_2026-09-10.md`

**How to run Claude on this plan:**
```bash
cd ~/projects/seo-advisor
claude -p --model opus --effort high --output-format text \
  "Execute BUILD_PLAN_CLAUDE.md Phase N. Stay in the project dir. Add/adjust tests. Do not promote to ~/aiscripts/. Do not rewrite ranking philosophy."
```

**Ground rules**
1. Work only in `~/projects/seo-advisor` until Phase C.
2. Prefer small, reviewable commits (or clear change sets) per bug ID.
3. Every P0/P1 fix needs a regression test that would have failed on the 2026-09-10 behavior.
4. Do not enable Google Ads Keyword Planner in production path until Phase B Ads item is fixed *and* Basic access is proven.
5. Do not enable nginx `/seo/` without auth; nginx is currently inactive on this host.
6. Keep write-back out of scope (still `wp.py`).

---

## Phase A — P0 data integrity (do first; blocks next live run)

Fix in this order. Stop and report if a later fix depends on an earlier one unexpectedly.

### A1 — B1: GSC prior-window comparison (fake 0→N trends)

**Problem:** `_prior_date_range()` in `gsc.py` uses `DATE_RANGE_DAYS` (365), so the prior window falls outside ~16-month GSC retention. Report shows `impr 0→N` while decay (90d) correctly shows falling — opposite signals in one briefing.

**Files:** `gsc.py` (`_prior_date_range`, `get_page_period_comparison`, `get_site_context` date_range.previous)

**Do:**
- Give period comparison its own adjacent short window (same idea as `DECAY_WINDOW_DAYS` / decay path), **or** hard-cap prior start within retention (~14 months).
- Ensure previous window is adjacent to current (previous.end ≈ current.start − 1 day).
- Keep decay path behavior unless a shared helper clearly improves both.

**Tests:**
- Assert prior start is within retention for `DATE_RANGE_DAYS=365`.
- Assert adjacency of current/previous windows.
- Optional: fixture proving empty prior rows are not labeled as “growth from zero” without data.

**Done when:** unit tests pass; no code path still derives prior range solely from full `DATE_RANGE_DAYS` for period comparison.

---

### A2 — B2: Rank Math score / tier sync after Stage 2b

**Problem:** Catalog miss → selection sets “unknown” tier; Stage 2b finds score (e.g. 10) on the post; `main.py` never copies post→metrics. Report: `score=10/100 (unknown RankMath score)`. Fixability understated.

**Files:** `main.py` (Stage 2b merge), `analyzer.py` (tier/fixability helpers if needed), `briefing.py` only if labels still disagree after metrics sync

**Do:**
- After Stage 2b, if post has a Rank Math score and metrics lack one (or disagree), update `metrics["rankmath_score"]`, recompute tier + label + fixability (and priority if still used downstream).
- Prefer one shared resolution helper used by catalog path and Stage 2b.
- Never emit `score=N` with `unknown RankMath score` for the same page.

**Tests:**
- Synthetic: metrics unknown + post score 10 → metrics/tier/label consistent after merge.
- Synthetic: catalog score ≥ `RANKMATH_SKIP_SCORE` must not bypass skip when score arrives late (or document intentional re-rank behavior).

**Done when:** contradiction in 2026-09-10 shape cannot recur; tests green.

---

### A3 — B3: WP catalog cap / newest-first / pages skipped

**Problem:** `list_content_with_rankmath(max_items=300)` + `orderby=modified&order=desc`; if posts fill budget, pages never fetched; neglected pages lose `modified`/scores → neglect_multiplier=1.0.

**Files:** `wp_client.py` (`list_content_with_rankmath`), `main.py` call site

**Do:**
- Page catalog to exhaustion (or much higher safe cap) with **separate budgets** for `posts` and `pages`.
- Prefer `orderby=modified&order=asc` (oldest first) **or** no date bias that starves neglected content; document choice.
- RankMath-only stubs must include `modified` when available.
- Keep timeouts reasonable; log truncation if any hard cap remains.

**Tests:**
- Mock pagination: posts alone would fill old cap → pages still fetched.
- Stub without modified does not silently pretend “fresh” if that is the chosen semantics (assert neglect behavior).

**Done when:** pages cannot be skipped solely because posts filled the list; tests green.

---

### A4 — B5: `save_page_state` wiping `last_modified_seen`

**Problem:** Blind `INSERT OR REPLACE` with stub `modified=None` erases prior `last_modified_seen`; edit detection never fires.

**Files:** `db.py` (`save_page_state`), callers in `main.py`

**Do:**
- Preserve existing `last_modified_seen` when new value is NULL (UPDATE/`COALESCE` or read-modify-write).
- Do not lose backoff/edit fields on partial stubs.

**Tests:**
- Save full modified → save stub without modified → `last_modified_seen` unchanged.
- Edit detection still works across that sequence.

**Done when:** tests pin preservation; no blind null overwrite.

---

### A5 — PageSpeed: key gate + 429 circuit breaker + no raw error body

**Problem:** Anonymous PSI → 100% 429; continues all URLs; dumps `resp.text` (incl. project number) into Markdown.

**Files:** `pagespeed.py`, `briefing.py` (error rendering), `config.py` / `.env.example` as needed

**Do:**
- Treat missing `PAGESPEED_API_KEY` as “skip stage” (or force configured=false) even if `USE_PAGESPEED=1`.
- On HTTP 429, log once and **break** out of `scan_selected_urls`.
- Collapse errors to one safe line; never interpolate raw response bodies.
- Add `execute`/request timeouts already present — do not increase hang risk.

**Tests:**
- Missing key → no scan calls / status explains skip.
- First 429 → no further URL calls.
- Error string has no JSON body / project_number.

**Done when:** tests green; briefing cannot embed PSI response bodies.

---

### Phase A exit criteria

```bash
cd ~/projects/seo-advisor
.venv/bin/python -m pytest -q
```

- All existing tests still pass; new regression tests for A1–A5 pass.
- Short note in this file or `CHANGELOG` / commit message listing files touched per bug ID.
- **Do not** run a full live GSC/WP job unless Michael asks.

**Status 2026-09-12 — A1–A5 done, uncommitted in `~/projects/seo-advisor`.** `173 passed`.

| Bug | Files touched | Tests |
|---|---|---|
| A1 prior window | `gsc.py` | `tests/test_gsc_windows.py` |
| A2 score/tier | `main.py`, `analyzer.py`, `briefing.py` | `tests/test_rankmath_sync.py` |
| A3 catalog | `wp_client.py`, `config.py`, `main.py` | `tests/test_wp_catalog.py` |
| A4 modified wipe | `db.py`, `main.py` | `tests/test_db.py` |
| A5 PageSpeed | `pagespeed.py`, `briefing.py`, `main.py`, `config.py`, `.env.example` | `tests/test_pagespeed.py` |

A5 notes: `PAGESPEED_API_KEY` is now required — `is_configured()` is false without
it whatever `USE_PAGESPEED` says, and stage 2e reports the skip instead of running.
The scan breaks out of the URL loop on the first 429 (status/`notes` say how far it
got). Errors are collapsed to `HTTP <code> — <reason>` at the source and sanitised
again in `briefing._safe_stage_error`, so no response body, `?key=` URL or project
number can reach the Markdown. Not touched here (Phase B): GSC retries, Ads oneof,
nginx, path anchors.

---

## Phase B — P1 reliability + identity (before promote)

### B0 — R1 hotfix (A3 regression): false edit detection from `modified` formats

**Problem:** mu-plugin emits MySQL `YYYY-MM-DD HH:MM:SS`; WP REST uses ISO `YYYY-MM-DDTHH:MM:SS`. `analyzer.py` compares raw strings → false "edited", drops neglected pages, ping-pongs after `mark_edited`.

**Do:**
- Normalize `modified` at ingest (plugin: RFC3339; Python: parse both at compare time via existing `_days_since` / datetime parse).
- Compare parsed datetimes, not raw strings.
- Test with stub `modified="2024-03-05 10:00:00"` vs ISO seen stamp — must NOT mark edited.

**Do this before redeploying the mu-plugin** (deploy without fix activates R1).

---

Do after Phase A (A1–A5 done). Include R1 as B0 before other B work if not already fixed.

### B1 — Canonical page identity (review B4)

**Files:** `analyzer.py`, `main.py`, `db.py`  
**Do:** one `_canonical_key` for dedup, state lookup, and persistence.  
**Test:** www / non-www / trailing-slash variants share state.

### B2 — Slug fallback tightening (review B15)

**Files:** `wp_client.py`  
**Do:** exact match or hyphen-boundary only; log fuzzy resolutions.  
**Test:** `classic-…` vs shorter slug does not false-bind.

### B3 — GSC retries + Stage 2b abort (API)

**Files:** `gsc.py` (`execute(num_retries=3)` or equivalent), `main.py` Stage 2b  
**Do:** retry transient failures; do not re-raise in a way that aborts remaining selected URLs after a single page failure (log + continue unless auth-fatal).  
**Test:** mock mid-loop failure still processes later URLs.

**Status 2026-09-13 — B0 (R1) + B1–B3 done, uncommitted, on top of A1–A5.** `238 passed`.

| Item | Files touched | Tests |
|---|---|---|
| B0/R1 `modified` formats | `wp_client.py` (`parse_modified`/`normalize_modified` at every ingest), `analyzer.py` (`_modified_changed` compares datetimes), `wordpress-plugin/eager-rankmath-rest.php` (`mysql_to_rfc3339`, v1.1.1) | `tests/test_modified_formats.py` |
| B1 identity | `analyzer.py` (`canonical_key`, state re-key, exclusions), `db.py` (read/write by key + `init_db` migration merging legacy duplicates) | `tests/test_page_identity.py` |
| B2 slug fallback | `wp_client.py` (`slug_match`: exact or `-N` duplicate suffix; fuzzy hits logged) | `tests/test_slug_fallback.py` |
| B3 retries / 2b | `gsc.py` (`execute(num_retries=3)`, `GSCAuthError`, `is_auth_fatal`), `main.py` (`enrich_selected_pages`), `seo_advisor.py` (`LocalLLMConfigError`) | `tests/test_stage2b.py` |
| R2 reasons | `analyzer.py` (`sync_rankmath_from_post` rewrites the RankMath reason) | `tests/test_rankmath_sync.py` |
| R3 PSI header | `briefing.py` (`ok X/Y scanned of Z requested` + stop note) | `tests/test_briefing_pagespeed_header.py` |

Notes: the first `init_db()` against the live `seo_state.db` rewrites `page_history.url`
to canonical keys (one-way). `wordpress-plugin/build/` and the `.zip` still hold the
pre-A3 plugin — rebuild before deploying (Phase D drift item). B4–B7 not started.

### B4 — Ads Keyword Planner `oneof` (keep gated)

**Files:** `keyword_planner.py`  
**Do:** use `keyword_and_url_seed` when both seeds and URL are present; or seeds-only. Leave gated until Basic access proven.  
**Test:** building the request does not set both exclusive oneof members.

### B5 — Prompt / docs alignment (review B8)

**Files:** `briefing.py` (`CLAUDE_HANDOFF_PROMPT` + headings), `SETUP.md`, `.env.example`  
**Do:** describe neglect ranker (`missed_clicks × neglect × fixability × decay`), not tier-first. Align `.env.example` with `config.py` knobs from commit `4585e8d`. Fix `"clicks/yr"` if still hardcoded wrongly.  
**Test:** cheap assert that handoff prompt does not claim Rank Math tier-first ordering.

### B6 — Secrets + path anchors

**Files:** `config.py`, `db.py`, `gsc.py`, `authorize.py`, writers of token JSON  
**Do:**
- Anchor `DB_PATH`, `_TOKEN_FILE`, credentials, `REPORTS_DIR` to `Path(__file__).resolve().parent`.
- `chmod 600` on `token.json`, `client_secret.json`, `ads_token.json` (and write with mode 0600 going forward).
- Deduplicate Bing keys in `.env` (operator may need to edit live `.env` — Claude should not print secrets).

**Note:** `promote.sh` currently patches `config.py` dotenv paths incompletely — path anchors make that less critical.

### B7 — Nginx report surface (config only)

**Files:** `nginx-seo-reports.conf`, `cowork-nginx-updated.conf`  
**Do:** add `auth_basic` or `allow 127.0.0.1; deny all;`; comment that alias must follow promote path. Do not enable the nginx unit.

**Status 2026-09-13 — B4–B7 done, uncommitted, on top of A1–A5 + B0–B3.** `259 passed`.

| Item | Files touched | Tests |
|---|---|---|
| B4 Ads oneof | `keyword_planner.py` (`_build_idea_request`/`_set_seed`: `keyword_and_url_seed` when both, else one member; still gated by `is_configured`) | `tests/test_keyword_planner.py` (real v24 proto) |
| B5 prompt/docs | `briefing.py` (prompt + pipeline/selection/overview headings), `analyzer.py` (`clicks_window_label`), `main.py` (log wording/unit), `config.py` (dead `PRIORITIZE_BY_RANKMATH` comment), `SETUP.md`, `.env.example` | `tests/test_briefing.py`, `tests/test_priority.py` |
| B6 paths/secrets | `config.py` (`PROJECT_DIR`, `project_path`, `write_private_text`, anchored dotenv/`GSC_CREDENTIALS_FILE`/`REPORTS_DIR`), `db.py`, `gsc.py`, `authorize.py`, `authorize_ads.py`, `setup_bing.py`, `.gitignore` (`backups/`) | `tests/test_paths_secrets.py` |
| B7 nginx | `nginx-seo-reports.conf`, `cowork-nginx-updated.conf` (`allow 127.0.0.1; allow ::1; deny all;`, auth_basic alternative, promote-path alias comment, noindex) | — (config only; nginx not enabled) |

Notes: live `.env` duplicate `BING_API_KEY`/`BING_SITE_URL` collapsed to one line each
at the first position carrying the previously-effective (last) value — verified by
hashing `dotenv_values` before/after; backup in `backups/.env.bak-*` (0600, ignored).
Plugin `build/` + `.zip` rebuilt from v1.1.1 source (old zip in `backups/`). `promote.sh`'s
config.py dotenv patch no longer matches (block changed) and will print "check manually";
the anchored `PROJECT_DIR / ".env"` is equivalent to its first candidate.

---

## Phase C — Promote readiness (only when Michael says go)

1. Re-run `.venv/bin/python -m pytest -q` — all green.  
2. Optional dry live run (Michael approves): `./run.sh` or documented entrypoint; spot-check new report for: no `0→N` with empty prior, no `score=N (unknown…)`, no PSI JSON blobs.  
3. Grok Build second pass (bug-check) on the diff.  
4. Promote via `~/aiscripts/promote.sh` (or documented process) **only after** Michael approval.  
5. Confirm ops copy has path-safe layout; crontab/systemd still use `run.sh` or absolute paths.

---

## Phase D — Nice-to-have (not blockers)

- Delete or retarget dead APIs: `_gsc_reasons`, `cooldown_urls`, `identify_low_performers` as primary test driver; dead config knobs.  
- Keep real `score_source` from fetcher (`wp_client.py` overwrite).  
- Bing: notes not rendered as page bullets; optional Bing-informed selection later.  
- `SKIP_SLUG_SUBSTRINGS`: avoid bare `cookie` false positives.  
- Revisit `load_dotenv(override=True)` vs systemd env.  
- Plugin: `auth_callback` read-only (`__return_false`); reconfirm public `permission_callback`.  
- Plugin zip vs source drift (generate in CI or drop tracked zip).

---

## Suggested Claude execution order (one session per chunk)

| Session | Scope |
|---|---|
| 1 | Phase A1 + A2 + tests |
| 2 | Phase A3 + A4 + tests |
| 3 | Phase A5 + full pytest |
| 4 | Phase B1–B3 |
| 5 | Phase B4–B7 |
| 6 | Phase C only with explicit go |

After each session: summarize what changed, tests run, residual risks. Do not start Phase C without approval.

---

## Acceptance snapshot (end of Phase A)

| Bug | Symptom gone? | Test added? |
|---|---|---|
| B1 prior window | No structural empty prior for 365d setups | Yes |
| B2 score/tier | No `score=N (unknown…)` | Yes |
| B3 catalog | Pages not starved by posts-only fill | Yes |
| B5 modified wipe | Stub save preserves `last_modified_seen` | Yes |
| PSI | No key → skip; 429 → stop; no raw body | Yes |
