"""
update_retirement_age_defaults.py
Lele Aviation Intelligence Platform — Retirement Age Defaults Update

Jon edited the 08_Retirement_Defaults sheet directly in
forecast_baseline_template_v3.3-c9ebeae8.xlsx, replacing the four DRAFT
placeholder ages with his own researched assumptions:

    Widebody:   25 -> 20
    Narrowbody: 25 -> 25  (unchanged)
    Regional:   20 -> 30
    Turboprop:  30 -> 30  (unchanged)

This script pushes those four values to the live `retirement_age_defaults`
table. Per the established pattern, this MUST happen before any workbook
rebuild, since the rebuild script re-populates 08_Retirement_Defaults
straight from this table -- a direct in-workbook edit that isn't pushed back
to the DB first would be silently overwritten on the next rebuild.

Idempotent: plain UPDATE by aircraft_size_class, safe to re-run.

RUN:  python update_retirement_age_defaults.py
"""

import os
import sys
import psycopg2
from dotenv import load_dotenv

load_dotenv()
url = os.getenv("DATABASE_URL")
if not url:
    sys.exit("DATABASE_URL not found in .env file.")

NEW_VALUES = {
    "Widebody": 20,
    "Narrowbody": 25,
    "Regional": 30,
    "Turboprop": 30,
}

conn = psycopg2.connect(url, connect_timeout=15)
conn.autocommit = False
cur = conn.cursor()

print("1. Current state:")
cur.execute("select aircraft_size_class, default_retirement_age from retirement_age_defaults order by 1")
before = dict(cur.fetchall())
for k, v in before.items():
    print(f"   {k}: {v}")

print("\n2. Applying Jon's new values...")
for size_class, new_age in NEW_VALUES.items():
    cur.execute(
        "UPDATE retirement_age_defaults SET default_retirement_age = %s WHERE aircraft_size_class = %s",
        (new_age, size_class),
    )
    if cur.rowcount != 1:
        sys.exit(f"FATAL: expected exactly 1 row updated for '{size_class}', got {cur.rowcount} -- aborting.")
conn.commit()

print("\n3. Verification:")
cur.execute("select aircraft_size_class, default_retirement_age from retirement_age_defaults order by 1")
after = dict(cur.fetchall())
for k, v in after.items():
    changed = " (changed)" if before[k] != v else " (unchanged)"
    print(f"   {k}: {before[k]} -> {v}{changed}")

cur.close()
conn.close()
print("\nDone.")
