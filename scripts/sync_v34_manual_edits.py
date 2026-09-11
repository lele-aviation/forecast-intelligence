"""
sync_v34_manual_edits.py
Lele Aviation Intelligence Platform -- Sync Jon's manual v3.4 workbook edits to DB

Jon hand-edited forecast_baseline_template_v3.4.xlsx directly in Excel:
  1. Filled in Has IFE? (First/Business/Prem Eco/Economy) + IFE Type for every
     active subfleet (previously ~2,127/3,631 rows were blank -- AeroLOPA-
     uncovered). Some of his entries go beyond AeroLOPA's auto-draft coverage
     (e.g. has_ife_first YES count rose from 70 to 92), so this is treated as
     an authoritative full overwrite of the 8 IFE columns for all 2,753
     active subfleets, not a sparse patch.
  2. Zeroed out J Lie-Flat (seats_j_lieflat) wherever J Privacy Door
     (seats_j_privacy_door) is nonzero -- a privacy-door business seat is no
     longer double-counted as a plain lie-flat seat. Confirmed exactly 63
     active subfleets are affected, and the DB currently still carries the
     pre-correction nonzero lie-flat value for all 63.
  3. Has Connectivity?/Connectivity Notes: workbook shows NO/blank for every
     row, which already matches the DB default (has_connectivity DEFAULT
     FALSE, connectivity_notes NULL) -- included below anyway for an explicit,
     idempotent full overwrite rather than relying on the column default.

Per the project's standing rule (workbook columns sourced from the DB get
silently overwritten on the next rebuild), these edits must land in the DB
before any future build_template_v34.py re-run, or they're lost.

Known data-quality flags in Jon's edits, NOT auto-corrected by this script
(pushed to DB exactly as entered -- see chat for the full list):
  - 1 row (subfleet 12019, Eastern Airlines 767-300ER) has Has IFE? (Economy)
    left blank while IFE Type (Economy) = 'No-IFE' -- looks like an
    unintentional blank, pushed through as NULL rather than guessed.
  - 15 rows: Has IFE? (First) = YES but IFE Type (First) = 'No-IFE'.
  - 25 rows: Has IFE? (Business) = NO but IFE Type (Business) is a real type
    (mostly BYOD-Streaming on regional jets -- CRJ/E-Jet/Dash 8 fleets).
  - 1 row: Has IFE? (Business) = YES but IFE Type (Business) = 'No-IFE'.
  - 2 rows: Has IFE? (Prem Eco) = NO but IFE Type (Prem Eco) is a real type.

Idempotent: full overwrite by subfleet id from the current workbook state,
safe to re-run.

RUN:  python sync_v34_manual_edits.py
"""

import os
import sys
import openpyxl
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

load_dotenv()
url = os.getenv("DATABASE_URL")
if not url:
    sys.exit("DATABASE_URL not found in .env file.")

WORKBOOK_PATH = os.path.join(os.path.dirname(__file__), "..", "forecast_baseline_template_v3.4.xlsx")

IFE_COLS = {
    "has_ife_first": 37, "ife_type_first": 38,
    "has_ife_business": 39, "ife_type_business": 40,
    "has_ife_premium_economy": 41, "ife_type_premium_economy": 42,
    "has_ife_economy": 43, "ife_type_economy": 44,
}
OTHER_COLS = {
    "subfleet_id": 19,
    "j_lieflat": 9, "j_privacydoor": 11,
    "has_connectivity": 45, "connectivity_notes": 46,
}
ALL_COLS = {**OTHER_COLS, **IFE_COLS}


def yn_to_bool(v):
    if v == "YES":
        return True
    if v == "NO":
        return False
    return None


print(f"1. Reading {WORKBOOK_PATH} ...")
wb = openpyxl.load_workbook(WORKBOOK_PATH, data_only=True)
ws = wb["01_Fleet_Baseline"]
print(f"   max_row={ws.max_row}, max_col={ws.max_column}")

wb_rows = {}
for r in range(3, ws.max_row + 1):
    row = {k: ws.cell(row=r, column=c).value for k, c in ALL_COLS.items()}
    if row["subfleet_id"] is None:
        continue
    wb_rows[row["subfleet_id"]] = row
print(f"   {len(wb_rows)} active subfleet rows read.\n")

conn = psycopg2.connect(url, connect_timeout=15)
conn.autocommit = False
cur = conn.cursor()

print("2. Building IFE/connectivity full-overwrite update list (all active subfleets)...")
ife_updates = []
for sid, w in wb_rows.items():
    ife_updates.append((
        sid,
        yn_to_bool(w["has_ife_first"]), w["ife_type_first"] or None,
        yn_to_bool(w["has_ife_business"]), w["ife_type_business"] or None,
        yn_to_bool(w["has_ife_premium_economy"]), w["ife_type_premium_economy"] or None,
        yn_to_bool(w["has_ife_economy"]), w["ife_type_economy"] or None,
        yn_to_bool(w["has_connectivity"]) if w["has_connectivity"] is not None else False,
        w["connectivity_notes"] or None,
    ))
print(f"   {len(ife_updates)} rows queued.\n")

print("3. Building J Lie-Flat privacy-door correction list...")
lieflat_updates = []
for sid, w in wb_rows.items():
    if (w["j_privacydoor"] or 0) > 0:
        lieflat_updates.append((sid, w["j_lieflat"] or 0))
print(f"   {len(lieflat_updates)} rows queued (subfleets with nonzero J Privacy Door).\n")

print("4. Applying IFE/connectivity bulk update...")
execute_values(
    cur,
    """
    UPDATE subfleets AS s SET
        has_ife_first = v.has_ife_first, ife_type_first = v.ife_type_first,
        has_ife_business = v.has_ife_business, ife_type_business = v.ife_type_business,
        has_ife_premium_economy = v.has_ife_premium_economy, ife_type_premium_economy = v.ife_type_premium_economy,
        has_ife_economy = v.has_ife_economy, ife_type_economy = v.ife_type_economy,
        has_connectivity = v.has_connectivity, connectivity_notes = v.connectivity_notes
    FROM (VALUES %s) AS v(
        id, has_ife_first, ife_type_first, has_ife_business, ife_type_business,
        has_ife_premium_economy, ife_type_premium_economy, has_ife_economy, ife_type_economy,
        has_connectivity, connectivity_notes
    ) WHERE s.id = v.id
    """,
    ife_updates,
)
print("   Done.\n")

print("5. Applying J Lie-Flat correction...")
execute_values(
    cur,
    """
    UPDATE subfleets AS s SET seats_j_lieflat = v.j_lieflat
    FROM (VALUES %s) AS v(id, j_lieflat)
    WHERE s.id = v.id
    """,
    lieflat_updates,
)
conn.commit()
print("   Done.\n")

print("6. Verification:")
cur.execute("""
    select
        count(*) filter (where has_ife_first), count(*) filter (where has_ife_business),
        count(*) filter (where has_ife_premium_economy), count(*) filter (where has_ife_economy)
    from subfleets where valid_to is null
""")
print("   YES counts (first, business, premeco, eco):", cur.fetchone())

cur.execute("""
    select count(*) from subfleets
    where valid_to is null and seats_j_privacy_door > 0 and seats_j_lieflat <> 0
""")
print("   Remaining privacy-door rows with nonzero lie-flat (should be 0):", cur.fetchone()[0])

cur.close()
conn.close()
print("\nDone.")
