# Lele Aviation Intelligence Platform — System Architecture
**Version 1.11 | June–July 2026 | Confidential**

> **For a fresh Claude session picking this up:** read this whole file. `forecast_baseline_template_v3.4.xlsx` is the current workbook (built 2026-06-22, hand-edited by Jon and re-synced to the DB 2026-06-23 — see next paragraph). **Part 8's AeroLOPA integration is complete — all 6 steps done and verified.** **Manual edit sync (2026-06-23):** Jon edited `forecast_baseline_template_v3.4.xlsx` directly in Excel — filled in Has IFE?/IFE Type for every active subfleet across all 4 cabin classes (previously blank for AeroLOPA-uncovered rows), and zeroed out J Lie-Flat wherever J Privacy Door is nonzero (a privacy-door business seat is no longer double-counted as a plain lie-flat seat, 63 active subfleets affected). Both pushed to the live DB via new idempotent script `scripts/sync_v34_manual_edits.py` (full re-run of the script is safe — it's a full overwrite by subfleet id from the current workbook state, not a sparse patch). **A handful of internal contradictions in Jon's IFE entries were found and pushed through as-is, not auto-corrected** — see Part 2 Group A and Part 7 item 7 for the exact list (43 rows total, e.g. Has IFE?=NO paired with a real IFE Type, mostly on regional-jet BYOD-Streaming rows). See Part 2 Group A for full detail. **v3.4 (2026-06-22) adds two changes, both already live in the DB and in the workbook:** (1) retirement age defaults updated to Jon's researched values (Widebody 20, Narrowbody 25, Regional 30, Turboprop 30 — was 25/25/20/30 DRAFT placeholders); (2) IFE is now tracked PER CABIN CLASS — the single whole-subfleet Has IFE?/IFE Type pair (`01_Fleet_Baseline` cols AK/AL in v3.3) is replaced by FOUR pairs, one each for First/Business/Premium Economy/Economy (cols AK–AR), matching the grain AeroLOPA's source data actually supports. Has Connectivity?/Connectivity Notes shifted from AM/AN to AS/AT to make room. See Part 6 for the workbook-level detail and Part 2 `subfleets` entry / Group F for the DB-level detail. **v3.3 (2026-06-22) added two features, both already live in the DB and in the workbook:** retirement modeling (new `retirement_age_defaults` table + `01_Fleet_Baseline` cols AH–AJ + new sheet `08_Retirement_Defaults`) and IFE/connectivity tracking (new `subfleets` columns, superseded by the cabin-class split in v3.4 above). **v3.3.1 (2026-06-22) closes the Turboprop pricing gap** — see Part 7 item 9. **v3.3.2 (2026-06-22) closes the bulk airline categorization gap** — all 987 airlines now have a Category, sourced live from `airlines.airline_category` in the DB — see Part 1, Part 2 Group A, and Part 7 item 4 (RESOLVED). **File-naming note (read before running anything):** the rebuild script is `scripts/build_template_v34.py`, not `build_template.py`, `build_template_v33.py`, `build_template_v331.py`, `build_template_v332.py`, or `build_template_v332_fix.py` — this environment hit a persistent stale-read issue more than once (bash-side tools kept returning truncated content even after a full rewrite, while the file tools saw the correct content; root cause not resolved, only worked around — same fix each time, write the verified-correct content fresh to a new filename). The output workbook is likewise `forecast_baseline_template_v3.4.xlsx`, a new filename, not an overwrite of `forecast_baseline_template.xlsx` — the original also appears locked (likely open in Excel on Jon's machine); sub-version bumps do NOT rename the output workbook, only the build script's filename changes. **If a future rebuild hits the same symptom** (bash `wc -l`/`ast.parse` truncated at a fixed line count that doesn't move no matter how many times the file is rewritten, while `Read`/`Write` tool calls see the full correct content), don't keep fighting the same filename — copy the script to a new name in `scripts/` and run that instead, same pattern used several times now. Part 8's AeroLOPA integration is complete — all 6 steps done and verified, including Step 6 (rebuild `01_Fleet_Baseline`). **v3.2 (2026-06-19, after Part 8) redesigned `06_Retrofit_Defaults` into a full 32-row Size Class × Airline Category grid with an explicit OTH row per size class** — see Part 6. Part 7 lists smaller open items. **The project folder was reorganized 2026-06-19** — scripts now live in `scripts/`, large source files in `source_data/`, working/crosswalk files in `reference/`, orphans in `archive/`; the workbook, `ARCHITECTURE.md`, and `.env` stay at the folder root. See Part 9. The DB connection string is in `.env` in the folder root (also hardcoded directly in the build scripts as of v3.3.2). Nothing important lives only in chat history — the database is the source of truth, this doc is the source of truth for design decisions.

---

## Overview

This document defines the complete database architecture for the Lele Aviation Intelligence Platform — a single PostgreSQL database (hosted on Supabase) that serves as the quantitative backbone for:

1. **MRO/Interiors Forecast** — multi-vintage, subfleet-level spend forecasts
2. **Hoku Intelligence** — airline capital allocation scores, signal history, reaction analysis
3. **Client Deliverables** — Insperial and future bespoke engagements
4. **Supplier Intelligence** — program wins, sub-supplier relationships, capacity signals

**Design principle:** Notion remains the source of record for qualitative data (raw signals, articles, SEC filings, news events, editorial judgment). PostgreSQL is the source of record for all quantitative data and structured reference data. The two systems are linked by shared IDs, not duplicated content.

---

## Part 1: Airline Classification Framework

Every airline in the system is classified on two primary dimensions plus one secondary attribute used by the Reaction Engine.

---

### Dimension 1: Airline Category

> **Taxonomy edit 2026-06-17, propagation confirmed complete 2026-06-18.** Jon redefined this taxonomy to the 8-value set below, replacing EMG/LSR. The DB CHECK constraint, this doc, and the `05_Airline_Defaults` Category dropdown (data validation list, confirmed present: `FSC,GL,LCC,ULCC,RFSC,REG,LEI,OTH`) are all in sync. **Zero airlines used EMG or LSR** before the change, so no data migration was needed.
>
> **Category assignment coverage — RESOLVED (v3.3.2, 2026-06-22).** Originally flagged 2026-06-18: only 23 of 987 airlines had `airline_category` populated. Jon did a full manual categorization pass over all 987 airlines (weekend of 2026-06-20/21) and sent back the completed sheet (`Airline Categories - Completed.xlsx`). All 987 names matched the live `airlines` table with zero unresolved rows; applied via `scripts/apply_airline_categories_v2.py` (single bulk `execute_values` statement, idempotent, safe to re-run). **`airlines.airline_category` is now 987/987 populated** — distribution: RFSC 293, OTH 193, LEI 187, REG 123, LCC 112, FSC 48, ULCC 19, GL 12. Nine airlines changed from a previously-set (legacy seed) category — mostly FSC→GL reclassifications (Etihad, Japan Airlines, Lufthansa, Qantas, Turkish Airlines, All Nippon Airways), plus JetBlue (LCC→RFSC) and Ryanair/United (ULCC→LCC / FSC→GL) — Jon's new pass is authoritative. The v3.2 OTH-fallback mechanism described below is now moot for coverage purposes (every airline has a real, Jon-assigned category) but remains the architecture for any future new airline added with no category set.

What kind of airline it is — market position, product philosophy, and customer segment. This is the primary classification.

| Code | Category | Description |
|------|----------|-------------|
| FSC | Full Service Carrier | Full network carrier with multi-cabin product; significant fleet and international presence (United, Air Canada, Korean Air, Lufthansa, British Airways, ANA, JAL) |
| GL | Global Leader | Premium product pacesetter with global reach; sets standards others track internationally (Emirates, Qatar, Singapore, Cathay Pacific, Delta) |
| LCC | Low Cost Carrier | Cost discipline with meaningful cabin differentiation, often one or two classes (Southwest, AirAsia, Jetstar, IndiGo, Volaris) |
| ULCC | Ultra Low Cost Carrier | Maximum densification, bare-bones model, minimal or no cabin differentiation (Ryanair, easyJet, Wizz Air, Spirit, Frontier) |
| RFSC | Regional Full Service Carrier | Full product differentiation within a defined geography; meaningful widebody or long-haul operations (Alaska, Air New Zealand, WestJet, Porter, TAP, Finnair) |
| REG | Regional Airline | Mainline-branded regional/feeder operator flying CRJ/E-Jet equipment under a major carrier's livery (Envoy, PSA, SkyWest, Horizon, Endeavor, Republic, GoJet, Mesa, Piedmont, Air Wisconsin) |
| LEI | Leisure / Charter | Charter, vacation-oriented, or heavily leisure-focused operators (Air Transat, Allegiant, Condor, TUI, Sunwing) |
| OTH | Other | Anything that doesn't fit the above (new entrants/trajectory not yet established, niche/startup carriers, etc.) |

**Why this matters for spend forecasting:** Category is the primary driver of cabin investment intensity. A Global Leader will invest 3–5x more per seat per cycle than a ULCC. Category informs default spend assumptions and retrofit interval assumptions before airline-specific overrides are applied.

**REG note:** this category exists specifically to fix a known data gap — regional subsidiary carriers (Envoy, PSA, SkyWest, etc.) exist as separate `airlines` rows with their own CRJ/E-Jet `subfleets`, but `parent_airline_id` is NOT populated for any US regional subsidiary (only Avianca/Lion Air/SAS/Smartwings/Tuifly subsidiaries have it set). This means a mainline carrier's regional-fleet retrofit signal currently has nowhere correct to land. Tagging these 10 carriers as REG at least makes them queryable as a group; properly linking them via `parent_airline_id` is a separate, not-yet-scheduled fix.

---

### Dimension 2: Influence Tier
How much this airline's cabin decisions move the market. Drives which events trigger Reaction Engine analysis.

| Tier | Label | What It Means |
|------|-------|---------------|
| 1 | Global Pacesetter | Sets standards others track globally. Their announcements trigger Reaction Engine analysis for all clusters they belong to. (~4–6 airlines worldwide) |
| 2 | Regional Leader | Defines product expectations within their region/route set. Announcements trigger analysis within their clusters. (~15 airlines) |
| 3 | National Player | Significant fleet; follows regional leaders. Announcements monitored but rarely trigger broad reaction. (~30 airlines) |
| 4 | Follower | Reacts to necessity; limited market-signal value for reaction purposes. |

**Tier is scored on five dimensions (1–5 each, max 25):**
- Brand & Product Leadership
- Competitive Visibility (how closely peers track them)
- Network Relevance (route breadth and premium route density)
- Fleet & Cabin Complexity (widebody share, multi-cabin configurations)
- Historical Reaction Trigger Rate (how often their actions provoke peer responses)

Note: Category and Influence Tier are independent. An RFSC can be Tier 2 (Alaska is a meaningful signal within North America). A large FSC can be Tier 3 if their cabin investments don't drive peer behavior (American Airlines in the current model).

---

### Secondary Attribute: Investment Decision Pattern
This is **not** a classification of what kind of airline it is — it is a behavioral attribute describing **how** a specific airline makes cabin investment decisions. It is derived from analysis of 590 historical events (2015–2026) and is used by the Reaction Engine to calculate propagation probability and timing.

| Code | Pattern | Trigger | Examples |
|------|---------|---------|---------|
| FE | Fleet-Event-Linked | New aircraft type delivery sets cabin standard; existing fleet systematically retrofits to match | American (A321neo → PE rollout), United (IFE on deliveries), Emirates (777X → 777-300ER cascade) |
| TC | Time-Cycled | Follows a regular refresh cycle independent of specific events | Singapore Airlines (~5yr refresh), Etihad |
| CR | Competitor-Responsive | Reacts to peer announcements with defined lag; explicitly cites competitors in filings | Qatar (tracks Emirates), Air Canada (tracks Delta/United) |
| HY | Hybrid | Moves on multiple triggers; combination varies by program type | Delta (Financial Threshold + Fleet-Event), Lufthansa, Qantas |

Each airline also has a **Trigger Hierarchy** — an ordered list of what moves them:
- P = Primary (most reliable predictor)
- S = Secondary (reinforcing)

Example — Delta (HY): Earnings milestone / ROIC target (P) → Fleet delivery new type (S) → Fleet age threshold (S) → Competitive pressure (S)

---

### Competitive Clusters
Groups of airlines whose cabin investment decisions directly influence each other. Based on route overlap and product competition — not simply region.

| Cluster | Key Members | Basis |
|---------|-------------|-------|
| NA-Mainline | Delta, United, American | Domestic + transatlantic route overlap |
| NA-Premium | Delta, United, American, Air Canada | Premium cabin competition |
| Gulf-Big3 | Emirates, Qatar, Etihad | Premium long-haul |
| Europe-FSC | Lufthansa Group, IAG, Air France-KLM | Transatlantic + intra-European premium |
| Asia-Pacific-Premium | Singapore, Cathay, ANA, JAL | Long-haul premium |
| Transatlantic-Premium | Delta, United, Lufthansa, BA, Air France, Virgin Atlantic | Long-haul premium overlap |
| Middle-East-Europe | Emirates, Qatar, Etihad, Lufthansa, BA | Asia-Europe long-haul |

An airline can belong to multiple clusters. **Cluster Intensity** (0.0–1.0) measures how reliably one airline's move provokes another's within a cluster.

---

## Part 2: Complete Table Inventory

### Group A — Reference Tables (stable, infrequently updated)

---

**`airlines`** — master registry; every other table references this
- id, name, iata_code, icao_code, ticker
- parent_group (Lufthansa Group, IAG, Air France-KLM, etc.)
- **airline_category** (FSC/GL/LCC/ULCC/RFSC/REG/LEI/OTH — see Part 1 Dimension 1. **987/987 rows assigned as of v3.3.2 (2026-06-22)** — Jon's full manual categorization pass, see Part 1 note and Part 7 item 4)
- parent_airline_id (FK self-referential — only populated for 13 rows: Avianca/Lion Air/SAS/Smartwings/Tuifly subsidiaries. NOT populated for US regional subsidiaries — see REG note above)
- **investment_decision_pattern** (FE/TC/CR/HY — secondary attribute, used by Reaction Engine)
- trigger_primary, trigger_secondary_1, trigger_secondary_2 (fleet_delivery/competitor_response/financial_milestone/time_cycle/fleet_age/partner_influence)
- peer_sensitivity (High/Moderate/Low)
- region, country, alliance (Star/Oneworld/SkyTeam/None)
- **influence_tier** (1–4)
- brand_product_score, competitive_visibility_score, network_relevance_score, fleet_complexity_score, reaction_trigger_rate_score (1–5 each; sum = influence_tier_score)
- is_active, notes
- **iata_code coverage: 208/987 populated** (was 23/981) — backfilled from AeroLOPA in Part 8 Step 1, done 2026-06-19.
- 987 rows total (was 981 — +6 new rows created during Part 8 Step 1 for AeroLOPA-tracked carriers with no existing match).

---

**`competitive_clusters`**
- id, cluster_name, cluster_type (route_overlap/product_segment/alliance_block)
- description, intensity (0.0–1.0), notes

**`airline_cluster_membership`** — M2M: airlines ↔ clusters
- airline_id (FK), cluster_id (FK), is_primary_cluster

---

**`aircraft_types`** — aircraft model reference
- id, oem (Boeing/Airbus/Embraer/Bombardier/ATR), family, model
- category (Narrowbody/Widebody/Regional/Turboprop)
- typical_range (Short/Medium/Long/Ultra-Long), notes
- 95 rows total (was 82) — +13 added during Part 8 Step 2 for AeroLOPA-only families (ATR42/72, Dash 8/Q400, Britten-Norman Islander, Saab 340, Fokker 100, Embraer 135/140, CRJ-550, Boeing 737-400 Combi, etc.). Crosswalk done — only 1 of 1,512 AeroLOPA configs remains unmatched to an `aircraft_types` row.

---

**`subfleets`** — cabin configurations per airline × aircraft type, split to per-LOPA-config grain for AeroLOPA-covered pairs (Part 8 Step 4, done 2026-06-19)
- id, airline_id (FK), aircraft_type_id (FK)
- subfleet_name — e.g. "Oasis", "Transcon" for legacy Manual rows; for AeroLOPA-sourced rows, `{aircraft_types.model}` alone if the pair has exactly one LOPA config, or `{model} ({lopa_config_code})` if the pair has multiple (zero naming collisions across the table)
- seats_first_recliner, seats_first_lieflat, seats_domestic_first
- seats_j_recliner, seats_j_lieflat
- seats_premium_economy, seats_economy_plus (Y+), seats_economy (Y), seats_total
- **has_ife** (boolean), **ife_type** (AVOD-Seatback/Overhead/BYOD-Streaming/No-IFE) — the original v3.3 whole-subfleet pair, auto-drafted 2026-06-22 from AeroLOPA's Cabin Details `IFE Description` free-text field. **Superseded in the workbook as of v3.4 (2026-06-22)** by the 8 columns below — Jon asked to break IFE out by seat type, and AeroLOPA's source data supports exactly the 4-way cabin-class grain, not a finer one. `has_ife`/`ife_type` remain in the DB (nothing else references them) but are no longer surfaced in `01_Fleet_Baseline`.
- **has_ife_first / ife_type_first, has_ife_business / ife_type_business, has_ife_premium_economy / ife_type_premium_economy, has_ife_economy / ife_type_economy** (4 boolean/text pairs, added v3.4, 2026-06-22 by `scripts/add_ife_by_cabin_class_columns.py`) — same `AVOD-Seatback/Overhead/BYOD-Streaming/No-IFE` taxonomy, one pair per cabin class. **Initial state (2026-06-22):** auto-drafted by `scripts/populate_ife_by_cabin_class.py` from AeroLOPA's per-cabin-segment `ife_description` (join path: `subfleets.notes` regex → `aerolopa_snapshot_configs` (3-way match on airline/aircraft_type/lopa_config_code, needed because one airline+type pair can have up to 18 distinct configs) → `aerolopa_snapshot_cabins` (per cabin_type_code F/J/W/M)) — covered 78/932/264/1,477 of 2,753 active subfleets respectively, rest left NULL. **Current state (manual edit sync, 2026-06-23):** Jon filled in every remaining blank cell directly in the workbook for all 2,753 active subfleets (going beyond AeroLOPA's coverage in places — e.g. First TRUE rose from 70 to 92) and it was pushed to the DB via `scripts/sync_v34_manual_edits.py`, a full overwrite by subfleet id. Live counts (out of 2,753 active): First 92 TRUE / 2,661 FALSE, Business 655 TRUE / 2,098 FALSE, Premium Economy 231 TRUE / 2,522 FALSE, Economy 730 TRUE / 2,022 FALSE / **1 still NULL** (subfleet 12019, Eastern Airlines 767-300ER — `ife_type_economy` says 'No-IFE' but `has_ife_economy` was left blank in the workbook; looks like an unintentional miss, pushed through as NULL rather than guessed, worth a 1-cell fix). **NULL ≠ FALSE here, unlike the legacy pair**: NULL means "no seats of this class in this config / not covered," FALSE means "confirmed no IFE in this cabin." The 878 closed/superseded Manual subfleet rows (history only, not shown in the workbook) remain untouched/NULL across all 4 classes, as do any future new subfleets until reviewed. **Known internal contradictions in Jon's entries, pushed to DB as-is (not auto-corrected — needs his judgment call, not a guess):** 15 rows have Has IFE? (First)=YES with IFE Type='No-IFE'; 25 rows have Has IFE? (Business)=NO with a real IFE Type filled in anyway (mostly BYOD-Streaming on regional-jet fleets — CRJ/E-Jet/Dash 8 at American, Delta, United, Qantas, Air Astana, Virgin Australia, WestJet Encore); 1 row has Has IFE? (Business)=YES with IFE Type='No-IFE' (Hi Fly A330-200); 2 rows have Has IFE? (Prem Eco)=NO with a real IFE Type filled in (Qatar Airways and Eva Airways 777-300ER).
- **has_connectivity** (boolean, default FALSE), **connectivity_notes** (text) — new 2026-06-22 (v3.3), independent of the IFE fields above. **No connectivity/WiFi-provider data source exists anywhere in the pipeline** (AeroLOPA doesn't track it), so these are blank for every row by design — 100% manual entry, per Jon's confirmed choice.
- **retirement_age_override** (numeric(4,1)) — new 2026-06-22 (v3.3). NULL = use the Size Class default from `retirement_age_defaults` (see Group F below); set only for a subfleet with a known retirement/conversion plan that differs from the default.
- galley_type (Standard/Premium/Galley-Heavy), lav_count — **left NULL on all AeroLOPA-sourced rows**, deliberately out of scope (AeroLOPA's free-text IFE/WiFi fields don't map cleanly to these CHECK-constrained categories)
- **seats_j_privacy_door**, and new (2026-06-19) **seats_first_privacy_door** — integer counts of J/F seats with a privacy door/suite, summed from AeroLOPA's `aerolopa_snapshot_cabins.privacy_door_status = 'Confirmed'` rows, joined on (airline, LOPA config, cabin type J/F). `seats_first_privacy_door` was added specifically because there was no column to hold First-class suite counts before this. Currently 63 / 38 rows respectively have a nonzero value. **Correction 2026-06-23 (Jon):** `seats_j_lieflat` is now zeroed wherever `seats_j_privacy_door` is nonzero — a privacy-door business seat (a suite) is no longer also double-counted as a plain lie-flat seat. Affects exactly the 63 rows with nonzero `seats_j_privacy_door`; applied in the workbook by Jon directly, pushed to the DB via `scripts/sync_v34_manual_edits.py`. No equivalent correction was needed/made for `seats_first_lieflat` vs `seats_first_privacy_door` — First class privacy door isn't broken out as its own workbook column.
- **deck** (text, nullable — 'Upper'/'Lower'). **Deck distinction abandoned going forward as of 2026-06-19**: AeroLOPA's Cabin Deck field turned out to be 100% empty (confirmed by direct file inspection, not an extraction bug), which killed the original plan to rebuild the Upper/Lower split from cabin-level deck tags. Of the 23 legacy deck-split pairs (46 rows), 16 were AeroLOPA-covered (Emirates A380, Lufthansa, Qatar, Singapore, ANA, Korean Air, British Airways, Qantas, Asiana, Air China, Etihad) and got collapsed to one row per LOPA config with `deck = NULL`; their old deck-split rows are now closed (see valid_to below), not deleted. The remaining 7 pairs (14 rows) aren't AeroLOPA-covered and keep their original deck split untouched.
- valid_from, valid_to — **now actively used** (first real exercise of this mechanism, Part 8 Step 4). Refreshing a pair closes the superseded row (`valid_to = today`, renamed with suffix `" [Manual, closed {date}]"` — required because `UNIQUE(airline_id, aircraft_type_id, subfleet_name)` applies across all rows regardless of `valid_to`) and inserts a new active row rather than overwriting or deleting.
- source (AeroLOPA/Manual/OEM) — no longer 100% 'Manual'; see row counts below
- last_updated, notes — AeroLOPA-sourced rows carry a regex-parseable LOPA config code in a fixed format: `"AeroLOPA 2026-Q2 snapshot. LOPA config: {code}. Loaded {date}."` (load-bearing — Part 8 Step 5 recovers the config code from this field, there's no dedicated column for it)
- **3,631 rows total** (was 2,120): 1,242 active Manual + 1,511 active AeroLOPA + 878 closed/superseded Manual (kept as permanent history, never deleted). 1,033 of 2,097 distinct (airline, aircraft_type) pairs are AeroLOPA-covered; for the other ~1,064 pairs AeroLOPA doesn't track, the original Manual row is untouched per the supersede-if-covered/fallback-if-not rule. See Part 8 Step 4 for full detail.

---

**`suppliers`** — companies selling into the aviation interiors market
- id, name, ticker (if public), hq_country, parent_company
- tier_in_supply_chain (1 = direct to airline/OEM, 2 = to seat OEM, 3 = materials/components)
- is_public, is_active, notes

**`supplier_product_categories`** — M2M: what each supplier sells
- supplier_id (FK), product_category, product_subcategory
- market_position (Leader/Challenger/Niche), cabin_class_focus (Economy/Business/First/All)

---

### Group B — Event Tables (append-only; grow over time)

---

**`cabin_events`** — the intelligence backbone (590 historical events imported; ongoing from Hoku)

The `is_announcement` flag is the most important field in this table. When TRUE, it means a program has been publicly confirmed — it is already won by a supplier and is NOT an open opportunity. However, it IS a trigger for Reaction Engine analysis of peer airlines.

- id, event_id (EVT-XXXX for historical compatibility)
- airline_id (FK), event_date, year, quarter
- event_type (Retrofit_Program/IFE_Connectivity/Premium_Economy_Intro/Lounge_Investment/Seat_Replacement/Fleet_Delivery/Densification/Fleet_Retirement/Route_Expansion/Sustainability/Lessor_Transition/Financial_Milestone/Partner_Influence/New_Product_Launch)
- signal_family, cabin_class (All/Economy/Business/First/Premium_Economy)
- scope (New_Deliveries_Only/Full_Fleet/Partial_Fleet)
- trigger_context (fleet_delivery/competitor_response/new_product_launch/fleet_retirement/route_expansion/densification/financial_milestone/age_cycle/partner_influence)
- peer_reference_airline_id (FK, nullable — the competitor cited as the driver)
- capex_mentioned (boolean), capex_amount_text, capex_amount_usd (parsed)
- retrofit_target_year
- **is_announcement** (boolean) — TRUE = program confirmed/awarded; FALSE = signal/indicator
- event_summary, confidence (High/Medium/Low), verified (boolean)
- source_type (SEC/Press_Release/Earnings_Call/Trade_Press/Conference)
- source_document (URL or filename)
- notion_signal_url (text, nullable — Notion page URL for cross-reference)
- created_at, updated_at, notes

**`event_aircraft`** — M2M: one event can span multiple aircraft types
- event_id (FK), aircraft_type_id (FK), aircraft_count

---

**`supplier_program_wins`** — structured supplier win record

Note: Supplier wins are currently stored as narrative text in Notion state pages (e.g., "Recaro — Supplier State"). There is no structured wins database in Notion. This table is built fresh using those narrative pages as source material and supplemented by press releases and trade publications.

- id, event_id (FK → cabin_events — the confirmed announcement)
- supplier_id (FK), product_category, product_subcategory
- contract_type (SFE/BFE/MRO_Sole_Source/MRO_Approved_Vendor/Refurbishment)
- fleet_count, contract_value_usd (nullable — if disclosed)
- announced_date, estimated_production_start
- confidence (High = confirmed press release / Medium = inferred / Low = rumored)
- source, notes, created_at, updated_at

**`sub_supplier_relationships`** — supply chain linkages (Tier 1 to Tier 2/3 suppliers)
- id, tier1_supplier_id (FK), tier2_supplier_id (FK)
- product_link (what Tier 2 provides to Tier 1)
- relationship_type (Sole_Source/Qualified/Occasional)
- confidence (High/Medium/Low), notes

---

**`reaction_events`** — commercial opportunities generated by the Reaction Engine

When a Tier 1/2 airline makes an announcement (is_announcement = TRUE), the Reaction Engine identifies peer airlines likely to respond. Each row here is one opportunity — a specific target airline with a probability and timing window. The `forecast_opportunity_value_usd` field is the key output that bridges qualitative intelligence to quantitative value.

- id, trigger_event_id (FK → cabin_events), target_airline_id (FK)
- reaction_probability (0.0–1.0), timing_window_min_months, timing_window_max_months, timing_bucket
- signal_multiplier, age_modifier, cluster_modifier, investment_pattern_modifier
- final_probability (0.0–1.0), priority_band (High/Medium/Low)
- recommended_action (text — brief-ready language)
- **forecast_opportunity_value_usd** — calculated as: target airline fleet × subfleet seat counts × spend assumptions × final_probability
- status (Open/Materialized/Expired/Cancelled)
- materialized_event_id (FK → cabin_events, nullable — logged when the reaction actually occurs)
- week_identified, created_at, updated_at, notes

**`retrofit_baseline`** — one row per subfleet; the last known/estimated retrofit year, derived from `cabin_events` (built 2026-06-17, NOT the same thing as `retrofit_events` below — this is a denormalized one-row-per-subfleet rollup specifically built to feed `01_Fleet_Baseline` in the xlsx template)
- id, subfleet_id (FK, UNIQUE), airline_id (FK), aircraft_type_id (FK)
- last_confirmed_retrofit_year (integer, nullable)
- confidence (High/Medium/Low), status (Confirmed/Estimated/Unknown)
- source_event_id (FK → cabin_events), match_basis (text — e.g. 'model-exact', 'family-fallback', 'family-single', 'family-multi')
- notes (text — carries advisory info like a future-dated/planned retrofit that didn't qualify for last_confirmed_retrofit_year)
- created_at, updated_at
- **3,631 rows total** (was 2,120): 106 Confirmed, 97 Estimated, 3,428 Unknown. +1,511 rows from Part 8 Step 5 (2026-06-19) — exact 1:1 with `subfleets`, maintaining the established invariant that every active subfleet has exactly one `retrofit_baseline` row (the new AeroLOPA-sourced rows mostly land in 'Unknown' since they carry no prior retrofit history; a handful inherited a Confirmed/Estimated status copied forward from the subfleet they were split out of). Originally built by per-airline-scoped fuzzy matching of `cabin_events.aircraft_type` (free-text, semicolon-delimited) against that airline's actual `subfleets`, restricted to events at or before the current year (2026) — future-dated retrofit announcements are surfaced only as a note, never populate last_confirmed_retrofit_year. **Known coverage gaps (structural, not bugs):** retired aircraft types with no current `subfleets` row, and regional-subsidiary fleets not linked via `parent_airline_id` (see REG note in Part 1).
- **This table is a derived/exported artifact, not hand-edited.** Refresh by re-running the matching script against `cabin_events`, not by editing rows directly.
- `cabin_events.cabin_class` already distinguishes **All (409) / Premium_Economy (92) / Economy (47) / Business (42) / First (5)** — meaning ~186 of 595 events already carry cabin-specific signal. The xlsx template's Premium/Economy retrofit-timing columns (Part 6) are already structurally built to consume a cabin-tier-aware version of this table — **but the matching script itself has not yet been rebuilt to actually populate them.** That's separate, unscheduled work (see Part 7 item 3), distinct from the AeroLOPA project in Part 8 (AeroLOPA carries current seat configuration, not retrofit timing/event history).

**`retrofit_events`** — detailed retrofit records; drives forecast timing resets
- id, event_id (FK → cabin_events)
- airline_id (FK), aircraft_type_id (FK, nullable), subfleet_id (FK, nullable)
- announcement_date, retrofit_start_year, retrofit_complete_year_est, fleet_count
- cabin_classes_affected
- **resets_forecast_timing** (boolean) — TRUE causes forecast_master rows for this airline × aircraft to reset retrofit_last_completed_year and recalculate forward spend
- notes

---

### Group C — Forecast Tables (quantitative engine)

---

**`forecast_versions`** — one row per vintage
- id, name (2022_Forecast / 2024_Forecast / 2026_Forecast / 2027_Forecast)
- published_date, start_year, end_year
- is_live (boolean — only one TRUE; the working forecast used for opportunity calculations)
- based_on_version_id (FK self-referential — 2027 based on 2026), notes
- Current rows: `2022_Forecast` (id 1), `2024_Forecast` (id 2), `2026_Forecast` (id 3, **is_live = TRUE**).

---

**`assumptions`** — cost rates driving all spend calculations

Separating rates from data means: change one rate → every forecast row using it recalculates. No more hunting through Excel formulas.

- id, forecast_version_id (FK)
- product_category (see spend categories below), service_type (Replace/Repair)
- aircraft_category (Narrowbody/Widebody/Regional), cabin_class (Economy/Business/First/Premium_Economy/All)
- cost_per_seat_usd (for seat-based categories), cost_per_aircraft_usd (for non-seat)
- interval_years (replacement or repair cycle length)
- effective_date, source, notes

---

**`forecast_master`** — spine; one row per airline × subfleet × year × version

Replacing the flat "operator + aircraft model" with subfleet_id enables proper subfleet differentiation (AA Oasis vs. Transcon) and connects seat counts directly to spend calculation.

- id, forecast_version_id (FK), airline_id (FK), subfleet_id (FK), year
- fleet_count, deliveries, avg_age
- **retirements, fleet_count_adjusted** (both numeric(8,3), new 2026-06-22, v3.3) — `fleet_count` above is left untouched (licensed, no retirements); `fleet_count_adjusted` is a transparent, separate overlay so the consultant's published numbers are never silently overwritten. Rule: once a subfleet's `avg_age` crosses its effective retirement age (subfleet override on `subfleets.retirement_age_override`, else the Size Class default from `retirement_age_defaults`), 20% of the prior year's adjusted fleet retires annually (a 5-year phase-out), netted against scheduled deliveries. Computed for all 36,266 rows (2026–2035, live `2026_Forecast` version). Across all forecast subfleets this drops the 2035 fleet total from 63,938 (licensed) to 54,031 (adjusted) — ~9,400 cumulative retirements by 2035.
- retrofit_interval_adj, repair_interval_adj, repair_interval_adj_v2
- retrofit_last_completed_year (nullable — updated by retrofit_events with resets_forecast_timing = TRUE)
- **seat_data_source** (Actual/Average/**AeroLOPA** — describes how fleet_count/avg_age were derived. Currently 16,810 'Actual' / 4,346 'Average' / **15,110 'AeroLOPA'** across the live 2026_Forecast.) **Do not confuse this with `01_Fleet_Baseline` column R "Seat Data Source" in the xlsx (Assumption/AeroLOPA/Actual) — that's a different, newer concept describing seat-*configuration* provenance, lives only in the xlsx today, and has no DB-side column yet. `subfleets.source` is the intended backing field for the xlsx column; see Part 6 and Part 8.**
- data_confidence (High/Medium/Low — was 100% 'Medium'; now 35,466 'Medium' / **800 'Low'**. The 800 are brand-new (airline, aircraft_type) combos from Part 8 Step 5 with no AeroLOPA aircraft count to seed `fleet_count` from — flagged for manual review.)
- last_updated, updated_by, notes
- **36,266 rows total** (was 21,156, live 2026_Forecast version only) — +15,110 from Part 8 Step 5 (2026-06-19): the AeroLOPA subfleet split propagated to forecast rows.

---

**`forecast_spend`** — full granularity; one row per master_id × spend_line_item

> **DB reality (confirmed 2026-06-30):** The live DB table is named `forecast_spend` (not `forecast_spend_detail` as originally planned). **20,926 rows confirmed populated** for the live `2026_Forecast` version as of 2026-06-30. There is no separate `forecast_spend_totals` table — totals are handled by views (see Spend Rollup Views below). Use `forecast_spend` in all queries.

Stores all ~40 line items from the current Excel model. This means the database is the single source of truth and the Excel files are no longer needed for reference.

**Spend line items tracked (both Replace and Repair where applicable):**
- Economy Seats, True PY Seats, Business Class Seats, Dom. First Class Seats, First Class Seats
- Carpets, Flooring, Curtains
- Seat Covers (Economy/Business/Dom. First/First)
- Seat Cushions (Economy/Business/Dom. First/First)
- Cut & Sew (Economy/Business/Dom. First/First)
- Seat Belts (Flight Crew/Standard/Regulatory)
- Lavatories, Laminates
- Panels (Ceiling/Sidewalls/Overhead Bins/Latches/Window Shades)
- Galleys, Ovens, Coffee/Beverage Makers, Carts, Chillers, Liquid Chillers
- Stowage/Closets, Overhead Lighting, IFEC
- Engineering / Certification, Misc Parts Kits

Fields:
- id, master_id (FK → forecast_master)
- spend_line (text — the specific item name, e.g., "Economy Seats Replace")
- product_category (rollup group — see views below)
- service_type (Replace/Repair)
- assumption_id (FK → assumptions — the rate used)
- spend_usd
- is_override (boolean — TRUE if manually overridden from the formula-driven rate)
- override_reason (text, nullable)

---

> **Note:** `forecast_spend_totals` as a standalone table does not exist in the live DB — summary aggregates are handled by the views below.

---

**Spend Rollup Views** (database views — not tables; calculated automatically from spend_detail)

Views behave like tables for query purposes but contain no stored data — they always reflect the current state of spend_detail. Define the rollup logic once; every query gets correct aggregation.

| View Name | What It Aggregates |
|-----------|-------------------|
| `v_spend_by_seats` | All seat categories (Economy/PY/Business/First) combined |
| `v_spend_by_softgoods` | Seat covers + cushions + cut & sew + curtains + seat belts |
| `v_spend_by_panels` | All panel types (ceiling/sidewall/bins/latches/shades) |
| `v_spend_by_galley` | Galleys + inserts (ovens/coffee makers/carts/chillers) |
| `v_spend_by_major_category` | 8–10 rolled-up categories (Seats/Soft Goods/Hard Goods/IFE/Galleys/Lav/Lighting/Engineering) |
| `v_spend_by_region_year` | Totals grouped by region + year (Insperial data table format) |
| `v_spend_by_airline_category` | Totals grouped by airline_category + year |
| `v_spend_comparison` | Side-by-side totals for all forecast versions in overlapping years |

---

### Group D — Hoku Allocation Tables

---

**`airline_allocation_scores`** — weekly model state; append-only (never overwrite)

One row per airline per week creates a full audit trail of how the model evolved, and enables retrospective accuracy analysis (predicted vs. actual reaction timing).

- id, airline_id (FK), week_label (e.g., "Wk23"), score_date
- stage (Early/Emerging/Actionable/Urgent)
- compression (0–100), earnings (0–100), capital_modifier, cluster_intensity
- base_proximity (calculated), stage_bonus (calculated)
- allocation_score (calculated), allocation_tier (Tier 1/2/3), influence_tier (1–4)
- previous_score_id (FK self-referential — enables delta calculation), notes

**`model_adjustments`** — log of every Stage/Compression/Earnings change with signal linkage
- id, airline_id (FK), week_label, adjustment_date
- notion_signal_url (text — the Notion Raw Signal Intake page URL that drove this)
- cabin_event_id (FK → cabin_events, nullable — if the signal became a logged event)
- stage_before, stage_after, compression_delta (-2 to +2), earnings_delta (-2 to +2)
- allocation_score_before, allocation_score_after
- rationale (text), created_at

**`watchlist`** — forward signals being monitored; updated weekly
- id, airline_id (FK), aircraft_type_id (FK, nullable)
- forward_signal (text — what to watch for)
- probability_window (e.g., "2026-2028"), priority (High/Medium/Low)
- status (Active/Triggered/Expired)
- triggered_event_id (FK → cabin_events, nullable — set when signal fires)
- identified_week, created_at, updated_at

---

### Group E — System / Audit Tables

**`data_sources`** — registry of all external data inputs
- id, name (AeroLOPA/SEC/Cirium/CAPA/Trade_Press/etc.)
- source_type (API/Manual/Licensed/Public)
- refresh_cadence (Weekly/Monthly/Quarterly/Ad-Hoc)
- last_refreshed, api_endpoint (nullable), notes

**`audit_log`** — every material data change (auto-populated by database triggers)
- id, table_name, record_id, field_name
- old_value, new_value, changed_by, changed_at, change_reason

---

### Group F — Retirement Modeling (new 2026-06-22, v3.3; values updated 2026-06-22, v3.4)

**`retirement_age_defaults`** — one row per Aircraft Size Class; the final tier of the retirement-age cascade (`subfleets.retirement_age_override` → this table)
- id, aircraft_size_class (Narrowbody/Widebody/Regional/Turboprop — same 4-value CHECK as `aircraft_types.category`)
- default_retirement_age (numeric(4,1)), notes
- **4 rows. v3.3 shipped these as DRAFT placeholders (Widebody 25.0, Narrowbody 25.0, Regional 20.0, Turboprop 30.0); v3.4 (2026-06-22) replaces them with Jon's researched values: Widebody 20.0, Narrowbody 25.0, Regional 30.0, Turboprop 30.0.** Feeds `01_Fleet_Baseline`'s Effective Retirement Age column and the `forecast_master.retirements`/`fleet_count_adjusted` computation (Group C above).
- **Known inconsistency, flagged for Jon, not yet resolved:** the Regional row's `notes` text still reads to the effect of "regional jets are often retired/parted-out earlier than mainline narrowbody" (the rationale for the old 20.0 value), but the new value of 30.0 is now the *highest* of all four size classes — directly contradicting that stated rationale. Either the value or the note needs revisiting; flagged in the v3.4 workbook's `00_Instructions` and `04_Import_Guide` sheets but the underlying `notes` text itself was deliberately left untouched pending Jon's input.
- Simpler than the retrofit cascade by design (Jon's choice) — 2-tier, no airline-level middle tier, since retirement timing is driven by the airframe itself rather than airline-specific program decisions.
- `scripts/create_schema.py` Group F creates this table and adds the `subfleets`/`forecast_master` columns above via idempotent `ADD COLUMN IF NOT EXISTS` statements (needed because those two tables already existed on the live DB when this feature was added, so the base `CREATE TABLE IF NOT EXISTS` blocks in Groups A/C are no-ops there).

---

## Part 3: The Integration Bridges

### Bridge 1: Announcement → Quantified Opportunity

```
Airline announces retrofit (cabin_events, is_announcement = TRUE)
         ↓
Reaction Engine identifies peer airlines likely to respond
         ↓
reaction_events row created per target airline:
  probability, timing window, signal/age/cluster modifiers
         ↓
forecast_opportunity_value_usd calculated:
  target airline fleet (forecast_master)
  × seat counts by class (subfleets)
  × spend rates (assumptions)
  × final_probability
         ↓
Weekly brief: "United represents ~$Xm probability-weighted
opportunity in the 18-36 month window"
```

### Bridge 2: Signal → Forecast Timing Reset

```
Signal: ANA confirms 37-aircraft 787 retrofit program
         ↓
cabin_event created (is_announcement = TRUE)
retrofit_event created (resets_forecast_timing = TRUE)
         ↓
forecast_master: ANA × 787-8 × future years
  retrofit_last_completed_year = announcement year
  retrofit interval resets from zero
         ↓
forecast_spend_detail recalculates forward
```

### Bridge 3: Supplier Win → Sub-Supplier Targeting

```
Supplier win logged: "Recaro wins ANA 787 business class program"
         ↓
sub_supplier_relationships queried:
  Recaro's foam/fabric/leather/mechanism suppliers identified
         ↓
Output: "[Foam supplier] — ANA 787 production starting [date];
  Recaro capacity partially committed → target adjacent airlines early"
         ↓
Reaction Engine: ANA-adjacent airlines (United, Lufthansa, Air Canada)
  flagged as opportunity targets for suppliers competing against Recaro
  while Recaro capacity is constrained
```

### Bridge 4: Notion ↔ PostgreSQL (confirmed field mapping)

Notion's Raw Signal Intake database maps directly to PostgreSQL. The Notion page URL serves as the cross-reference key.

| Notion Field | PostgreSQL Destination |
|-------------|----------------------|
| Signal (title) | hoku_signals.signal_title |
| Signal Date | hoku_signals.signal_date |
| Pillar (Airline/Supplier/OEM/Lessor/Macro) | hoku_signals.pillar |
| Signal Type (Capital Expansion/Competitive Compression/Execution Risk/Portfolio Rotation/Noise) | hoku_signals.signal_type |
| Trigger Category (9 options) | hoku_signals.trigger_category |
| Quick Score (1–5) | hoku_signals.quick_score |
| Reaction Multiplier (Low/Medium/High) | hoku_signals.reaction_multiplier |
| Market Impact Scope (Airline Allocation/Supplier Landscape/Both) | hoku_signals.market_impact_scope |
| Market Theme (7 options) | hoku_signals.market_theme |
| Triage Worthy (boolean) | hoku_signals.triage_worthy |
| Why It Matters | hoku_signals.why_it_matters |
| Source Type | hoku_signals.source_type |
| Link (URL) | hoku_signals.source_url |
| Week Of (relation → Weekly Cycles) | hoku_signals.week_label |
| page URL | hoku_signals.notion_signal_url |

**What stays in Notion only:** Raw discovery outputs, CPO review commentary, article/SEC filing full text, weekly brief drafts, qualitative editorial notes, state page narratives (airline/supplier/OEM/lessor).

**What lives in PostgreSQL only:** All numerical scores, fleet data, spend calculations, forecast vintages, assumptions, reaction candidates, opportunity values, allocation score history.

**Sync cadence:** Weekly Python script pulls promoted signals from Notion Raw Signal Intake → structures and writes to PostgreSQL hoku_signals → triggers model_adjustments logging if allocation scores changed.

---

## Part 4: What This Enables

### Hoku Weekly Brief
- **Quantified opportunities:** "The ANA retrofit creates ~$Xm in adjacent demand — United (85%, 18-36mo), Lufthansa (72%, 12-24mo), Air Canada (68%, 24-36mo)"
- **Watchlist monitoring:** "Which forward signals fired this week?"
- **Model accuracy tracking:** When a reaction_event materializes, log actual timing vs. predicted; refine multipliers over time

### Insperial SOW Deliverables (due 31 Aug 2026)
- Seat counts by class / service type / region → `v_spend_by_region_year` view, one query
- Materials split (Leather/Synthetic/Fabric) → `forecast_spend_detail` filtered by product subcategory
- 2024–2036 forecast table → `forecast_master` joined to `forecast_spend_totals` for the live version

### 2027_Forecast Build (Q4 2026)
- Create new `forecast_versions` row based on 2026
- Fleet/seat data refreshed from AeroLOPA's quarterly file → `subfleets` updated (mechanism built in Part 8)
- Retrofit timing already logged via `retrofit_events` from 14 months of Hoku signal history
- Assumptions adjusted in `assumptions` table → all spend recalculates automatically
- Delta vs. 2026_Forecast immediately queryable via `v_spend_comparison`

### Future: Natural Language Queries
- "What did we forecast for Delta in 2030 across all three vintages?" → SQL generated from question, runs against DB
- "Which airlines are most likely to launch a retrofit program in the next 18 months?" → `reaction_events` filtered by timing window and status
- "Which suppliers have the most widebody program wins in Europe?" → `supplier_program_wins` aggregated

---

## Part 5: Build Sequence

1. **Supabase setup** — create account, provision PostgreSQL instance
2. **Run CREATE TABLE scripts** — all tables above in dependency order (reference tables first)
3. **Create views** — spend rollup views
4. **Migrate historical data** — import three forecast vintages into new schema; import 590 cabin events CSV; import allocation model scores
5. **Seed reference tables** — airlines, aircraft_types, suppliers with current known data
6. **Set up Notion sync script** — weekly pull of Raw Signal Intake → hoku_signals
7. **Build 2026_Forecast subfleet layer** — AA Oasis/Transcon as first example; expand from there
8. **Connect Insperial query layer** — verify SOW data tables can be generated cleanly

---

## Part 6: `forecast_baseline_template_v3.4.xlsx` — Working Template Structure (v3.4)

> **STATUS 2026-06-22 (v3.4): retirement age defaults updated + IFE redesigned to per-cabin-class grain.** Two changes, both already live in the DB and the rebuilt workbook. (1) `08_Retirement_Defaults`'s 4 values replaced with Jon's researched numbers — Widebody 20, Narrowbody 25, Regional 30, Turboprop 30 (was the v3.3 DRAFT placeholders 25/25/20/30); see Part 2 Group F for the flagged Regional notes-text inconsistency this introduced. (2) `01_Fleet_Baseline`'s single whole-subfleet Has IFE?/IFE Type pair (v3.3 cols AK/AL) is replaced by 4 pairs — one per cabin class (First/Business/Premium Economy/Economy), cols AK–AR — because AeroLOPA's source data only supports IFE detail at the cabin-class grain, and Jon asked for the breakout by seat type. Has Connectivity?/Connectivity Notes shifted from AM/AN to AS/AT to make room (net +6 columns, A–AN → A–AT). New DB columns `has_ife_<class>`/`ife_type_<class>` (8 total) added via `scripts/add_ife_by_cabin_class_columns.py` and auto-drafted via `scripts/populate_ife_by_cabin_class.py`; see Part 2 Group A for the full join path and coverage numbers. Output saved as `forecast_baseline_template_v3.4.xlsx` via `scripts/build_template_v34.py`. Verified: zip integrity OK, reopen OK, all 9 sheets present, `01_Fleet_Baseline` 2,753 data rows × 46 cols, `08_Retirement_Defaults` 4 data rows × 3 cols, cell-level spot checks of fill colors/data validation ranges/sample classified IFE data all correct.
>
> **STATUS 2026-06-22 (v3.3.2): bulk airline categorization closed — `05_Airline_Defaults` col B is now DB-sourced, not file-carry-forward.** All 987 airlines now have a Category (was 23/987) — Jon's full manual pass, applied to `airlines.airline_category` via `scripts/apply_airline_categories_v2.py` (see Part 1 and Part 7 item 4). The rebuild script (`scripts/build_template_v332_fix.py`) was changed to query `airlines.airline_category` directly from the DB for this column instead of reading it from the prior workbook file — more robust going forward, consistent with the project's "PostgreSQL is the source of record for structured reference data" principle. Fill color for this column changed from yellow (input required) to **green (pre-populated from DB, editable)** to match. Cadence Notes (col F) is unaffected — still carried forward file-to-file, since no dedicated DB column exists for that free-text field. Verified: zip integrity OK, LibreOffice headless recalculation zero formula errors, zero duplicate rows on `01_Fleet_Baseline`/`05_Airline_Defaults`, and a full 987-row category cross-check against Jon's source file — zero mismatches, zero blanks, all green-filled.
>
> **STATUS 2026-06-22 (v3.3): two new features added on top of the v3.2 structure — retirement modeling and IFE/connectivity tracking.** New sheet `08_Retirement_Defaults` (4 rows, Size Class → default retirement age, DRAFT placeholders — see Group F in Part 2). `01_Fleet_Baseline` gained 7 columns, AH–AN: Retirement Age Override / Effective Retirement Age / Est. Retirement Start Year (AH–AJ, mirrors the retrofit cascade pattern but 2-tier — subfleet override → Size Class default, no airline-level middle tier), and Has IFE? / IFE Type / Has Connectivity? / Connectivity Notes (AK–AN). IFE was auto-drafted from AeroLOPA's Cabin Details `IFE Description` field for the 1,506 of 2,753 active subfleets AeroLOPA covers (711 real IFE systems, 795 confirmed No-IFE); the other 1,247 rows are left blank, not guessed. Connectivity has no source data anywhere, so it's blank for every row — 100% manual entry by design. Both decisions were Jon's, selected from two explicit architecture options presented 2026-06-22 (see Part 7). Output saved as `forecast_baseline_template_v3.3.xlsx` (new filename — the original `forecast_baseline_template.xlsx` appears locked, likely open in Excel) via `scripts/build_template_v33.py` (new filename — see the file-naming note at the top of this doc). Verified: zip integrity OK, reopen OK, all 9 sheets present with correct row/column counts (`01_Fleet_Baseline` 2,753 data rows × 40 cols, `08_Retirement_Defaults` 4 data rows × 3 cols).
>
> **STATUS 2026-06-19: rebuilt for the AeroLOPA-integrated subfleet grain and verified (Part 8 Step 6), then redesigned again same day for the full defaults grid (v3.2).** `scripts/build_template.py` was updated to query active subfleets only (`valid_to IS NULL`) and to read `subfleets.source` for column R, then re-run end to end. Output verified via LibreOffice headless recalculation (zero formula errors across all formula cells), direct row-count/duplicate checks (zero duplicate `subfleet_id` rows across all 2,753 rows), and a full row-by-row spot-check of column R against the live DB (`source='AeroLOPA'` → "AeroLOPA", else → "Assumption"; zero mismatches across all 2,753 rows). Coverage is now the **full 987 airlines / 2,753 active subfleets** (1,242 Manual + 1,511 AeroLOPA; was 981/2,120 in v3.0 — superseded/closed Manual rows are excluded from the template but remain in the DB as history per `valid_to`).
>
> **Mid-rebuild discovery and fix (2026-06-19, v3.1):** the first rebuild attempt produced 219 `#N/A` errors in cols X/AA/AD (the Effective Retrofit Interval cascade). Root cause: `aircraft_types.category` gained a `Turboprop` value back in Part 8 Step 2, but `retrofit_interval_defaults` (the final fallback tier of the cascade, feeding `06_Retrofit_Defaults`) had no Turboprop row and its CHECK constraint didn't even allow one — a gap left over from Step 2 that nothing had exercised until Step 6's cascade formulas hit it (73 active Turboprop subfleets, no row class with a usable default). Fixed by updating the `retrofit_interval_defaults_aircraft_size_class_check` CHECK constraint to permit `'Turboprop'` and inserting one new blank-category fallback row, by analogy to the existing Regional/Narrowbody/Widebody blank-category defaults. This 15-row, blank-category-catch-all design was the v3.1 state and was superseded same-day by the v3.2 redesign below.
>
> **v3.2 redesign (2026-06-19): `06_Retrofit_Defaults` rebuilt as a full 32-row grid.** Jon's direction: the sheet should have one row for every (Size Class × Airline Category) combination — 4 Size Classes (**Widebody, Narrowbody, Regional, Turboprop**) × 8 Airline Categories (**FSC, GL, LCC, ULCC, RFSC, REG, LEI, OTH**) = 32 rows, no blank-category placeholder rows. **OTH is now an explicit row per size class, and it is the row every uncategorized airline resolves to** — the cascade formula was simplified to match: `IF(VLOOKUP(airline, 05_Airline_Defaults, Category)="", "OTH", that category)`, then a normal lookup against `06_Retrofit_Defaults` on `SizeClass|Category`. There is no separate blank-category fallback tier anymore; resolving to OTH *is* the fallback, by construction. The 32 starting values were generated with a consistent delta-from-OTH rule (FSC/GL/RFSC = OTH−1 yr, REG = OTH, LCC/LEI = OTH+1 yr, ULCC = OTH+3 yr) so every cell has a reasonable placeholder instead of being blank — **these are still draft placeholders**, to be replaced with real program intelligence over time.
>
> **Naming decision (v3.2):** "Regional" (aircraft size class) and "Turboprop" remain the literal stored values in the DB, in `aircraft_types.category`, and in every dropdown — they are **not** renamed to "Regional Jet" / "Turbopro" anywhere in the schema. Jon's call: friendlier labels are fine in prose/notes (e.g. referring to "Regional Jet" conversationally), but renaming the actual DB/dropdown values would mean touching the CHECK constraint, 21 aircraft rows, and every downstream formula reference for what is purely a cosmetic preference. They mean the same thing; only the words used to describe them in instructional text changed.

9 sheets, in order: `00_Instructions`, `01_Fleet_Baseline`, `02_Program_Scope`, `03_Pricing_Reference`, `04_Import_Guide`, `05_Airline_Defaults`, `06_Retrofit_Defaults`, `07_Retrofit_Baseline`, `08_Retirement_Defaults` (new, v3.3).

**Color convention (stated on `00_Instructions`, applied throughout):** Yellow = input required. Green = pre-populated from DB, editable/correctable. Grey = read-only. Black = formula. Header rows: navy fill, white bold; title rows: darker navy fill, white bold.

**`01_Fleet_Baseline`** (2,753 data rows, one per active subfleet, rows 3–2755; row 1 = group headers, row 2 = column headers) — columns A–AT (was A–AG through v3.2; AH–AN added v3.3; AK–AT restructured v3.4 — net +6 columns, AN→AT):

| Col | Group | Header | Notes |
|-----|-------|--------|-------|
| A | FROM DATABASE — verify, do not edit | Airline | |
| B | | Aircraft Model | |
| C | | Size Class | dropdown: Regional/Narrowbody/Widebody/Turboprop |
| D | | Subfleet Name | |
| E | | Deck | dropdown: Upper/Lower/blank — 16 active deck-split rows remain (the legacy pairs AeroLOPA doesn't cover; AeroLOPA-covered pairs collapsed to one row per LOPA config, `deck=NULL`, per Part 8 Step 4) |
| F–N | SEAT & FLEET CONFIG | F Lie-Flat, F Recliner, F Domestic, J Lie-Flat, J Recliner, J Privacy Door, Prem Eco, Eco Plus, Eco Seats | green, DB-sourced, meant to be corrected |
| O | | Total Seats | |
| P | | Fleet 2026 | |
| Q | | Avg Age 2026 | |
| R | SEAT DATA SOURCE | Seat Data Source | dropdown: Assumption/AeroLOPA/Actual. **Wired to `subfleets.source` as of Part 8 Step 6 (2026-06-19)** — reads "AeroLOPA" for the 1,511 AeroLOPA-sourced active rows, "Assumption" for the 1,242 Manual-sourced active rows. No longer hardcoded. |
| S | DB REF | Subfleet ID | used by VLOOKUPs elsewhere — don't touch |
| T | INPUTS — fill yellow cells | Include Forecast? | dropdown YES/NO |
| U | | Repair Interval (yrs) | |
| V–X | WHOLE AIRCRAFT RETROFIT (non-seat spend + fallback) | Retrofit Last Year, Retrofit Interval Override, Effective Retrofit Interval | V pre-populated green from `retrofit_baseline` where Confirmed/Estimated, blank/yellow otherwise; W is the per-subfleet override; X is the resolved cascade output (formula) |
| Y–AA | PREMIUM CABIN RETROFIT (First / Business / Privacy Door) | Retrofit Last Year, Retrofit Interval Override, Effective Retrofit Interval | structurally identical to V–X but for the premium track. **Y is currently always blank — `retrofit_baseline` doesn't yet populate a premium-specific value (see Part 7 item 3).** |
| AB–AF | ECONOMY CABIN RETROFIT (Prem Eco / Eco Plus / Economy) + mid-life refresh | Retrofit Last Year, Retrofit Interval Override, Effective Retrofit Interval, Economy Mid-Life Refresh? (Y/N), Economy Mid-Life Refresh Year | same caveat as Premium — AB is currently always blank |
| AG | NOTES | Notes | DB-sourced match/confidence notes auto-appended; also where Jon should flag manual seat-count corrections until/unless a dedicated tracking column is added |
| AH–AJ | RETIREMENT ASSUMPTIONS (new v3.3) | Retirement Age Override, Effective Retirement Age, Est. Retirement Start Year | AH = per-subfleet override (yellow, optional); AI = resolved cascade output (formula: AH if set, else `08_Retirement_Defaults` Size Class lookup); AJ = formula, first forecast year (2026–2035) avg age is projected to cross the effective retirement age, blank if it never does by 2035 |
| AK–AR | IFE BY CABIN CLASS (replaces single AK/AL pair, v3.4) | Has IFE? (First), IFE Type (First), Has IFE? (Business), IFE Type (Business), Has IFE? (Prem Eco), IFE Type (Prem Eco), Has IFE? (Economy), IFE Type (Economy) | one Has-IFE?/IFE-Type pair per cabin class, auto-drafted from AeroLOPA's per-cabin `ife_description` where covered (green) else blank (yellow); IFE Type dropdown: AVOD-Seatback/Overhead/BYOD-Streaming/No-IFE. Coverage out of 2,753: First 78, Business 932, Prem Eco 264, Economy 1,477 — see `subfleets` Group A entry for the True/False split per class |
| AS–AT | CONNECTIVITY (shifted from AM/AN, v3.4) | Has Connectivity?, Connectivity Notes | always blank — no connectivity data source exists anywhere, 100% manual entry by design |

**`05_Airline_Defaults`** (987 data rows, rows 3–989) — columns A–F: Airline, Category (dropdown, 8-value list, confirmed present; **green fill, DB-sourced as of v3.3.2** — see Part 6 status note above), Retrofit Years Override (Whole Aircraft), Retrofit Years Override (Premium), Retrofit Years Override (Economy), Cadence Notes. One row per airline (was 981, grew to 987 with the 6 new AeroLOPA-only airlines from Part 8 Step 1); the three override columns sit one level more specific than `06_Retrofit_Defaults` and one level less specific than the per-subfleet overrides on `01_Fleet_Baseline` (cols W/Z/AC). Leave the three override columns blank to inherit from the Size Class × Category default; Category itself is no longer blank for any airline (987/987 populated, v3.3.2) but can still be edited per row — note that a workbook-only edit will be replaced by whatever's in the DB on the next rebuild, so push corrections back to the DB rather than relying on a local edit surviving.
>
> **Direct answer to "do I fill this in for every airline?" (asked 2026-06-19, Category coverage answer superseded 2026-06-22 by v3.3.2):** the three retrofit-years override columns remain fully **OPTIONAL** — only set them for an airline whose retrofit cadence you know differs from its Size Class × Category default, otherwise leave blank and let it inherit. Category itself no longer needs a manual fill-in decision at all: all 987 airlines now carry a real, Jon-assigned category sourced live from the DB (see Part 1 and Part 7 item 4). The original OTH-fallback logic on `06_Retrofit_Defaults` (any airline with no Category resolves to the OTH row for its size class) remains the architecture for any future new airline added with no category set, but is no longer the active state for the current 987.

**`06_Retrofit_Defaults`** (32 data rows, rows 3–34) — columns A–H: Aircraft Size Class, Airline Category, Default Retrofit Years (Whole Aircraft), Default Retrofit Years (Premium), Default Retrofit Years (Economy), Default Repair Years, Lookup Key (formula: `=A{row}&"|"&B{row}`), Notes. Keyed by **Size Class × Airline Category**, wide by track. **Redesigned 2026-06-19 (v3.2) into a full grid: all 4 Size Classes × all 8 Categories = 32 rows, no blank-category placeholder rows.** OTH is an explicit row per Size Class and is the row every airline with no Category set on `05_Airline_Defaults` resolves to — see the v3.2 write-up above for the cascade-formula mechanics and the delta-from-OTH rule used to seed the 32 starting values. **These 32 values are still draft placeholders pending real program intelligence** — this is the highest-value sheet for Jon to refine over time, since every uncategorized or under-researched airline's forecast runs through it.

**`07_Retrofit_Baseline`** (2753 data rows, was 2120) — **read-only DB export of `retrofit_baseline`, refreshed by re-running the export script, never hand-edited.** Columns: Subfleet ID, Last Confirmed Retrofit Year (Whole Aircraft), Confidence, Status, Airline, Aircraft Model, Subfleet Name, Source Event, Match Basis, Notes, Last Confirmed Retrofit Year (Premium), Last Confirmed Retrofit Year (Economy). **Only the Whole Aircraft column is actually populated from `cabin_events` today; the Premium and Economy columns exist structurally but are placeholders (always blank) pending the cabin-tier-aware matching-script rebuild — see Part 7 item 3.** If Jon confirms/discovers a retrofit year for a row that shows Unknown, the right move is either (a) type it directly into `01_Fleet_Baseline`'s Retrofit Last Year column for that row only, or (b) better — tell Claude so the underlying `cabin_events`/`retrofit_baseline` DB rows get updated, which persists through future re-exports.

**`08_Retirement_Defaults`** (4 data rows, rows 3–6, new v3.3) — columns A–C: Aircraft Size Class, Default Retirement Age (yrs), Notes. One row per Size Class (Widebody/Narrowbody/Regional/Turboprop). **v3.3 shipped DRAFT placeholders (25/25/20/30); v3.4 (2026-06-22) replaces them with Jon's researched values — Widebody 20, Narrowbody 25, Regional 30, Turboprop 30.** Still editable — this is the sheet to refine further with real fleet-planning assumptions, same role `06_Retrofit_Defaults` plays for retrofit timing. **Flag:** the Regional row's Notes text wasn't rewritten along with the value and still gives the old "retired earlier than narrowbody" rationale, which the new 30-year value (now the highest of the four) contradicts — see Group F note in Part 2.

**`03_Pricing_Reference`** — 486 rows (414 original + 72 Turboprop, added v3.3.1 — see Part 7 item 9), read-only, Base Year 2026. **`00_Instructions`, `02_Program_Scope`, `04_Import_Guide`** — narrative/reference sheets, unchanged structurally from prior versions.

---

## Part 7: Smaller Open Items (post-v3.0)

1. **Seat count manual overrides (`01_Fleet_Baseline` F–N):** confirmed fine for Jon to overwrite green DB-sourced seat counts — green means "DB starting point," not "locked." Use the **Seat Data Source** dropdown (col R) to flag the new provenance once corrected (e.g. switch from "Assumption" to "Actual" after manually verifying a seat count), and/or note it in col AG.
2. **Three-tier override cascade — all overrides are optional, by design:** `01_Fleet_Baseline` cols W/Z/AC (per-subfleet) → `05_Airline_Defaults` cols C/D/E (per-airline) → `06_Retrofit_Defaults` (per Size Class × Category, including the explicit OTH row — see Part 6 v3.2). Each tier only needs filling in when you know that specific subfleet/airline differs from the next tier up. Leaving every override blank for an airline is a fully valid, intentional state — it just means "use the OTH default for this size class," not "incomplete data."
3. **Premium/Economy retrofit timing data — structure done, data not.** The cabin-tier split (Part 6, cols Y–AF) and `06_Retrofit_Defaults`/`05_Airline_Defaults` wide-by-track columns are built and live. What's still missing: the `retrofit_baseline` matching script needs a cabin-tier-aware rebuild so the Premium and Economy columns in `07_Retrofit_Baseline` actually populate instead of sitting blank. `cabin_events.cabin_class` already supports this (Business/First-tagged events → Premium track, Economy/Premium_Economy-tagged events → Economy track, "All"-tagged events as fallback for both). Unscheduled, independent of the AeroLOPA work in Part 8.
4. **Bulk airline categorization — RESOLVED (v3.3.2, 2026-06-22).** Previously: only 23/981 airlines had a category assigned (see Part 1 note). Jon did a full manual categorization pass over all 987 airlines (weekend of 2026-06-20/21), sent back as `Airline Categories - Completed.xlsx`. Applied to the live DB via new idempotent script `scripts/apply_airline_categories_v2.py` (single bulk `execute_values` statement — the original per-row `UPDATE` loop reliably timed out against the pooled Supabase connection at the ~45s bash sandbox cap; collapsing 987 round trips into one bulk statement fixed it). `airlines.airline_category` is now 987/987 populated: RFSC 293, OTH 193, LEI 187, REG 123, LCC 112, FSC 48, ULCC 19, GL 12. `05_Airline_Defaults` col B on the rebuilt workbook is now sourced live from this DB column (green fill, DB-sourced/editable) instead of carried forward from the prior workbook file — see Part 6 status note. Verified row-for-row against Jon's source file: zero mismatches across all 987 airlines.
5. **`07_Retrofit_Baseline` edit-or-not:** confirmed read-only/DB-export, explained in Part 6.
6. **Retirement age defaults — RESOLVED (v3.4, 2026-06-22).** v3.3 shipped the 4 `08_Retirement_Defaults` values (25/25/20/30) as extrapolated DRAFT placeholders. Jon supplied researched values directly in his edited copy of the workbook; applied to the live DB unchanged: Widebody 20, Narrowbody 25, Regional 30, Turboprop 30. **Open sub-item:** the Regional row's `notes` text wasn't updated alongside the value and still argues for an *earlier* retirement age than narrowbody — now contradicted by Regional (30) being the highest value of the four. Flagged in the v3.4 workbook (`00_Instructions`, `04_Import_Guide`) for Jon to reconcile; not auto-corrected since the right fix (update the number vs. update the note) is Jon's call.
7. **IFE auto-draft coverage gap — RESOLVED for active subfleets (manual edit sync, 2026-06-23).** v3.4 (2026-06-22) initially replaced the old single pair with 4 cabin-class pairs, auto-drafted from AeroLOPA at First 78/2,753, Business 932/2,753, Premium Economy 264/2,753, Economy 1,477/2,753 covered, rest NULL. Jon then filled in every remaining gap directly in the workbook for all 2,753 active subfleets; synced to the DB via `scripts/sync_v34_manual_edits.py` — see Part 2 Group A for live TRUE/FALSE counts. Only 1 active subfleet still has a NULL IFE cell (subfleet 12019, likely an unintentional miss — see Part 2 Group A). The 878 closed/superseded Manual subfleet rows remain untouched/NULL (not in the workbook, history only). **New open item from this sync:** 43 active subfleets have an internally inconsistent Has IFE?/IFE Type pair for one cabin class (NO paired with a real type, or YES paired with 'No-IFE') — pushed to the DB exactly as entered rather than guessed at; full list in Part 2 Group A. Worth a quick pass from Jon to reconcile, since which side is "right" (the YES/NO flag or the type) isn't inferable from the data alone.
8. **Connectivity has zero source data anywhere (v3.3):** by design, not a gap to close with more matching logic — there is no WiFi/connectivity dataset in the pipeline today. `has_connectivity`/`connectivity_notes` will stay 100% manual entry unless/until a new data source is identified. Jon's workbook currently shows NO/blank for every row (2026-06-23), which already matches the DB default — no change needed unless/until real connectivity data shows up.
9. **Turboprop pricing gap — RESOLVED (v3.3.1, 2026-06-22).** Previously: Turboprop subfleets (73 active) had zero rows in `assumptions` — the `assumptions_aircraft_size_class_check` CHECK constraint only permitted `Regional`/`Narrowbody`/`Widebody`, so Turboprop spend could never calculate, even though Jon had already built out a full Turboprop pricing matrix in his own standalone copy of `03_Pricing_Reference`. Jon flagged the discrepancy by sending that copy back for comparison. Fix, via new idempotent script `scripts/add_turboprop_pricing.py`: (1) widened the CHECK constraint to permit `'Turboprop'`; (2) inserted Jon's 72 rows (24 product codes × New/Repair/Replace, except `eng_cert` which is per_program × Large/Medium/Small) as-is, with one correction — three Monuments rows (New/Repair/Replace) had `product_code` typo'd as `tue`/`wed`/`thu` in Jon's file (an Excel autofill artifact), corrected to `mon` to match the product_catalog FK and the existing non-Turboprop Monuments rows. `assumptions` now has 486 active rows total (was 414). Verified the rebuilt `03_Pricing_Reference` row-for-row against Jon's file: all 72 Turboprop rows present, zero value mismatches, zero missing/extra rows.

10. **`forecast_spend` naming / Insperial spend sanity check (2026-06-30).** `forecast_spend` confirmed populated (20,926 rows), `v_spend_by_region_year` confirmed returning real numbers. **Open item before Insperial delivery (due 2026-08-31):** run a global total across all regions and years and sanity-check the aggregate against known cabin interiors market sizing (~$3–5B/year global). Africa 2026 alone shows ~$472M — not impossible but warrants verification that `assumptions` cost rates are calibrated, not still at placeholder values. Run: `SELECT year, SUM(total_spend) FROM v_spend_by_region_year WHERE forecast_version = '2026_Forecast' GROUP BY year ORDER BY year;` and compare to known market benchmarks.

11. **Route competition database — planned, not yet designed or built.** Key Hoku thesis: if airline A announces a retrofit of a fleet type where airline B flies the same routes with an older cabin product, airline B faces accelerated retrofit pressure, creating a hot lead. Requires: (a) a point-to-point route table (airline × origin × destination × aircraft_type); (b) a competitive overlap calculation joining routes → subfleets → cabin_events → reaction candidates; (c) a data source decision (OAG, Cirium, FlightAware, manual?). This is the highest-priority unbuilt module after Insperial delivery. Schema design is the first step. See also Part 11.

**Lesson learned (carried forward):** verify zip integrity (`python3 -c "import zipfile; zipfile.ZipFile(path)"`) immediately after every `wb.save()` / file copy, and run the LibreOffice-headless recalculation + duplicate-row check, before reporting any xlsx deliverable as complete.

---

## Part 8: AeroLOPA Integration (DONE — all 6 steps complete and verified, 2026-06-19)

### Why

Jon's mandate (2026-06-18): AeroLOPA is the baseline source of truth for the airlines it tracks. It covers every distinct LOPA (layout of passenger accommodations) configuration an airline flies — not one generic per-aircraft-type layout — including seat counts and whether business class has a privacy door, a trend Jon is watching closely alongside premium economy expansion. **Rule:** AeroLOPA data supersedes whatever we already have for the airlines it covers; for airlines it doesn't cover, keep using existing data. Refresh cadence: quarterly.

### Source file

`aerolopa seat config master.xlsx`, 5 tabs:
- **Airline Config Summary** — 1515 rows, one per distinct LOPA configuration. Carries per-config seat counts by class, and two privacy-door-status columns (Business, First) — **now known to be stale/unused, see Data Quality below.**
- **Cabin Details** — 2755 rows, one per cabin-segment within a config (finer grain). Has its own single Privacy Door Status column (col Z). **This is the authoritative privacy-door source going forward.** Also has a Cabin Deck column — **confirmed 2026-06-19 to be 100% empty across all 2,755 rows** (direct `openpyxl` read of the raw file, not an extraction bug). This killed the original Step 4 plan to rebuild the Upper/Lower deck split from cabin-level deck tags; see Part 8 Step 4.
- **Airline Summary** — 210 rows, per-airline rollup (includes IATA code for all 209 airlines).
- **Aircraft Type Summary** — 1490 rows, per-airline × aircraft-type rollup.
- **QA Summary** — totals/sanity-check tab.

### Grain decision — CONFIRMED

`subfleets` splits to **one row per distinct LOPA configuration** for AeroLOPA-covered airlines (not blended/weighted-averaged into one row per aircraft type). Jon's explicit choice over the alternative (keep one row per aircraft type, blend configs). 325 airline×aircraft-type combinations have 2–3 distinct LOPA configs each (e.g. IndiGo A321neo ×3, Sichuan Airlines across 5 aircraft types ×2 each) — these are exactly the rows that will multiply.

### Data quality — RESOLVED (2026-06-18)

Originally flagged: Airline Config Summary's Business/First Privacy Door Status columns had a messy 4-state distribution (`No`/`Not Present`/`Review`/`Confirmed`) — 79 Business-class and 34 First-class rows sitting in an ambiguous "Review" state.

Jon manually cleaned **Cabin Details column Z** (the separate, more granular sheet) down to a clean binary: **2654 "No" / 101 "Confirmed", zero Review/Not Present/blank remaining.** Verified this maps cleanly to LOPA configs with no rollup ambiguity: every config has exactly one Business-cabin (`Cabin Type = 'J'`) row and at most one First-cabin (`Cabin Type = 'F'`) row in Cabin Details — 932 J configs, 78 F configs, zero with more than one row, zero with mixed status. So Business/First privacy-door status can be read directly off Cabin Details via a 1:1 join on (Airline Name, Aircraft Code/LOPA Config, Cabin Type) — no aggregation logic needed.

**Important:** Airline Config Summary's own two Privacy Door Status columns are *not* formula-linked to Cabin Details and still show the old messy values — confirmed they didn't change when Jon edited Cabin Details. **Ignore those two columns going forward.** Cabin Details is the sole authoritative source for privacy-door status.

### Matching work — DONE (Steps 1–2, 2026-06-19)

- **Airlines:** all 209 AeroLOPA airlines resolved (130 exact `airlines.name` matches + 79 fuzzy/alias resolutions; 6 had no existing match and got new `airlines` rows created, growing the table 981→987). IATA backfilled from AeroLOPA: `airlines.iata_code` coverage went from 23/981 to 208/987.
- **Aircraft types:** `aircraft_types` grew 82→95 (+13 rows for AeroLOPA-only families: ATR42/72, DHC Dash 8/Q400, Britten-Norman Islander, Saab 340, Fokker 100, Embraer 135/140, CRJ-550, Boeing 737-400 Combi). Only 1 of 1,512 AeroLOPA configs remains unmatched to an `aircraft_type`.
- The crosswalk itself isn't a standalone mapping table — it's embedded directly as resolved `db_airline_id`/`db_aircraft_type_id` FK columns on the staging table rows (see New DB objects below), reused on every future quarterly refresh.

### New DB objects — BUILT (Step 3, 2026-06-19)

- **`aerolopa_snapshot_configs`** (1,512 rows, one per LOPA config, `snapshot_quarter='2026-Q2'`) — raw quarterly snapshot fields (seat counts by class, `aircraft_in_configuration`, haul type, etc.) plus the resolved `db_airline_id`/`db_aircraft_type_id` crosswalk columns and a `lopa_config_code`.
- **`aerolopa_snapshot_cabins`** (2,752 rows, one per cabin segment within a config) — `privacy_door_status` (cleaned binary), `cabin_deck` (100% empty, see Source file above), `cabin_type_code` (J/F/Y/W/etc.), `cabin_group`, `cabin_seats`.
- New `subfleets` columns: `seats_first_privacy_door` (Step 4) — privacy-door seat *counts*, not a separate status column. The original plan above (two structured Business/First privacy-door status columns) was superseded by this simpler design once Step 4 was underway: counts fold directly into the existing seat-count fields instead of a parallel status field.

### Template tie-in (no extra logic needed)

`01_Fleet_Baseline` column R "Seat Data Source" (Assumption/AeroLOPA/Actual, Part 6) is the natural hook. Once `subfleets.source = 'AeroLOPA'` is populated for matched/split rows, the next template rebuild flips column R to "AeroLOPA" for exactly those rows and leaves everything else "Assumption" — satisfying the supersede-if-covered / fallback-if-not rule by construction. (Requires updating `build_template.py` to read `subfleets.source` instead of hardcoding "Assumption" — small change, captured in Step 6 below.)

Also proposed, not yet built: an `08_AeroLOPA_Source` read-only reference sheet mirroring `07_Retrofit_Baseline`'s role — a transparent export of what AeroLOPA reported, sitting alongside the editable `01_Fleet_Baseline`.

### Execution plan — confirmed by Jon, executing step by step

Each step gets verified before moving to the next (per Jon's instruction). Status as of 2026-06-19:

1. **Airline name crosswalk + IATA backfill** — **DONE.** All 209 AeroLOPA airlines resolved (130 exact + 79 fuzzy/alias + 6 new rows created); `airlines.iata_code` backfilled 23/981 → 208/987.
2. **Aircraft-type crosswalk** — **DONE.** `aircraft_types` grew 82 → 95 (+13 AeroLOPA-only families); 1 of 1,512 configs remains unmatched.
3. **Staging table + load snapshot** — **DONE.** `aerolopa_snapshot_configs` (1,512 rows) + `aerolopa_snapshot_cabins` (2,752 rows), `snapshot_quarter = '2026-Q2'`.
4. **Split `subfleets` by LOPA config** — **DONE.** 1,511 new AeroLOPA rows inserted (`source='AeroLOPA'`, `valid_from=2026-06-19`), 878 old Manual rows closed (renamed + `valid_to` set, never deleted) — first real use of the `valid_from`/`valid_to` versioning mechanism. Zero name collisions, zero seat-component-sum mismatches. Three deviations from the original plan above, discovered mid-execution and resolved with Jon's sign-off:
   - **Deck split abandoned for new rows.** Cabin Deck data turned out to be 100% empty (see Source file note above), invalidating the planned cabin-tag-based deck rebuild. 16 of 23 legacy deck-split pairs were AeroLOPA-covered (Emirates A380, Lufthansa, Qatar, Singapore, ANA, Korean Air, British Airways, Qantas, Asiana, Air China, Etihad) — collapsed to one row per LOPA config, `deck=NULL`. The other 7 pairs (not AeroLOPA-covered) keep their original deck split.
   - **No generic Business/First subtotal column exists on `subfleets`** — only the granular recliner/lieflat/domestic-first split. Resolved: `seats_j_lieflat` = full business count, `seats_first_lieflat` or `seats_domestic_first` = full first count (routed by haul type: short/medium-haul → domestic-first, long-haul/unknown → lieflat); recliner fields left at 0 for all new rows. New column `seats_first_privacy_door` added to carry First-class suite counts (mirrors `seats_j_privacy_door`), since no column existed for this before.
   - **`subfleet_name`** = `{model}` when a pair has one resulting config, `{model} ({lopa_config_code})` when it has multiple. `notes` carries a regex-parseable LOPA config code for Step 5 to recover.
5. **Propagate to `forecast_master` and `retrofit_baseline`** — **DONE.** 863 (airline, aircraft_type) pairs had prior forecast/retrofit history to split: weighted apportionment by AeroLOPA's `aircraft_in_configuration` where available (665 pairs) or equal split where not (198 pairs), applied to `fleet_count`/`deliveries` per year; fleet-condition fields (avg_age, retrofit intervals, etc.) copied unchanged, not split. 170 additional (airline, aircraft_type) pairs had **zero** prior history (gaps at American, Delta, United, Qantas, JAL, Air Canada, Iberia, KLM, ITA Airways, SAS among others) — Jon's call: create forecasts now rather than leave them seat-config-only. 100/170 got a real fleet_count from AeroLOPA's aircraft count (`data_confidence='Medium'`); 70/170 got `fleet_count=0` flagged `data_confidence='Low'` for manual review. Old (closed) subfleets' forecast/retrofit rows are left untouched as history. **Totals: `forecast_master` 21,156→36,266 rows (+15,110); `retrofit_baseline` 2,120→3,631 rows (+1,511, exact 1:1 with `subfleets`).** Verified: every active subfleet has exactly one `retrofit_baseline` row and exactly 10 `forecast_master` rows (2026–2035), no orphaned rows, and a full sum-back check (863 pairs × 10 years) confirms new split rows reconstruct the pre-split fleet_count — one immaterial 0.002-unit rounding artifact found (Emirates A380, 2028, 18-way config split) and verified benign.
6. **Rebuild `01_Fleet_Baseline` + verify** — **DONE, 2026-06-19.** `build_template.py` updated (subfleets query now selects `valid_to IS NULL` active rows only and includes `s.source`; column R reads `"AeroLOPA" if source == "AeroLOPA" else "Assumption"` instead of hardcoding; the three /tmp sidecar JSON files from the old script no longer existed, so `curated_airlines`/`airline_defaults_filled`/`fleet_notes` are now re-derived directly from the prior workbook on disk before it's overwritten; hardcoded counts updated throughout — `all_airlines` 981→987, `retrofit_baseline`/subfleets asserts 2120→2,753). Row count grew from 2,120 to **2,753** active subfleets (1,242 Manual + 1,511 AeroLOPA), exactly as predicted. Surfaced and fixed one undocumented gap along the way (missing `retrofit_interval_defaults` Turboprop row — see the Part 6 write-up above). Verification (same protocol as v3.0): LibreOffice headless recalculation → **zero formula errors**; **zero duplicate `subfleet_id` rows**; row count reconciles to 2,753; column R spot-checked against live DB source for all 2,753 rows → **zero mismatches**. Saved as v3.1, then carried forward unchanged into the v3.2 grid redesign (Part 6) same day. `scripts/build_template.py` reflects the final, working state.

*Architecture through Part 9 current as of 2026-06-23. Parts 10–11 and Part 7 items 10–11 added 2026-06-30 (v1.11) — see the version note at the end of Part 11 for full change history.*

---

## Part 9: Project Folder Structure (reorganized 2026-06-19)

The folder was originally flat — every script, data file, and reference spreadsheet sitting loose at the root alongside the workbook. Reorganized into four subfolders, with only the actively-used root-level files left in place:

**Root** (`Forecast Files/`):
- `forecast_baseline_template.xlsx` — superseded, v3.2, kept as-is (appears locked, likely open in Excel)
- `forecast_baseline_template_v3.3.xlsx` — superseded, v3.3, kept as historical record
- `forecast_baseline_template_v3.4.xlsx` — the live workbook (v3.4, current)
- `ARCHITECTURE.md` — this file
- `.env` — DB connection string (`DATABASE_URL`); every script either does a bare `load_dotenv()` (searches upward from the script's own folder, so it finds this regardless of which subfolder the script lives in) or an explicit `ROOT`-relative path — confirmed both patterns resolve correctly from `scripts/`.

**`scripts/`** — every `.py` file: `build_template.py`, `build_template_v33.py`, `build_template_v331.py`, `build_template_v332.py`, and `build_template_v332_fix.py` (all five stale/superseded in this environment — see file-naming note at the top of this doc), `build_template_v34.py` (**current, use this one** — adds the IFE-by-cabin-class columns (AK–AT) and the updated retirement age defaults on top of `build_template_v332_fix.py`'s content, rewritten fresh to a new filename per the established stale-cache workaround), `add_turboprop_pricing.py` (idempotent one-off DB fix, 2026-06-22 — widens the `assumptions_aircraft_size_class_check` CHECK constraint and inserts the 72 Turboprop pricing rows; see Part 7 item 9), `apply_airline_categories.py` (superseded, per-row `UPDATE` loop, reliably times out — kept as historical record, do not run) and `apply_airline_categories_v2.py` (**current** — single bulk `execute_values` statement, idempotent; applies Jon's 987-airline categorization to `airlines.airline_category`; see Part 7 item 4), `add_ife_by_cabin_class_columns.py` (idempotent one-off schema migration, 2026-06-22 — adds the 8 `has_ife_<class>`/`ife_type_<class>` columns to `subfleets`; see Part 2 Group A), `populate_ife_by_cabin_class.py` (idempotent bulk-update DB script, 2026-06-22 — auto-drafts the 8 new columns from AeroLOPA's per-cabin `ife_description`; see Part 2 Group A), `sync_v34_manual_edits.py` (idempotent full-overwrite DB script, 2026-06-23 — reads Jon's hand-edited `forecast_baseline_template_v3.4.xlsx` directly and pushes his IFE fill-in + the J Lie-Flat/Privacy Door correction into `subfleets`; safe to re-run any time the workbook changes, since `build_template_v34.py` queries `s.has_ife_*`/`s.seats_j_lieflat` straight from the DB, so this script is the one place those edits need to land before a rebuild; see Part 2 Group A and Part 7 item 7), `create_schema.py`, `seed_reference_tables.py`, `import_forecast.py`, `import_2026_forecast.py`, `apply_airline_fixes.py`, `find_airline_name_conflicts.py`. All path references inside these scripts were updated to resolve correctly from this subfolder (verified via `ast.parse` and live path-resolution checks against `source_data/`, `reference/`, and `.env`).

**`source_data/`** — the large raw forecast-vintage source files the import scripts read from: `26-35 forecast_data.xlsx`, `26-35 10 year interiors forecast.xlsb`, `24-34 Interiors Forecast May 25 (version 1).xlsx`, `2022-2032 Air Transport Seat and Interiors MRO-Refurb Forecast Output 23Oct2023 (1).xlsb`.

**`reference/`** — working/crosswalk spreadsheets not directly read by any script's hardcoded path except where noted: `Pricing Matrix.xlsx`, `aerolopa seat config master.xlsx`, `aerolopa_aircraft_type_crosswalk.csv`, `aerolopa_airline_crosswalk.csv`, `aircraft_size_class_review.xlsx`, `airline_name_conflicts.csv` (output of `find_airline_name_conflicts.py`), `product_catalog_draft.xlsx`, `product_catalog_v2.xlsx`, `airline_categories_2026-06-22.xlsx` (stable checked-in copy of Jon's "Airline Categories - Completed.xlsx" — read directly by `apply_airline_categories_v2.py`'s hardcoded path; see Part 7 item 4).

**`archive/`** — `forecasts.db-journal`, an orphaned SQLite journal file with no matching `.db` file anywhere in the folder and no script reference to it. Moved here rather than deleted, since permanent deletion isn't something this process does automatically — safe for Jon to delete by hand if confirmed unneeded.

---

## Part 10: Hōkū Intelligence — Commercial Context

> **Why this section exists:** the DB's design decisions only make sense in context of what Hōkū is trying to produce commercially. Read this before asking why any table or view exists.

### What Hōkū Is

Hōkū is a subscription intelligence platform built exclusively for companies operating in the commercial aircraft cabin interiors market — the BD leaders, C-suite executives, and PE firms who need continuous market signal but cannot justify enterprise platforms (AWIN, Cirium) or bespoke research retainers. Lele Aviation Consulting and Hōkū are structurally separate businesses; the consulting firm's credibility is what makes the intelligence product credible.

**Primary buyer personas:**
- BD and strategy leaders at $5M–$300M cabin interiors suppliers
- C-suite at supplier companies evaluating platform/partnership strategy
- PE firms with cabin interiors portfolio exposure needing ongoing market context

### Three Tiers

| Tier | Price | Cap | Core Deliverable |
|------|-------|-----|-----------------|
| Standard | $2,400/yr | Unlimited | Weekly 4–7 page intelligence brief (email + PDF) |
| Founder | $12,000/yr | 10 seats | Standard + monthly 8–12 page deep-dive + analyst access cohort |
| Strategy | $36,000/yr | 6 seats | Founder + quarterly 90-min 1:1 strategy session + bespoke BD pipeline review |

Year 1 pricing is introductory (launched Aircraft Interiors Expo Hamburg, April 2026), locked for 3 years for Founder/Strategy enrollees. Full pricing from 2027.

### The Weekly Brief — Five Sections

1. **Executive Summary** — 3–5 bullet synthesis of the week's highest-signal events
2. **Market Themes** — 2–3 emerging structural themes with cross-signal analysis
3. **Airline Capital Allocation** — program-stage model (see below); the core Hōkū differentiator
4. **Key Airline Signals** — deep read on specific airline decisions with supplier implications
5. **Supplier Competitive Landscape + OEM/Lessor Signals + Signals to Watch**

### The Capital Allocation Model (Core Differentiator)

Each airline program is tracked through four stages, updated weekly:

| Stage | Meaning |
|-------|---------|
| **Monitoring** | Signal activity present; no confirmed program indicators |
| **Compression** | Multiple signals converging; program announcement likely within 12–24 months |
| **Actionable** | Program confirmed or near-confirmed; suppliers should be in BD conversations now |
| **Urgent** | Active tender or final selection window; BD must be engaged immediately |

Stage assignments live in `airline_allocation_scores` (weekly, append-only). Stage changes are logged in `model_adjustments` with the Notion signal URL that drove the change. **Current state (2026-06-30): scores are being updated manually in Notion; the automated DB sync script has not yet been built.** `hoku_signals` table exists but is empty — the Notion → PostgreSQL sync is an open item.

### Phase Roadmap

**Phase 1 — Foundation (2026):** Weekly brief live, Founder cohort enrolled, content engine (LinkedIn Tue/Thu). Insperial SOW as first bespoke project (due 2026-08-31). DB provides quantitative backbone for brief and Insperial.

**Phase 2 — Expansion (2027):** Full pricing for new subscribers. Hōkū Supplier Database (structured, searchable, gated to Founder+Strategy). Program Tracker (running status of major cabin programs). Annual Report (free distribution, inbound generation).

**Phase 3 — Platform (2028+):** Web dashboard combining supplier DB, program tracker, brief archive, signal monitoring. API access tier. Hōkū Enterprise ($40K–$75K/yr company-wide license). Potential strategic partnership with larger aviation media/data organization.

### How the DB Feeds Each Brief Section

| Brief Section | DB Source |
|--------------|-----------|
| Airline Capital Allocation | `airline_allocation_scores` + `model_adjustments` |
| Opportunity values ("$Xm probability-weighted") | `reaction_events.forecast_opportunity_value_usd` |
| Signals to Watch | `watchlist` |
| Fleet/program context | `subfleets` + `forecast_master` |
| Supplier competitive landscape | `supplier_program_wins` + `sub_supplier_relationships` |
| Insperial / bespoke spend tables | `forecast_spend` + `v_spend_by_region_year` |

---

## Part 11: Route Competition Database (Planned — Not Yet Built)

### The Thesis

If Airline A announces a retrofit of a specific fleet type (e.g., B737 domestic), and Airline B flies the same city-pair routes with an older cabin product on the same aircraft type, Airline B faces accelerated retrofit pressure from competitive exposure. This competitive overlap signal converts a generic "peer reaction" probability into a specific, route-validated hot lead for suppliers to pursue.

This is one of Hōkū's most differentiating quantitative signals and is **completely unbuilt** as of 2026-06-30. No table, no schema, no data source.

### What Needs to Be Built

**Table: `competitive_routes`** (proposed, schema not yet designed)
- Grain: airline × origin × destination × aircraft_type (at minimum)
- Optional: cabin_class_detail, frequency, year (for temporal relevance)
- Join path: `competitive_routes.airline_id` + `aircraft_type_id` → `subfleets` → `cabin_events` (retrofit announcements) → competitor overlap → `reaction_events` modifier

**Competitive overlap calculation**
- For a given retrofit announcement (cabin_event), find all other airlines that fly the same city-pair routes with the same or similar aircraft type
- Weight by route overlap density (number of overlapping routes), recency of competitor's last retrofit, and cabin age
- Output: a `route_competitive_pressure_score` that feeds into `reaction_events.final_probability` as an additional modifier alongside the existing cluster/age/pattern modifiers

**Data source decision (not yet made)**
- OAG (licensed, comprehensive, expensive)
- Cirium schedules data (licensed)
- FlightAware / FlightRadar24 (less structured)
- Manual compilation for top-50 route markets (fastest path to MVP)
- Open-source GTFS or similar (limited airline coverage)

### Priority

Highest-priority unbuilt module after Insperial delivery (2026-08-31). Schema design and data source decision are the first two steps. The competitive cluster framework already in `competitive_clusters` / `airline_cluster_membership` is a related but coarser instrument — route competition is finer-grained and more directly actionable for BD.

*Architecture current as of 2026-06-30 (v1.11: Hōkū commercial context added (Part 10), route competition database scoped (Part 11), `forecast_spend` naming corrected and confirmed populated (20,926 rows), `v_spend_by_region_year` confirmed working, Part 7 items 10–11 added). Prior history: v1.10 = 2026-06-23 (v3.3 retirement modeling + IFE/connectivity, v3.3.1 Turboprop pricing, v3.3.2 bulk airline categorization, v3.4 IFE per cabin class + manual edit sync + J Lie-Flat/Privacy Door correction). Part 8 (AeroLOPA integration, all 6 steps) complete and verified. See Part 7 for open items and Part 9 for folder layout.*
