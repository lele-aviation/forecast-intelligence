"""
apply_airline_categories.py
Lele Aviation Intelligence Platform — Bulk Airline Categorization

Closes the "only 23/981 airlines have a category assigned" gap flagged in
ARCHITECTURE.md Part 1 / Part 7 item 4. Jon did a full manual pass over all
987 airlines (weekend of 2026-06-20/21) assigning each one of the 8 taxonomy
values (FSC/GL/LCC/ULCC/RFSC/REG/LEI/OTH) and sent the completed sheet back
as "Airline Categories - Completed.xlsx".

This script:
  1. Reads the categorization from reference/airline_categories_2026-06-22.xlsx
     (a stable checked-in copy of Jon's file — same 05_Airline_Defaults sheet
     layout as the workbook, columns A=Airline, B=Category, F=Cadence Notes).
  2. Updates airlines.airline_category for all 987 matched rows (exact name
     match against the live `airlines` table — verified 987/987 match, zero
     unresolved names, before this script was written).
  3. Reports the full before/after category distribution, and flags the 9
     airlines where Jon's new pass changed a category that had previously
     been hand-set in the DB (legacy seed data, e.g. several FSC -> GL
     reclassifications) -- informational only, Jon's new pass is authoritative.

Note: airline-level Cadence Notes (17 rows) are NOT written to the DB here --
that field has no dedicated DB column (`airlines.notes` is used for a
different purpose, AeroLOPA new-row provenance) and is carried forward
workbook-to-workbook by design (see ARCHITECTURE.md Part 6). The rebuild
script merges Jon's notes from this same reference file directly.

Idempotent: safe to re-run (plain UPDATE by name, same input -> same result).

RUN:  python apply_airline_categories.py
"""

import os
import sys
import psycopg2
from psycopg2.extras import execute_values
import openpyxl
from dotenv import load_dotenv

load_dotenv()
url = os.getenv("DATABASE_URL")
if not url:
    sys.exit("DATABASE_URL not found in .env file.")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE_FILE = os.path.join(SCRIPT_DIR, "..", "reference", "airline_categories_2026-06-22.xlsx")

VALID_CATEGORIES = {"FSC", "GL", "LCC", "ULCC", "RFSC", "REG", "LEI", "OTH"}

print(f"1. Reading categorization from {SOURCE_FILE}...")
wb = openpyxl.load_workbook(SOURCE_FILE, data_only=True)
ws = wb["05_Airline_Defaults"]

rows = []
for r in range(3, ws.max_row + 1):
    name = ws.cell(row=r, column=1).value
    category = ws.cell(row=r, column=2).value
    if name is None:
        continue
    if category not in VALID_CATEGORIES:
        sys.exit(f"FATAL: row {r} airline '{name}' has invalid category {category!r} -- aborting, fix source file.")
    rows.append((name, category))

print(f"   {len(rows)} airline rows read, all categories valid.\n")

conn = psycopg2.connect(url, connect_timeout=15)
conn.autocommit = False
cur = conn.cursor()

print("2. Verifying every airline name resolves to a DB row...")
cur.execute("select name from airlines")
db_names = {row[0] for row in cur.fetchall()}
unmatched = [name for name, _ in rows if name not in db_names]
if unmatched:
    sys.exit(f"FATAL: {len(unmatched)} airline name(s) in source file not found in DB: {unmatched[:10]} -- aborting.")
print("   all names matched.\n")

print("3. Capturing prior state for the changed-airlines report...")
cur.execute("select name, airline_category from airlines where airline_category is not null")
prior = dict(cur.fetchall())

print("4. Applying updates (single bulk statement, not 987 round trips)...")
execute_values(
    cur,
    "UPDATE airlines AS a SET airline_category = v.category, updated_at = now() "
    "FROM (VALUES %s) AS v(name, category) WHERE a.name = v.name",
    rows,
)
updated = cur.rowcount
conn.commit()
print(f"   {updated} rows updated (re-running is idempotent -- same values, no-op on a second pass).\n")

print("5. Verification:")
cur.execute("select count(*) from airlines where airline_category is not null")
print("   total categorized:", cur.fetchone()[0], "/ 987")

cur.execute("select airline_category, count(*) from airlines group by 1 order by 2 desc")
print("   distribution:")
for row in cur.fetchall():
    print("    ", row)

print("\n6. Airlines where Jon's new pass changed a previously-set category (informational):")
new_map = dict(rows)
changed = [(name, prior[name], new_map[name]) for name in prior if prior[name] != new_map.get(name)]
for name, old, new in changed:
    print(f"    {name}: {old} -> {new}")
print(f"   {len(changed)} changed.")

cur.close()
conn.close()
print("\nDone.")
