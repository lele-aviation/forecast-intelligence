#!/usr/bin/env python3
"""
Rebuild forecast_baseline_template.xlsx (v3.3) for Lele Aviation.
Incorporates: 8-value airline category taxonomy, Premium/Economy cabin-tier
retrofit split (+ Whole Aircraft track for non-seat spend), Seat Data Source
column (now wired to subfleets.source), full 987-airline / 2753-active-subfleet
universe (AeroLOPA integration), wide retrofit-default tables, retirement
modeling (08_Retirement_Defaults + cols AH-AJ), IFE/connectivity tracking
(cols AK-AN), and Turboprop pricing coverage (72 rows added v3.3.1).
DB data is read-only in this script -- no writes to Postgres.
"""
import json
import psycopg2
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.utils import get_column_letter

DB_URL = "postgresql://postgres.bcgbsaviwtnbqpypmsfk:Mahalo2026FY!@aws-1-us-east-1.pooler.supabase.com:5432/postgres"
OUT_PATH = "/sessions/trusting-amazing-albattani/mnt/Forecast Files/forecast_baseline_template_v3.3.xlsx"
SOURCE_PATH = "/sessions/trusting-amazing-albattani/mnt/Forecast Files/forecast_baseline_template.xlsx"

# ---------------------------------------------------------------------------
# Style primitives (colors/fonts copied exactly from the intact v2.1 file)
# ---------------------------------------------------------------------------
THIN_GREY = Side(style="thin", color="FFBFBFBF")
BORDER = Border(top=THIN_GREY, bottom=THIN_GREY, left=THIN_GREY, right=THIN_GREY)

def font(color, bold=False, size=8, name="Arial"):
    return Font(name=name, size=size, bold=bold, color=color)

def fill(rgb):
    return PatternFill(fill_type="solid", fgColor=rgb)

F_YELLOW = ("FFFFFF00", "FF7B3F00")   # input required
F_GREEN  = ("FFE2EFDA", "FF1F3864")   # DB-sourced, editable
F_GREY   = ("FFF2F2F2", "FF595959")   # read-only
F_BLUE   = ("FFDDEBF7", "FF000000")   # formula

def style_cell(cell, kind, bold=False, size=8, name="Arial", align="center",
               wrap=False, number_format="General"):
    fg, fc = kind
    cell.fill = fill(fg)
    cell.font = font(fc, bold=bold, size=size, name=name)
    cell.alignment = Alignment(horizontal=align, vertical="center", wrap_text=wrap)
    cell.number_format = number_format
    cell.border = BORDER

TITLE_NAVY = ("FF1F3864", "FFFFFFFF")   # title bar fill/font (navy/white)
HEADER_BLUE = ("FF2F5597", "FFFFFFFF")  # column header bar (mid-blue/white)
GROUP_GREEN_HDR = ("FFE2EFDA", "FF1F3864")  # group header row (same as green data)

def style_title(cell, size=11, bold=True):
    cell.fill = fill(TITLE_NAVY[0])
    cell.font = font(TITLE_NAVY[1], bold=bold, size=size)
    cell.alignment = Alignment(horizontal="left", vertical="center")
    cell.border = BORDER

def style_header_blue(cell, size=9, align="center", wrap=True):
    cell.fill = fill(HEADER_BLUE[0])
    cell.font = font(HEADER_BLUE[1], bold=True, size=size)
    cell.alignment = Alignment(horizontal=align, vertical="center", wrap_text=wrap)
    cell.border = BORDER

def style_group_header(cell, size=8, align="center"):
    cell.fill = fill(GROUP_GREEN_HDR[0])
    cell.font = font(GROUP_GREEN_HDR[1], bold=True, size=size)
    cell.alignment = Alignment(horizontal=align, vertical="center", wrap_text=True)
    cell.border = BORDER

# ---------------------------------------------------------------------------
# Pull data from Postgres (read-only)
# ---------------------------------------------------------------------------
conn = psycopg2.connect(DB_URL)
cur = conn.cursor()

cur.execute("""
    select s.id, a.name, t.model, t.category, s.subfleet_name, s.deck, s.source,
           s.seats_first_lieflat, s.seats_first_recliner, s.seats_domestic_first,
           s.seats_j_lieflat, s.seats_j_recliner, s.seats_j_privacy_door,
           s.seats_premium_economy, s.seats_economy_plus, s.seats_economy,
           s.retirement_age_override, s.has_ife, s.ife_type, s.has_connectivity, s.connectivity_notes
    from subfleets s
    join airlines a on a.id = s.airline_id
    join aircraft_types t on t.id = s.aircraft_type_id
    where s.valid_to is null
    order by a.name, t.model, case s.deck when 'Upper' then 0 when 'Lower' then 1 else 2 end
""")
subfleets = cur.fetchall()
assert len(subfleets) == 2753, f"expected 2753 active subfleets, got {len(subfleets)}"

cur.execute("""
    select aircraft_size_class, default_retirement_age, notes
    from retirement_age_defaults order by id
""")
retirement_defaults = cur.fetchall()
assert len(retirement_defaults) == 4, f"expected 4 retirement age defaults (Size Class grid), got {len(retirement_defaults)}"

cur.execute("select subfleet_id, fleet_count, avg_age from forecast_master where forecast_version_id=3 and year=2026")
fm = {row[0]: (row[1], row[2]) for row in cur.fetchall()}

cur.execute("""
    select rb.subfleet_id, rb.last_confirmed_retrofit_year, rb.confidence, rb.status,
           rb.match_basis, rb.notes, ce.event_id
    from retrofit_baseline rb
    join subfleets s on s.id = rb.subfleet_id and s.valid_to is null
    left join cabin_events ce on ce.id = rb.source_event_id
""")
rb = {row[0]: row[1:] for row in cur.fetchall()}
assert len(rb) == 2753, f"expected 2753 retrofit_baseline rows (1:1 with active subfleets), got {len(rb)}"

cur.execute("""
    select aircraft_size_class, airline_category, default_retrofit_years, default_repair_years, notes
    from retrofit_interval_defaults order by id
""")
defaults14 = cur.fetchall()
assert len(defaults14) == 32, f"expected 32 interval defaults (full 4 Size Class x 8 Category grid, Step 7 restructure), got {len(defaults14)}"

cur.execute("""
    select pc.product_group, a.product_code, pc.display_name, pc.cost_basis, a.service_type,
           a.aircraft_size_class, a.mod_size, a.base_cost, a.escalation_rate
    from assumptions a
    join product_catalog pc on pc.code = a.product_code
    where a.is_active = true
    order by pc.product_group, a.product_code, a.aircraft_size_class,
             case a.mod_size when 'Large' then 0 when 'Medium' then 1 when 'Small' then 2 else 3 end
""")
pricing = cur.fetchall()
assert len(pricing) == 486, f"expected 486 pricing rows (414 + 72 Turboprop, added v3.3.1), got {len(pricing)}"

cur.execute("select name from airlines order by name")
all_airlines = [row[0] for row in cur.fetchall()]
assert len(all_airlines) == 987, f"expected 987 airlines, got {len(all_airlines)}"

cur.close()
conn.close()

# The three /tmp sidecar JSON files from the original v3.0 build no longer
# exist (one-time dumps, didn't survive). Re-derive the same data straight out
# of the current already-built workbook before it gets overwritten below.
_existing_wb = openpyxl.load_workbook(SOURCE_PATH, data_only=True)

_ws_fb = _existing_wb["01_Fleet_Baseline"]
curated_airlines = set()
fleet_notes = {}
for _r in range(3, _ws_fb.max_row + 1):
    _airline = _ws_fb.cell(row=_r, column=1).value   # A: Airline
    if _airline is None:
        continue
    _subfleet_name = _ws_fb.cell(row=_r, column=4).value  # D: Subfleet Name
    _include = _ws_fb.cell(row=_r, column=20).value        # T: Include in Forecast?
    _note = _ws_fb.cell(row=_r, column=33).value            # AG: Notes
    if _include == "YES":
        curated_airlines.add(_airline)
    if _note:
        fleet_notes[f"{_airline}||{_subfleet_name}"] = _note

_ws_ad = _existing_wb["05_Airline_Defaults"]
airline_defaults_filled = {}
for _r in range(3, _ws_ad.max_row + 1):
    _airline = _ws_ad.cell(row=_r, column=1).value  # A: Airline
    if _airline is None:
        continue
    _category = _ws_ad.cell(row=_r, column=2).value  # B: Category
    _notes = _ws_ad.cell(row=_r, column=6).value       # F: Cadence Notes
    if _category or _notes:
        airline_defaults_filled[_airline] = {"category": _category, "notes": _notes}

_existing_wb.close()
del _existing_wb, _ws_fb, _ws_ad

print(f"Loaded: {len(subfleets)} subfleets, {len(rb)} retrofit_baseline, "
      f"{len(defaults14)} interval defaults, {len(retirement_defaults)} retirement age defaults, "
      f"{len(pricing)} pricing rows, "
      f"{len(curated_airlines)} curated airlines, {len(airline_defaults_filled)} "
      f"airline-default carryovers, {len(fleet_notes)} fleet notes")

# ---------------------------------------------------------------------------
# Workbook
# ---------------------------------------------------------------------------
wb = openpyxl.Workbook()
wb.remove(wb.active)

# ---------------------------------------------------------------------------
# 00_Instructions
# ---------------------------------------------------------------------------
ws = wb.create_sheet("00_Instructions")
ws.column_dimensions["A"].width = 3
ws.column_dimensions["B"].width = 30
ws.column_dimensions["C"].width = 64
ws.column_dimensions["D"].width = 22

ws["B1"] = "LELE AVIATION INTELLIGENCE PLATFORM — Forecast Baseline Template v3.3"
style_title(ws["B1"], size=13)
for col in "CD":
    style_title(ws[f"{col}1"])

ws["B2"] = ("Base Year: 2026  |  Color code: Yellow=input required  |  Green=pre-populated from DB  |  "
            "Grey=read-only  |  Black=formula  |  Blue fill=formula cell")
for col in "BCD":
    style_cell(ws[f"{col}2"], F_GREY, align="left")

ws["B4"] = "SHEET"; ws["C4"] = "PURPOSE"
for col in "BCD":
    style_header_blue(ws[f"{col}4"])

sheet_purpose = [
    ("01_Fleet_Baseline", "One row per airline-subfleet-deck, full 987-airline / 2753-active-subfleet universe (AeroLOPA-integrated; closed/superseded Manual rows live in the DB but are excluded here). Fill yellow columns before import. Set Include in Forecast = YES for the active coverage set."),
    ("02_Program_Scope", "Which product groups are in scope for New / Replace / Repair service types; cyclical mod-size rule; whole-aircraft vs. cabin-tier retrofit tracks."),
    ("03_Pricing_Reference", "Read-only: all 486 pricing assumptions (incl. Turboprop) with escalated costs for 2028/2030/2032."),
    ("04_Import_Guide", "Step-by-step instructions + how mod size / retrofit timing / cabin-tier tracks are calculated."),
    ("05_Airline_Defaults", "One row per airline (987). Set 8-value Category + airline-specific retrofit overrides (Whole Aircraft / Premium / Economy) here once."),
    ("06_Retrofit_Defaults", "Default retrofit/repair intervals by Size Class x Airline Category, wide by track (Whole Aircraft / Premium / Economy). Edit values freely."),
    ("07_Retrofit_Baseline", "One row per active subfleet (2753), exported from the DB. Last confirmed/estimated retrofit year, sourced from cabin_events filings -- feeds 01_Fleet_Baseline's Whole Aircraft track automatically. Premium/Economy columns are placeholders pending the cabin-tier-aware DB rebuild."),
    ("08_Retirement_Defaults", "Default retirement age by Aircraft Size Class (4 rows: Widebody/Narrowbody/Regional/Turboprop). Feeds 01_Fleet_Baseline's Effective Retirement Age cascade. Edit values freely -- current numbers are DRAFT placeholders."),
]
r = 5
for name, purpose in sheet_purpose:
    ws.cell(row=r, column=2, value=name)
    ws.cell(row=r, column=3, value=purpose)
    style_cell(ws.cell(row=r, column=2), F_GREY, bold=True, align="left")
    style_cell(ws.cell(row=r, column=3), F_GREY, align="left", wrap=True)
    style_cell(ws.cell(row=r, column=4), F_GREY)
    r += 1

r += 1
ws.cell(row=r, column=2, value="WHAT CHANGED IN v3.0")
style_title(ws.cell(row=r, column=2), size=11)
for col in "CD":
    style_title(ws.cell(row=r, column=openpyxl.utils.column_index_from_string(col)))
r += 1

changelog_v3 = [
    "Airline Category is now an 8-value taxonomy: FSC, GL, LCC, ULCC, RFSC, REG, LEI, OTH (replaces the old FSC/GL/LCC/ULCC/RFSC/\"Regional FSC\" list, which had a redundant Regional FSC entry and no slot for Regional/Leisure/Other carriers). DB CHECK constraint already updated to match.",
    "Coverage expanded from the curated 354-airline / 890-subfleet subset to the FULL 981-airline / 2120-subfleet universe (every active airline and subfleet in the DB, verified zero duplicates). Use col T (Include in Forecast?) to keep the active spend model scoped to the same 354 airlines as before -- they're pre-flagged YES, the other 627 are pre-flagged NO. Flip any row to YES/NO as your coverage decisions evolve.",
    "Cabin-tier retrofit split (the big change): Retrofit Last Year / Override / Effective Interval is no longer one shared track per subfleet. It's now THREE parallel tracks: WHOLE AIRCRAFT (drives non-seat-specific spend -- carpets, panels, galleys, lavatories, IFEC, Eng & Cert -- and is the fallback for everything else), PREMIUM (First/Business/Privacy Door seats), and ECONOMY (Prem Eco/Eco Plus/Economy seats). Carriers often retrofit Business/First on a faster cycle than Economy; this lets the two move independently. Non-seat spend intentionally stays on the single Whole Aircraft track for now -- no need for that complexity yet.",
    "New Seat Data Source column (01_Fleet_Baseline col R): dropdown of Assumption / AeroLOPA / Actual, tracking where each row's seat configuration came from. Defaults to \"Assumption\" everywhere since the DB doesn't yet distinguish source at this granularity -- update as you verify counts.",
    "Economy Mid-Life Refresh (01_Fleet_Baseline cols AE/AF): an optional, non-forced flag + year for carriers who refresh Economy once mid-cycle without a full Business/First program alongside it.",
    "05_Airline_Defaults and 06_Retrofit_Defaults both went WIDE: each now carries separate override/default columns per track (Whole Aircraft / Premium / Economy) instead of one shared column, so the cascade resolves correctly per track.",
    "07_Retrofit_Baseline's Premium/Economy columns (K/L) are placeholders -- blank until the retrofit_baseline DB table and its matching script are rebuilt to be cabin-tier-aware (deferred, separate pass). The Whole Aircraft column (B) is fully populated from the live DB as before.",
    "Total Seats (col O) is now a live formula (=SUM of the seat columns) instead of a static snapshot, so it stays correct if you edit individual seat counts.",
]
for i, txt in enumerate(changelog_v3, start=1):
    ws.cell(row=r, column=2, value=f"{i}.")
    ws.cell(row=r, column=3, value=txt)
    style_cell(ws.cell(row=r, column=2), F_GREY, bold=True, align="center")
    style_cell(ws.cell(row=r, column=3), F_GREY, align="left", wrap=True)
    style_cell(ws.cell(row=r, column=4), F_GREY)
    ws.row_dimensions[r].height = 48
    r += 1

r += 1
ws.cell(row=r, column=2, value="WHAT CHANGED IN v3.2")
style_title(ws.cell(row=r, column=2), size=11)
for col in "CD":
    style_title(ws.cell(row=r, column=openpyxl.utils.column_index_from_string(col)))
r += 1

changelog_v32 = [
    "06_Retrofit_Defaults is now a full grid: all 4 Size Classes (Widebody, Narrowbody, Regional, Turboprop) "
    "x all 8 Airline Categories (FSC, GL, LCC, ULCC, RFSC, REG, LEI, OTH) = 32 rows. The old blank-category "
    "\"catch-all\" rows are gone -- OTH is now an explicit row per size class and is the row every "
    "uncategorized airline resolves to.",
    "Cascade formula simplified to match: an airline with no Category set on 05_Airline_Defaults now resolves "
    "directly to its size class's OTH row on 06_Retrofit_Defaults (previously a separate blank-category "
    "fallback tier). You do not need to set Category for every airline -- leaving it blank is a valid, "
    "intentional choice that means \"use the OTH default.\"",
    "32 new placeholder values were generated using a consistent rule (FSC/GL/RFSC = OTH-1 yr, REG = OTH, "
    "LCC/LEI = OTH+1 yr, ULCC = OTH+3 yr) so every cell has a reasonable starting number instead of being "
    "blank. These are still DRAFT placeholders -- replace with real program intelligence as you get it.",
    "\"Regional\" (size class) and \"Turboprop\" remain the stored values in the DB and dropdowns -- not "
    "renamed to \"Regional Jet\"/\"Turbopro\" -- to avoid touching the DB constraint, 21 aircraft rows, and "
    "every downstream reference for what is effectively a label preference. They mean the same thing.",
]
for i, txt in enumerate(changelog_v32, start=1):
    ws.cell(row=r, column=2, value=f"{i}.")
    ws.cell(row=r, column=3, value=txt)
    style_cell(ws.cell(row=r, column=2), F_GREY, bold=True, align="center")
    style_cell(ws.cell(row=r, column=3), F_GREY, align="left", wrap=True)
    style_cell(ws.cell(row=r, column=4), F_GREY)
    ws.row_dimensions[r].height = 48
    r += 1

r += 1
ws.cell(row=r, column=2, value="WHAT CHANGED IN v3.3")
style_title(ws.cell(row=r, column=2), size=11)
for col in "CD":
    style_title(ws.cell(row=r, column=openpyxl.utils.column_index_from_string(col)))
r += 1

changelog_v33 = [
    "Aircraft retirements are now modeled. New 08_Retirement_Defaults sheet sets a default retirement age per "
    "Size Class (Widebody/Narrowbody/Regional/Turboprop -- DRAFT placeholders, currently 25/25/20/30 years). "
    "01_Fleet_Baseline cols AH-AJ add a per-subfleet override cascade (subfleet override > Size Class default) "
    "plus a calculated Est. Retirement Start Year, the first forecast year a subfleet's average age is "
    "projected to cross its effective retirement age.",
    "Behind the scenes, this drives two new forecast_master columns -- retirements and fleet_count_adjusted -- "
    "computed for all 36,266 forecast rows (2026-2035). The rule: once a subfleet's avg_age crosses its "
    "effective retirement age, 20% of the prior year's adjusted fleet retires annually (a 5-year phase-out), "
    "netted against scheduled deliveries. The original licensed fleet_count column is left untouched -- "
    "fleet_count_adjusted is a transparent, separate overlay so the consultant's published numbers are never "
    "silently overwritten. Across all forecast subfleets, this drops the 2035 fleet total from 63,938 "
    "(licensed, no retirements) to 54,031 (adjusted) -- about 9,400 cumulative retirements by 2035.",
    "IFE and connectivity are now tracked as two independent fields per subfleet (previously not modeled at "
    "all). 01_Fleet_Baseline cols AK-AN: Has IFE? / IFE Type (AVOD-Seatback / Overhead / BYOD-Streaming / "
    "No-IFE), and Has Connectivity? / Connectivity Notes.",
    "IFE was auto-drafted from AeroLOPA's Cabin Details sheet (parsing the free-text IFE Description field) for "
    "every subfleet AeroLOPA covers -- 1,506 of 2,753 active subfleets (55%): 711 show a real IFE system "
    "(550 AVOD-Seatback, 151 BYOD-Streaming, 10 Overhead), 795 show confirmed No-IFE. The remaining 1,247 rows "
    "(1,242 Manual-source subfleets with no AeroLOPA coverage, plus 5 AeroLOPA-source edge cases -- 787-9, "
    "787-10, A350-1000, BN-2 Islander, DHC-6 Twin Otter -- not in our aircraft-type crosswalk) are left blank "
    "rather than guessed; green fill = drafted from real data, yellow fill = needs your input.",
    "Connectivity has no source data anywhere (AeroLOPA does not track WiFi/connectivity provider by aircraft), "
    "so Has Connectivity? / Connectivity Notes are blank for every row -- 100% manual entry, by design.",
    "v3.3.1: Turboprop subfleets (73 active) now have full pricing coverage. 72 rows were added to the "
    "assumptions table (24 product codes x New/Repair/Replace, except per-program Eng & Cert which is x "
    "Large/Medium/Small) -- carried over from your own pricing matrix, with one correction (a product-code "
    "typo on the three Monuments rows). 03_Pricing_Reference now totals 486 rows.",
]
for i, txt in enumerate(changelog_v33, start=1):
    ws.cell(row=r, column=2, value=f"{i}.")
    ws.cell(row=r, column=3, value=txt)
    style_cell(ws.cell(row=r, column=2), F_GREY, bold=True, align="center")
    style_cell(ws.cell(row=r, column=3), F_GREY, align="left", wrap=True)
    style_cell(ws.cell(row=r, column=4), F_GREY)
    ws.row_dimensions[r].height = 75
    r += 1

r += 1
ws.cell(row=r, column=2, value="COLUMN DEFINITIONS — 01_Fleet_Baseline")
style_title(ws.cell(row=r, column=2), size=11)
for col in "CD":
    style_title(ws.cell(row=r, column=openpyxl.utils.column_index_from_string(col)))
r += 1

col_defs = [
    ("deck", "Blank = whole aircraft. Upper/Lower for split A380/747 rows."),
    ("seat_data_source", "Assumption / AeroLOPA / Actual -- where the seat counts in cols F-N came from. Default Assumption."),
    ("j_privacy_door", "Business seats with a closing door/suite. Priced separately from lie-flat."),
    ("include_in_forecast?", "YES/NO -- include in active spend model."),
    ("retrofit_last_year (x3 tracks)", "Pre-populated from retrofit_baseline where known (green = Confirmed/Estimated), for the Whole Aircraft track only. Premium/Economy tracks are blank placeholders until the DB rebuild."),
    ("retrofit_interval_override (x3 tracks)", "Leave blank to use the airline/category default for that track. Fill in only if you know the actual program timing for this specific subfleet."),
    ("effective_retrofit_interval (x3 tracks)", "Formula -- shows the interval actually used after the override cascade, per track."),
    ("economy_midlife_refresh? / year", "Optional flag + year for a standalone Economy refresh that doesn't follow the Premium cycle."),
    ("repair_interval_yrs", "Defaults to 1 (annual), whole-aircraft level. Override only for a product repaired on a longer cycle."),
    ("retirement_age_override", "Leave blank to use the Size Class default from 08_Retirement_Defaults. Fill in only if you know this specific subfleet's retirement/conversion plan differs from the default."),
    ("effective_retirement_age", "Formula -- the retirement age actually used after the override cascade (subfleet override > Size Class default)."),
    ("est_retirement_start_year", "Formula -- first forecast year (2026-2035) this subfleet's average age is projected to cross its effective retirement age, assuming fleet age advances 1 yr/yr from the 2026 baseline. Blank if it never crosses by 2035."),
    ("has_ife? / ife_type", "Drafted from AeroLOPA where covered (green); blank where not covered (yellow -- needs your input). IFE Type values: AVOD-Seatback / Overhead / BYOD-Streaming / No-IFE."),
    ("has_connectivity? / connectivity_notes", "No source data exists for this anywhere -- 100% manual entry. Blank for every row until you fill it in."),
]
for name, desc in col_defs:
    ws.cell(row=r, column=2, value=name)
    ws.cell(row=r, column=3, value=desc)
    style_cell(ws.cell(row=r, column=2), F_GREY, bold=True, align="left")
    style_cell(ws.cell(row=r, column=3), F_GREY, align="left", wrap=True)
    style_cell(ws.cell(row=r, column=4), F_GREY)
    ws.row_dimensions[r].height = 30
    r += 1

print("00_Instructions built")

# ---------------------------------------------------------------------------
# 01_Fleet_Baseline
# ---------------------------------------------------------------------------
ws = wb.create_sheet("01_Fleet_Baseline")

COLS = [
    "Airline", "Aircraft Model", "Size Class", "Subfleet Name", "Deck",                      # A-E
    "F Lie-Flat", "F Recliner", "F Domestic", "J Lie-Flat", "J Recliner", "J Privacy Door",   # F-K
    "Prem Eco", "Eco Plus", "Eco Seats", "Total Seats", "Fleet 2026", "Avg Age 2026",         # L-Q
    "Seat Data Source",                                                                        # R
    "Subfleet ID", "Include Forecast?", "Repair Interval (yrs)",                              # S-U
    "Retrofit Last Year", "Retrofit Interval Override", "Effective Retrofit Interval",         # V-X  Whole Aircraft
    "Retrofit Last Year", "Retrofit Interval Override", "Effective Retrofit Interval",         # Y-AA Premium
    "Retrofit Last Year", "Retrofit Interval Override", "Effective Retrofit Interval",         # AB-AD Economy
    "Economy Mid-Life Refresh?", "Economy Mid-Life Refresh Year",                             # AE-AF
    "Notes",                                                                                    # AG
    "Retirement Age Override", "Effective Retirement Age", "Est. Retirement Start Year",        # AH-AJ
    "Has IFE?", "IFE Type", "Has Connectivity?", "Connectivity Notes",                          # AK-AN
]
assert len(COLS) == 40

for i, name in enumerate(COLS, start=1):
    ws.cell(row=2, column=i, value=name)
    style_group_header(ws.cell(row=2, column=i))

ws.row_dimensions[1].height = 15.75
ws.row_dimensions[2].height = 36
ws.freeze_panes = "A3"

group_headers = [
    ("A1:E1", "FROM DATABASE — verify, do not edit"),
    ("F1:Q1", "SEAT & FLEET CONFIG"),
    ("R1:R1", "SEAT DATA SOURCE"),
    ("S1:S1", "DB REF"),
    ("T1:U1", "INPUTS — fill yellow cells"),
    ("V1:X1", "WHOLE AIRCRAFT RETROFIT (non-seat spend + fallback)"),
    ("Y1:AA1", "PREMIUM CABIN RETROFIT (First / Business / Privacy Door)"),
    ("AB1:AF1", "ECONOMY CABIN RETROFIT (Prem Eco / Eco Plus / Economy) + mid-life refresh"),
    ("AG1:AG1", "NOTES"),
    ("AH1:AJ1", "RETIREMENT ASSUMPTIONS"),
    ("AK1:AN1", "IFE & CONNECTIVITY"),
]
for rng, label in group_headers:
    ws.merge_cells(rng)
    start = rng.split(":")[0]
    ws[start] = label
    style_group_header(ws[start])

# column widths
widths = {"A":28,"B":16,"C":13,"D":20,"E":9,"F":8,"G":8,"H":8,"I":8,"J":8,"K":9,"L":8,"M":8,
          "N":8,"O":9,"P":10,"Q":12,"R":14,"S":10,"T":11,"U":13,
          "V":11,"W":13,"X":13,"Y":11,"Z":13,"AA":13,"AB":11,"AC":13,"AD":13,
          "AE":14,"AF":14,"AG":30,
          "AH":13,"AI":13,"AJ":14,"AK":10,"AL":15,"AM":14,"AN":30}
for col, w in widths.items():
    ws.column_dimensions[col].width = w

# data validations
dv_size = DataValidation(type="list", formula1='"Regional,Narrowbody,Widebody,Turboprop"', allow_blank=True)
dv_yn = DataValidation(type="list", formula1='"YES,NO"', allow_blank=True)
dv_deck = DataValidation(type="list", formula1='"Upper,Lower,"', allow_blank=True)
dv_seatsrc = DataValidation(type="list", formula1='"Assumption,AeroLOPA,Actual"', allow_blank=True)
dv_yn2 = DataValidation(type="list", formula1='"Y,N"', allow_blank=True)
dv_ife_type = DataValidation(type="list", formula1='"AVOD-Seatback,Overhead,BYOD-Streaming,No-IFE"', allow_blank=True)
for dv in (dv_size, dv_yn, dv_deck, dv_seatsrc, dv_yn2, dv_ife_type):
    ws.add_data_validation(dv)

n = len(subfleets)
last_row = 2 + n
dv_size.add(f"C3:C{last_row}")
dv_yn.add(f"T3:T{last_row}")
dv_deck.add(f"E3:E{last_row}")
dv_seatsrc.add(f"R3:R{last_row}")
dv_yn2.add(f"AE3:AE{last_row}")
dv_yn.add(f"AK3:AK{last_row}")
dv_ife_type.add(f"AL3:AL{last_row}")
dv_yn.add(f"AM3:AM{last_row}")

def cascade_formula(row, override_col, ad_col_idx, rd_col, mapcol):
    """Build the 3-tier cascade formula: subfleet override -> airline default (05) -> Size Class x Category
    default (06). 06_Retrofit_Defaults is a full Size Class x Category grid (incl. an explicit OTH row per
    size class) -- an airline with no Category set on 05_Airline_Defaults resolves to OTH here, so there's
    no separate blank-category fallback tier needed."""
    cat_lookup = (f'IF(VLOOKUP(A{row},\'05_Airline_Defaults\'!$A:$B,2,FALSE())="","OTH",'
                  f'VLOOKUP(A{row},\'05_Airline_Defaults\'!$A:$B,2,FALSE()))')
    return (
        f'=IF({override_col}{row}<>"",{override_col}{row},'
        f'IF(IFERROR(VLOOKUP(A{row},\'05_Airline_Defaults\'!$A:$F,{ad_col_idx},FALSE()),"")<>"",'
        f'VLOOKUP(A{row},\'05_Airline_Defaults\'!$A:$F,{ad_col_idx},FALSE()),'
        f'IFERROR(INDEX(\'06_Retrofit_Defaults\'!${rd_col}:${rd_col},'
        f'MATCH(C{row}&"|"&{cat_lookup},\'06_Retrofit_Defaults\'!${mapcol}:${mapcol},0)),'
        f'"NO MATCH - CHECK SIZE CLASS")))'
    )

def retrofit_last_year_formula(row, lookup_col):
    return (f'=IFERROR(IF(VLOOKUP(S{row},\'07_Retrofit_Baseline\'!$A:${lookup_col},'
            f'{openpyxl.utils.column_index_from_string(lookup_col)},FALSE)=0,"",'
            f'VLOOKUP(S{row},\'07_Retrofit_Baseline\'!$A:${lookup_col},'
            f'{openpyxl.utils.column_index_from_string(lookup_col)},FALSE)),"")')

def retirement_cascade_formula(row):
    """2-tier cascade: subfleet override (AH) -> Size Class default (08_Retirement_Defaults).
    Simpler than the retrofit cascade -- no airline-level tier, per Jon's chosen design."""
    return (f'=IF(AH{row}<>"",AH{row},'
            f'IFERROR(VLOOKUP(C{row},\'08_Retirement_Defaults\'!$A:$B,2,FALSE()),'
            f'"NO MATCH - CHECK SIZE CLASS"))')

def retirement_start_year_formula(row):
    """First forecast year (2026-2035) this subfleet's average age is projected to cross its
    effective retirement age, assuming fleet age advances ~1 yr/yr from the 2026 baseline (col Q) --
    mirrors the same assumption used in the DB-side retirements/fleet_count_adjusted computation."""
    return f'=IF(OR(Q{row}="",ISTEXT(AI{row})),"",2026+MAX(0,ROUNDUP(AI{row}-Q{row},0)))'

row = 3
for (sf_id, airline, model, size_class, subfleet_name, deck, source, f_lf, f_rc, f_dom, j_lf, j_rc, j_pd,
     pe, ep, eco, retirement_age_override, has_ife, ife_type, has_connectivity, connectivity_notes) in subfleets:
    seats = [f_lf, f_rc, f_dom, j_lf, j_rc, j_pd, pe, ep, eco]
    fleet_count, avg_age = fm.get(sf_id, (None, None))
    is_curated = airline in curated_airlines
    note_key = f"{airline}||{subfleet_name}"
    note = fleet_notes.get(note_key, "")

    values = [airline, model, size_class, subfleet_name, deck] + seats
    for i, v in enumerate(values, start=1):
        c = ws.cell(row=row, column=i, value=v)
        style_cell(c, F_GREEN, align="left" if i in (1,2,3,4) else "center")

    # O Total Seats - live formula
    c = ws.cell(row=row, column=15, value=f"=SUM(F{row}:N{row})")
    style_cell(c, F_BLUE, number_format="#,##0")

    c = ws.cell(row=row, column=16, value=fleet_count)
    style_cell(c, F_GREEN, number_format="#,##0")
    c = ws.cell(row=row, column=17, value=float(avg_age) if avg_age is not None else None)
    style_cell(c, F_GREEN, number_format="0.0")

    c = ws.cell(row=row, column=18, value="AeroLOPA" if source == "AeroLOPA" else "Assumption")
    style_cell(c, F_YELLOW)

    c = ws.cell(row=row, column=19, value=sf_id)
    style_cell(c, F_GREY)

    c = ws.cell(row=row, column=20, value="YES" if is_curated else "NO")
    style_cell(c, F_YELLOW)

    c = ws.cell(row=row, column=21, value=1)
    style_cell(c, F_YELLOW, number_format="0")

    # --- Whole Aircraft track (V,W,X) ---
    status = rb.get(sf_id, (None, None, "Unknown", None, None, None))[2]
    v_formula = retrofit_last_year_formula(row, "B")
    c = ws.cell(row=row, column=22, value=v_formula)
    style_cell(c, F_GREEN if status != "Unknown" else F_YELLOW, number_format="0")
    c = ws.cell(row=row, column=23, value=None)
    style_cell(c, F_YELLOW, number_format="0")
    c = ws.cell(row=row, column=24, value=cascade_formula(row, "W", 3, "C", "G"))
    style_cell(c, F_BLUE, number_format="0.0")

    # --- Premium track (Y,Z,AA) - placeholder, no DB cabin-tier data yet ---
    c = ws.cell(row=row, column=25, value=retrofit_last_year_formula(row, "K"))
    style_cell(c, F_GREY, number_format="0")
    c = ws.cell(row=row, column=26, value=None)
    style_cell(c, F_YELLOW, number_format="0")
    c = ws.cell(row=row, column=27, value=cascade_formula(row, "Z", 4, "D", "G"))
    style_cell(c, F_BLUE, number_format="0.0")

    # --- Economy track (AB,AC,AD) - placeholder ---
    c = ws.cell(row=row, column=28, value=retrofit_last_year_formula(row, "L"))
    style_cell(c, F_GREY, number_format="0")
    c = ws.cell(row=row, column=29, value=None)
    style_cell(c, F_YELLOW, number_format="0")
    c = ws.cell(row=row, column=30, value=cascade_formula(row, "AC", 5, "E", "G"))
    style_cell(c, F_BLUE, number_format="0.0")

    # --- Economy mid-life refresh (AE, AF) ---
    c = ws.cell(row=row, column=31, value=None)
    style_cell(c, F_YELLOW)
    c = ws.cell(row=row, column=32, value=None)
    style_cell(c, F_YELLOW, number_format="0")

    # --- Notes (AG) ---
    c = ws.cell(row=row, column=33, value=note if note else None)
    style_cell(c, F_YELLOW, align="left", wrap=True)

    # --- Retirement assumptions (AH, AI, AJ) ---
    c = ws.cell(row=row, column=34, value=float(retirement_age_override) if retirement_age_override is not None else None)
    style_cell(c, F_YELLOW, number_format="0.0")
    c = ws.cell(row=row, column=35, value=retirement_cascade_formula(row))
    style_cell(c, F_BLUE, number_format="0.0")
    c = ws.cell(row=row, column=36, value=retirement_start_year_formula(row))
    style_cell(c, F_BLUE, number_format="0")

    # --- IFE & Connectivity (AK, AL, AM, AN) ---
    # has_ife/ife_type: drafted from AeroLOPA Cabin Details where it covers this subfleet (green);
    # left blank where uncovered (yellow -- flagged for manual review, never guessed).
    ife_yn = "YES" if has_ife is True else ("NO" if has_ife is False else None)
    c = ws.cell(row=row, column=37, value=ife_yn)
    style_cell(c, F_GREEN if has_ife is not None else F_YELLOW)
    c = ws.cell(row=row, column=38, value=ife_type if ife_type else None)
    style_cell(c, F_GREEN if ife_type else F_YELLOW)
    # has_connectivity/connectivity_notes: no source data exists anywhere -- always blank,
    # 100% manual entry by design (intentionally ignores the unset DB column default).
    c = ws.cell(row=row, column=39, value=None)
    style_cell(c, F_YELLOW)
    c = ws.cell(row=row, column=40, value=None)
    style_cell(c, F_YELLOW, align="left", wrap=True)

    row += 1

print(f"01_Fleet_Baseline built: {row-3} data rows (rows 3-{row-1})")

# ---------------------------------------------------------------------------
# 02_Program_Scope
# ---------------------------------------------------------------------------
ws = wb.create_sheet("02_Program_Scope")
ws.column_dimensions["A"].width = 4
ws.column_dimensions["B"].width = 38
ws.column_dimensions["C"].width = 70
ws.column_dimensions["D"].width = 55

def plain(cell, size=9, bold=False, color="FF000000", wrap=False, align="left"):
    cell.font = Font(name="Arial", size=size, bold=bold, color=color)
    cell.alignment = Alignment(horizontal=align, vertical="center", wrap_text=wrap)

ws["B2"] = "02_PROGRAM_SCOPE"
plain(ws["B2"], size=16, bold=True, color="FF1F3864")
ws["B3"] = "Cabin retrofit / repair program logic — how mod size, timing, and the three retrofit tracks are calculated"
plain(ws["B3"], size=9, color="FF1F3864")

ws["B5"] = "WHY THIS SHEET CHANGED"
plain(ws["B5"], size=12, bold=True, color="FF1F3864")
ws["B6"] = ("v1 of this template used a static 'Default Mod Size by Airline Tier' lookup table on this sheet. "
            "That table was removed in v2 and remains removed in v3. Mod size (Small / Medium / Large) is not a "
            "fixed per-row value -- it is CALCULATED PER YEAR for each subfleet, based on where that year falls "
            "in the subfleet's retrofit cycle. This sheet explains the rule; the calculation itself runs "
            "downstream in the forecast_spend logic (not as an editable cell here), driven by inputs you provide "
            "on 01_Fleet_Baseline.")
plain(ws["B6"], wrap=True)
ws.row_dimensions[6].height = 60
ws.merge_cells("B6:D6")

ws["B8"] = "WHOLE AIRCRAFT vs. CABIN-TIER TRACKS (new in v3)"
plain(ws["B8"], size=12, bold=True, color="FF1F3864")
ws["B9"] = ("01_Fleet_Baseline now carries three independent retrofit tracks per subfleet: WHOLE AIRCRAFT, "
            "PREMIUM (First/Business/Privacy Door seats), and ECONOMY (Prem Eco/Eco Plus/Economy seats). "
            "Seat-replacement spend for a given cabin uses that cabin's own track. Everything else -- carpets, "
            "sidewalls, panels, galleys, lavatories, IFEC, Eng & Cert, and any other non-seat-specific line item "
            "-- stays on the WHOLE AIRCRAFT track. We are intentionally not splitting non-seat spend by cabin "
            "tier yet; it adds complexity the data doesn't need right now. The Whole Aircraft track also acts as "
            "the fallback any time a cabin-specific signal isn't available.")
plain(ws["B9"], wrap=True)
ws.row_dimensions[9].height = 70
ws.merge_cells("B9:D9")

ws["B11"] = "CYCLICAL MOD-SIZE RULE"
plain(ws["B11"], size=12, bold=True, color="FF1F3864")
ws["B12"] = "Position in retrofit cycle"; ws["C12"] = "Mod Size"; ws["D12"] = "Applies to"
for col in "BCD":
    plain(ws[f"{col}12"], bold=True, color="FFFFFFFF")
    ws[f"{col}12"].fill = fill("FF1F3864")
mod_rows = [
    ("Retrofit year itself (years_since_last_retrofit == 0)", "LARGE",
     "Eng & Cert (and other retrofit-tied line items) for that subfleet-year, per track. Supersedes Small/Medium -- only one size applies per year."),
    ("Halfway point of the interval (years_since == ROUND(interval/2))", "MEDIUM",
     "Eng & Cert line item only -- this is the only product_code in 03_Pricing_Reference where mod_size varies."),
    ("Every other year in the cycle", "SMALL", "Eng & Cert line item only."),
]
r = 13
for a, b, c in mod_rows:
    ws.cell(row=r, column=2, value=a); plain(ws.cell(row=r,column=2), wrap=True)
    ws.cell(row=r, column=3, value=b); plain(ws.cell(row=r,column=3))
    ws.cell(row=r, column=4, value=c); plain(ws.cell(row=r,column=4), wrap=True)
    ws.row_dimensions[r].height = 30
    r += 1

r += 1
ws.cell(row=r, column=2, value="Worked example"); plain(ws.cell(row=r,column=2), bold=True, color="FF1F3864", size=10)
r += 1
ws.cell(row=r, column=2, value=("Subfleet retrofitted in 2023 (Whole Aircraft or cabin-specific track), effective interval = 8 years, "
                                  "halfway = ROUND(8/2) = 4.\n2023 (years_since=0) -> LARGE.  2024-2026 (years_since=1-3) -> SMALL.  "
                                  "2027 (years_since=4) -> MEDIUM.\n2028-2030 (years_since=5-7) -> SMALL.  2031 (years_since=0, cycle restarts) -> LARGE."))
plain(ws.cell(r,column=2) if False else ws.cell(row=r,column=2), wrap=True)
ws.merge_cells(f"B{r}:D{r}")
ws.row_dimensions[r].height = 55
r += 2

ws.cell(row=r, column=2, value="RETROFIT ROLLOUT DURATION (deferred / not yet in this template)")
plain(ws.cell(row=r,column=2), size=12, bold=True, color="FF1F3864")
r += 1
ws.cell(row=r, column=2, value=("A retrofit program typically reconfigures 2-3 aircraft/month, so a 30-aircraft fleet takes roughly "
                                  "10-15 months and can span two calendar years depending on start month. This template treats a "
                                  "retrofit as landing entirely in the relevant track's 'Retrofit Last Year' column for simplicity. "
                                  "To model rollout pacing explicitly later, the plan is a dedicated 'retrofit_events' table (program "
                                  "start month, aircraft/month rate, fleet size -> spend spread across months/years). Flagged as "
                                  "possibly too granular for now; this note exists so the gap is visible rather than silently assumed."))
plain(ws.cell(r,column=2), wrap=True)
ws.merge_cells(f"B{r}:D{r}")
ws.row_dimensions[r].height = 70
r += 2

ws.cell(row=r, column=2, value="REPAIR SPEND CADENCE")
plain(ws.cell(row=r,column=2), size=12, bold=True, color="FF1F3864")
r += 1
ws.cell(row=r, column=2, value=("Repair spend represents annual cabin maintenance cost. 01_Fleet_Baseline col U ('Repair Interval "
                                  "(yrs)') defaults to 1 (annual) for every row, at the whole-aircraft level. Override only if a "
                                  "specific subfleet has a confirmed non-annual repair cadence."))
plain(ws.cell(r,column=2), wrap=True)
ws.merge_cells(f"B{r}:D{r}")
ws.row_dimensions[r].height = 45

print("02_Program_Scope built")

# ---------------------------------------------------------------------------
# 03_Pricing_Reference
# ---------------------------------------------------------------------------
ws = wb.create_sheet("03_Pricing_Reference")
widths3 = {"A":18,"B":20,"C":36,"D":11,"E":13,"F":12,"G":10,"H":14,"I":8,"J":12,"K":12,"L":12}
for col, w in widths3.items():
    ws.column_dimensions[col].width = w
ws.freeze_panes = "A3"

ws["A1"] = f"PRICING REFERENCE  —  All {len(pricing)} Assumption Rows  |  Base Year 2026  |  Read-Only"
style_title(ws["A1"], size=11)
for col in "BCDEFGHIJKL":
    style_title(ws[f"{col}1"])

headers3 = ["Product Group","Code","Display Name","Cost Basis","Service Type","Size Class","Mod Size",
            "Base Cost\n2026","Esc Rate","Est Cost\n2028","Est Cost\n2030","Est Cost\n2032"]
for i, h in enumerate(headers3, start=1):
    ws.cell(row=2, column=i, value=h)
    style_header_blue(ws.cell(row=2, column=i))
ws.row_dimensions[2].height = 30

row = 3
for product_group, code, display_name, cost_basis, service_type, size_class, mod_size, base_cost, esc_rate in pricing:
    vals = [product_group, code, display_name, cost_basis, service_type, size_class, mod_size]
    for i, v in enumerate(vals, start=1):
        c = ws.cell(row=row, column=i, value=v)
        style_cell(c, F_GREY, align="left" if i in (1,2,3) else "center")
    c = ws.cell(row=row, column=8, value=float(base_cost))
    style_cell(c, F_GREY, number_format='\\$#,##0')
    c = ws.cell(row=row, column=9, value=float(esc_rate))
    style_cell(c, F_GREY, number_format='0.00%')
    for off, yrs in ((10,2),(11,4),(12,6)):
        c = ws.cell(row=row, column=off, value=f"=H{row}*(1+I{row})^{yrs}")
        style_cell(c, F_GREY, number_format='\\$#,##0')
        c.font = font("FF000000", size=8)
    row += 1

print(f"03_Pricing_Reference built: {row-3} data rows")

# ---------------------------------------------------------------------------
# 04_Import_Guide
# ---------------------------------------------------------------------------
ws = wb.create_sheet("04_Import_Guide")
ws.column_dimensions["A"].width = 3
ws.column_dimensions["B"].width = 30
ws.column_dimensions["C"].width = 58
ws.column_dimensions["D"].width = 46

ws["B1"] = "IMPORT GUIDE — Complete the template, then share with Claude to import"
style_title(ws["B1"])
for col in "CD":
    style_title(ws[f"{col}1"])

ws["B2"] = "STEP BY STEP  (for a first pass: MANDATORY = needed to start developing forecasts, OPTIONAL = refine later)"
style_header_blue(ws["B2"], size=10)
for col in "CD":
    style_header_blue(ws[f"{col}2"], size=10)

steps = [
    ("MANDATORY — verify, don't re-key", "Size Class (col C), Deck (col E), and seat counts (cols F-N) are "
     "pre-populated from the database/AeroLOPA. Spot-check rows where col R = \"Assumption\" (a guess, not a "
     "real source) — those are the ones most likely to be wrong. Deck rows use a default convention "
     "(F/J/PD->Upper, PE/EcoPlus/Eco->Lower); verify against AeroLOPA per carrier, see col AG note."),
    ("MANDATORY", "Set Seat Data Source (col R) — Assumption / AeroLOPA / Actual. Update as you verify counts "
     "against a real source; rows still marked Assumption are your lowest-confidence data."),
    ("MANDATORY", "Set Include in Forecast? (col T) — YES for the active coverage universe, NO to exclude. "
     "Pre-flagged YES for the original 354-airline curated set, NO for the rest of the full 987-airline "
     "universe; nothing downstream calculates spend for a NO row, so this directly controls what's in scope."),
    ("OPTIONAL — only if you know a different cycle", "Retrofit Interval Override, per track (cols W/Z/AC). "
     "Leave blank to use the cascade default shown in the Effective Retrofit Interval column (subfleet override "
     "> airline-specific override from 05_Airline_Defaults > Size Class x Category default from "
     "06_Retrofit_Defaults). Fill in only for a specific subfleet with a confirmed program timing that differs "
     "from the default."),
    ("KNOWN GAP, not a fill-in task", "Whole Aircraft Retrofit Last Year (col V) is pre-populated (green) only "
     "where retrofit_baseline has a confirmed/estimated signal — that's 128 of 2,753 active subfleets (~5%); "
     "the other ~95% show \"Unknown\" with no anchor year. Filling these in one at a time isn't realistic for a "
     "first pass — flag to Claude if you want a bulk default strategy (e.g. assume due-now, or skip spend "
     "timing for Unknown rows until confirmed) rather than hand-editing thousands of cells."),
    ("OPTIONAL, deferred", "Premium track (cols Y-AA) and Economy track (cols AB-AD): same override/cascade "
     "mechanics as Whole Aircraft, but Retrofit Last Year (cols Y/AB) is a blank placeholder for every row right "
     "now — the DB's retrofit_baseline table isn't cabin-tier-aware yet (separate, deferred pass). Fill Override "
     "directly only if you know a confirmed Premium- or Economy-specific program timing for a subfleet."),
    ("OPTIONAL", "Economy Mid-Life Refresh (cols AE-AF). Set Y and a year only for carriers doing a standalone "
     "Economy refresh that isn't tied to the Premium cycle."),
    ("OPTIONAL", "Repair Interval (col U) — defaults to 1 (annual cabin maintenance), whole-aircraft level. "
     "Override only for a confirmed non-annual cadence."),
    ("FYI, not editable here", "Mod Size is NOT entered here — calculated per year from each track's retrofit "
     "cycle. See 02_Program_Scope for the Small/Medium/Large cyclical rule."),
    ("OPTIONAL — only for airlines you know differ", "05_Airline_Defaults col B (Category, FSC/GL/LCC/ULCC/"
     "RFSC/REG/LEI/OTH): you do NOT need to set this for every airline. Leave it blank for any airline you "
     "haven't specifically categorized — it will automatically use the OTH default on 06_Retrofit_Defaults, "
     "which is a valid, intentional fallback, not an error. Only set Category where you know an airline belongs "
     "in a more specific bucket and want its defaults to differ from OTH."),
    ("OPTIONAL — only for airlines you know differ", "05_Airline_Defaults cols C/D/E (Retrofit Years Override, "
     "per track): same logic as the subfleet-level override above, one level up. Leave blank unless you know a "
     "specific airline's retrofit cycle differs from its Size Class x Category default."),
    ("MANDATORY, already done for you — review the numbers", "06_Retrofit_Defaults is now a complete 32-row "
     "grid (4 Size Classes x 8 Categories) for Whole Aircraft, so every subfleet resolves to a real default "
     "even with no airline-level input. The Whole Aircraft numbers are still DRAFT placeholders (extrapolated, "
     "not researched) — review/replace them; Premium/Economy default columns are intentionally blank pending "
     "your program intelligence. Edit any cell any time, formulas update automatically."),
    ("RESOLVED v3.3.1 — review the numbers", "Turboprop subfleets (73 active) now have full pricing coverage "
     "in 03_Pricing_Reference (72 rows added to the assumptions table, sourced from your pricing matrix) — "
     "Turboprop spend now calculates. These were carried over from your numbers as-is except for a product-code "
     "typo on the Monuments rows ('tue'/'wed'/'thu' -> corrected to 'mon')."),
    ("OPTIONAL — only for subfleets you know differ", "Retirement Age Override (col AH). Leave blank to use the "
     "Size Class default from 08_Retirement_Defaults. Fill in only if you have a specific retirement/conversion "
     "plan for that subfleet. Effective Retirement Age (AI) and Est. Retirement Start Year (AJ) are formulas — "
     "don't edit directly."),
    ("MANDATORY, already done for you — review the numbers", "08_Retirement_Defaults' 4 retirement-age numbers "
     "(Widebody/Narrowbody/Regional/Turboprop) are DRAFT placeholders (25/25/20/30 years) — review/replace with "
     "real fleet-planning assumptions. This also drives the retirements / fleet_count_adjusted columns in the "
     "underlying forecast data (not shown directly in this template) — once a subfleet's average age crosses "
     "its effective retirement age, 20% of the fleet phases out per year against a 5-year retirement window."),
    ("REVIEW — auto-drafted, not guessed", "Has IFE? / IFE Type (cols AK/AL) were auto-drafted from AeroLOPA's "
     "cabin descriptions for the 1,506 subfleets AeroLOPA covers (green fill). The other 1,247 rows (mostly "
     "Manual-source subfleets with no AeroLOPA data) are blank (yellow) — fill in only if you know the actual "
     "IFE system; otherwise leave for a future data refresh."),
    ("MANDATORY — no source data exists", "Has Connectivity? / Connectivity Notes (cols AM/AN) are blank for "
     "every row — there is no WiFi/connectivity data source anywhere in the pipeline yet. 100% manual entry if "
     "you want this tracked; otherwise leave blank."),
    ("Last step", "Save file. Share with Claude to import — script updates subfleets, forecast_master and "
     "generates forecast_spend."),
]
r = 3
for tag, txt in steps:
    ws.cell(row=r, column=2, value=tag)
    ws.cell(row=r, column=3, value=txt)
    style_cell(ws.cell(row=r, column=2), F_YELLOW if tag.startswith("MANDATORY") else F_GREY,
               bold=True, align="left", wrap=True)
    style_cell(ws.cell(row=r, column=3), F_GREY, align="left", wrap=True)
    style_cell(ws.cell(row=r, column=4), F_GREY)
    ws.row_dimensions[r].height = 60
    r += 1

r += 1
ws.cell(row=r, column=2, value="HOW SPEND IS CALCULATED")
style_header_blue(ws.cell(row=r, column=2), size=10)
for col in "CD":
    style_header_blue(ws.cell(row=r, column=openpyxl.utils.column_index_from_string(col)), size=10)
r += 1

calc_rows = [
    ("per_seat:", "base_cost × (1+esc)^(year−2026) × seat_count — triggered in retrofit years (New/Replace, using the seat's cabin-tier track) or repair years (Repair, using the Whole Aircraft track)"),
    ("per_aircraft:", "base_cost[size_class] × (1+esc)^(year−2026) × fleet_count — Whole Aircraft track timing"),
    ("per_program (Eng & Cert only):", "eng_cert[size_class][mod_size] × (1+esc)^(year−2026) — mod_size determined by the cyclical rule, Whole Aircraft track, once per subfleet-year"),
]
for a, b in calc_rows:
    ws.cell(row=r, column=2, value=a); style_cell(ws.cell(row=r,column=2), F_GREY, bold=True, align="left")
    ws.cell(row=r, column=3, value=b); style_cell(ws.cell(row=r,column=3), F_GREY, align="left", wrap=True)
    style_cell(ws.cell(row=r, column=4), F_GREY)
    ws.row_dimensions[r].height = 30
    r += 1

r += 1
ws.cell(row=r, column=2, value="TIMING LOGIC")
style_header_blue(ws.cell(row=r, column=2), size=10)
for col in "CD":
    style_header_blue(ws.cell(row=r, column=openpyxl.utils.column_index_from_string(col)), size=10)
r += 1
timing_rows = [
    ("Retrofit year (per track):", "(year − retrofit_last_year) MOD effective_retrofit_interval == 0  →  mod_size = LARGE, for that track"),
    ("Repair year:", "(year − retrofit_last_year[Whole Aircraft]) MOD repair_interval_yrs == 0 AND not a retrofit year  →  repair line items apply"),
    ("Mod size (Eng & Cert only):", "years_since = (year − retrofit_last_year) MOD effective_retrofit_interval, Whole Aircraft track. LARGE if years_since==0; MEDIUM if years_since==ROUND(interval/2); else SMALL. Large supersedes — only one size per subfleet-year, no stacking."),
    ("New:", "applies to forecast_master.deliveries count each year regardless of retrofit cycle"),
    ("Rollout duration:", "NOT modeled in this template (a retrofit year posts its full spend in one year). See 02_Program_Scope for the deferred multi-month rollout note."),
]
for a, b in timing_rows:
    ws.cell(row=r, column=2, value=a); style_cell(ws.cell(row=r,column=2), F_GREY, bold=True, align="left")
    ws.cell(row=r, column=3, value=b); style_cell(ws.cell(row=r,column=3), F_GREY, align="left", wrap=True)
    style_cell(ws.cell(row=r, column=4), F_GREY)
    ws.row_dimensions[r].height = 36
    r += 1

print("04_Import_Guide built")

# ---------------------------------------------------------------------------
# 05_Airline_Defaults
# ---------------------------------------------------------------------------
ws = wb.create_sheet("05_Airline_Defaults")
widths5 = {"A":30,"B":12,"C":15,"D":15,"E":15,"F":50}
for col, w in widths5.items():
    ws.column_dimensions[col].width = w
ws.freeze_panes = "A3"

ws["A1"] = f"AIRLINE DEFAULTS  —  All {len(all_airlines)} Airlines  |  Category + Per-Track Retrofit-Year Overrides"
style_title(ws["A1"], size=11)
for col in "BCDEF":
    style_title(ws[f"{col}1"])

headers5 = ["Airline", "Category", "Retrofit Years Override\n(Whole Aircraft)",
            "Retrofit Years Override\n(Premium)", "Retrofit Years Override\n(Economy)", "Cadence Notes"]
for i, h in enumerate(headers5, start=1):
    ws.cell(row=2, column=i, value=h)
    style_header_blue(ws.cell(row=2, column=i))
ws.row_dimensions[2].height = 32

dv_cat = DataValidation(type="list", formula1='"FSC,GL,LCC,ULCC,RFSC,REG,LEI,OTH"', allow_blank=True)
ws.add_data_validation(dv_cat)
last_row5 = 2 + len(all_airlines)
dv_cat.add(f"B3:B{last_row5}")

F_GREY_NAVY = ("FFF2F2F2", "FF1F3864")
row = 3
for airline in all_airlines:
    carry = airline_defaults_filled.get(airline)
    category = carry.get("category") if carry else None
    notes = carry.get("notes") if carry else None

    c = ws.cell(row=row, column=1, value=airline)
    style_cell(c, F_GREY_NAVY, align="left")
    c = ws.cell(row=row, column=2, value=category if category else None)
    style_cell(c, F_YELLOW)
    for col in (3, 4, 5):
        c = ws.cell(row=row, column=col, value=None)
        style_cell(c, F_YELLOW, number_format="0")
    c = ws.cell(row=row, column=6, value=notes if notes else None)
    style_cell(c, F_GREY, align="left", wrap=True)
    row += 1

print(f"05_Airline_Defaults built: {row-3} data rows")

# ---------------------------------------------------------------------------
# 06_Retrofit_Defaults
# ---------------------------------------------------------------------------
ws = wb.create_sheet("06_Retrofit_Defaults")
widths6 = {"A":16,"B":14,"C":17,"D":17,"E":17,"F":15,"G":16,"H":50}
for col, w in widths6.items():
    ws.column_dimensions[col].width = w
ws.freeze_panes = "A3"

ws["A1"] = "RETROFIT & REPAIR DEFAULTS  —  By Aircraft Size Class x Airline Category  |  Wide by Track  |  Edit freely"
style_title(ws["A1"], size=11)
for col in "BCDEFGH":
    style_title(ws[f"{col}1"])

headers6 = ["Aircraft Size Class", "Airline Category", "Default Retrofit Years\n(Whole Aircraft)",
            "Default Retrofit Years\n(Premium)", "Default Retrofit Years\n(Economy)",
            "Default Repair Years", "Lookup Key", "Notes"]
for i, h in enumerate(headers6, start=1):
    ws.cell(row=2, column=i, value=h)
    style_header_blue(ws.cell(row=2, column=i))
ws.row_dimensions[2].height = 32

row = 3
for size_class, category, retrofit_years, repair_years, notes in defaults14:
    c = ws.cell(row=row, column=1, value=size_class); style_cell(c, F_GREY, align="left")
    c = ws.cell(row=row, column=2, value=category if category else None); style_cell(c, F_GREY, align="left")
    c = ws.cell(row=row, column=3, value=float(retrofit_years) if retrofit_years is not None else None)
    style_cell(c, F_YELLOW, number_format="0.0")
    c = ws.cell(row=row, column=4, value=None); style_cell(c, F_YELLOW, number_format="0.0")
    c = ws.cell(row=row, column=5, value=None); style_cell(c, F_YELLOW, number_format="0.0")
    c = ws.cell(row=row, column=6, value=float(repair_years) if repair_years is not None else None)
    style_cell(c, F_YELLOW, number_format="0.0")
    c = ws.cell(row=row, column=7, value=f'=A{row}&"|"&B{row}')
    style_cell(c, F_BLUE, align="left")
    c = ws.cell(row=row, column=8, value=notes if notes else None)
    style_cell(c, F_GREY, align="left", wrap=True)
    row += 1

print(f"06_Retrofit_Defaults built: {row-3} data rows")

# ---------------------------------------------------------------------------
# 07_Retrofit_Baseline
# ---------------------------------------------------------------------------
ws = wb.create_sheet("07_Retrofit_Baseline")
widths7 = {"A":10,"B":12,"C":11,"D":11,"E":28,"F":16,"G":20,"H":13,"I":24,"J":50,"K":14,"L":14}
for col, w in widths7.items():
    ws.column_dimensions[col].width = w
ws.freeze_panes = "A3"

ws["A1"] = ("RETROFIT BASELINE  —  DB Export, Read-Only  |  Whole Aircraft column populated from cabin_events; "
            "Premium/Economy columns are placeholders pending the cabin-tier-aware DB rebuild")
style_title(ws["A1"], size=10)
for col in "BCDEFGHIJKL":
    style_title(ws[f"{col}1"])

headers7 = ["Subfleet ID", "Last Confirmed\nRetrofit Year\n(Whole Aircraft)", "Confidence", "Status",
            "Airline", "Aircraft Model", "Subfleet Name", "Source Event", "Match Basis", "Notes",
            "Last Confirmed\nRetrofit Year\n(Premium)", "Last Confirmed\nRetrofit Year\n(Economy)"]
for i, h in enumerate(headers7, start=1):
    ws.cell(row=2, column=i, value=h)
    style_header_blue(ws.cell(row=2, column=i))
ws.row_dimensions[2].height = 36

row = 3
for sf_id, airline, model, size_class, subfleet_name, deck, *_seats in subfleets:
    last_year, confidence, status, match_basis, notes, event_id = rb.get(
        sf_id, (None, None, "Unknown", None, None, None))

    c = ws.cell(row=row, column=1, value=sf_id); style_cell(c, F_GREY, number_format="0")
    c = ws.cell(row=row, column=2, value=last_year); style_cell(c, F_GREY, number_format="0")
    c = ws.cell(row=row, column=3, value=confidence if confidence else None); style_cell(c, F_GREY)
    c = ws.cell(row=row, column=4, value=status); style_cell(c, F_GREY)
    c = ws.cell(row=row, column=5, value=airline); style_cell(c, F_GREY, align="left")
    c = ws.cell(row=row, column=6, value=model); style_cell(c, F_GREY, align="left")
    c = ws.cell(row=row, column=7, value=subfleet_name); style_cell(c, F_GREY, align="left")
    c = ws.cell(row=row, column=8, value=event_id if event_id else None); style_cell(c, F_GREY)
    c = ws.cell(row=row, column=9, value=match_basis if match_basis else None); style_cell(c, F_GREY, align="left")
    c = ws.cell(row=row, column=10, value=notes if notes else None); style_cell(c, F_GREY, align="left", wrap=True)
    c = ws.cell(row=row, column=11, value=None); style_cell(c, F_GREY, number_format="0")
    c = ws.cell(row=row, column=12, value=None); style_cell(c, F_GREY, number_format="0")
    row += 1

print(f"07_Retrofit_Baseline built: {row-3} data rows")

# ---------------------------------------------------------------------------
# 08_Retirement_Defaults
# ---------------------------------------------------------------------------
ws = wb.create_sheet("08_Retirement_Defaults")
widths8 = {"A": 18, "B": 22, "C": 60}
for col, w in widths8.items():
    ws.column_dimensions[col].width = w
ws.freeze_panes = "A3"

ws["A1"] = "RETIREMENT AGE DEFAULTS  —  By Aircraft Size Class  |  Edit freely"
style_title(ws["A1"], size=11)
for col in "BC":
    style_title(ws[f"{col}1"])

headers8 = ["Aircraft Size Class", "Default Retirement Age (yrs)", "Notes"]
for i, h in enumerate(headers8, start=1):
    ws.cell(row=2, column=i, value=h)
    style_header_blue(ws.cell(row=2, column=i))
ws.row_dimensions[2].height = 24

row = 3
for size_class, default_age, notes in retirement_defaults:
    c = ws.cell(row=row, column=1, value=size_class); style_cell(c, F_GREY, align="left")
    c = ws.cell(row=row, column=2, value=float(default_age)); style_cell(c, F_YELLOW, number_format="0.0")
    c = ws.cell(row=row, column=3, value=notes if notes else None); style_cell(c, F_GREY, align="left", wrap=True)
    ws.row_dimensions[row].height = 30
    row += 1

print(f"08_Retirement_Defaults built: {row-3} data rows")

# ---------------------------------------------------------------------------
# Save + verify
# ---------------------------------------------------------------------------
sheet_order = ["00_Instructions", "01_Fleet_Baseline", "02_Program_Scope", "03_Pricing_Reference",
               "04_Import_Guide", "05_Airline_Defaults", "06_Retrofit_Defaults", "07_Retrofit_Baseline",
               "08_Retirement_Defaults"]
wb._sheets = [wb[name] for name in sheet_order]
wb.active = 0

wb.save(OUT_PATH)
print(f"Saved: {OUT_PATH}")

import zipfile
zf = zipfile.ZipFile(OUT_PATH)
bad = zf.testzip()
assert bad is None, f"corrupt member: {bad}"
print(f"Zip integrity OK -- {len(zf.namelist())} members")

wb2 = openpyxl.load_workbook(OUT_PATH)
print("Reopen OK. Sheets:", wb2.sheetnames)
for name in sheet_order:
    ws2 = wb2[name]
    print(f"  {name}: max_row={ws2.max_row}, max_col={ws2.max_column}")
