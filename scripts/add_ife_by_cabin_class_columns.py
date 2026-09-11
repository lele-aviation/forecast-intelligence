"""
add_ife_by_cabin_class_columns.py
Lele Aviation Intelligence Platform — IFE-by-Cabin-Class Schema Migration

Jon asked to break IFE tracking out by seat type. AeroLOPA's source data only
distinguishes IFE at the 4-way cabin-class grain (First/Business/Premium
Economy/Economy) -- not the finer seat-hardware-variant grain (e.g. F
Lie-Flat vs F Recliner vs F Domestic share one First-cabin IFE value).
Confirmed this grain + a Has-IFE?/IFE-Type column pair per class with Jon
directly (2026-06-22).

Adds 8 new columns to `subfleets`:
    has_ife_first,            ife_type_first
    has_ife_business,         ife_type_business
    has_ife_premium_economy,  ife_type_premium_economy
    has_ife_economy,          ife_type_economy

These are NOT DEFAULT FALSE like the original has_ife column (that mixed
"confirmed no IFE" with "unknown/uncovered" -- visible today as a None/False
split in the legacy data: 1,247 None/None + 878 False/None + 795 False/
'No-IFE'). NULL here means "not covered by AeroLOPA / no seats of this
type"; FALSE means "confirmed no IFE in this cabin." The original
has_ife/ife_type pair is left in place (nothing else in the DB references
it) but is no longer surfaced in the workbook -- superseded by these four
pairs.

This same migration block is also appended to create_schema.py (Group F)
for the permanent record -- this standalone script exists only because of
a transient OneDrive sync lag that prevented create_schema.py's update from
being visible to the shell in this session. Once that resolves, running
create_schema.py alone is sufficient; running this script again is a no-op
either way (every statement uses IF NOT EXISTS / IF EXISTS).

RUN:  python add_ife_by_cabin_class_columns.py
"""

import os
import sys
import psycopg2
from dotenv import load_dotenv

load_dotenv()
url = os.getenv("DATABASE_URL")
if not url:
    sys.exit("DATABASE_URL not found in .env file.")

conn = psycopg2.connect(url, connect_timeout=15)
conn.autocommit = False
cur = conn.cursor()

CABIN_CLASSES = ["first", "business", "premium_economy", "economy"]

for cls in CABIN_CLASSES:
    label = f"subfleets.has_ife_{cls} / ife_type_{cls}"
    sql = f"""
    ALTER TABLE subfleets ADD COLUMN IF NOT EXISTS has_ife_{cls} BOOLEAN;
    ALTER TABLE subfleets ADD COLUMN IF NOT EXISTS ife_type_{cls} TEXT;
    ALTER TABLE subfleets DROP CONSTRAINT IF EXISTS subfleets_ife_type_{cls}_check;
    ALTER TABLE subfleets
        ADD CONSTRAINT subfleets_ife_type_{cls}_check
        CHECK (ife_type_{cls} IN ('AVOD-Seatback','Overhead','BYOD-Streaming','No-IFE'));
    """
    try:
        cur.execute(sql)
        conn.commit()
        print(f"  ✓  {label}")
    except Exception as e:
        conn.rollback()
        sys.exit(f"FATAL: {label}: {e}")

print("\nVerification:")
cur.execute("""
    select column_name, data_type from information_schema.columns
    where table_name = 'subfleets' and column_name like 'has_ife_%' or column_name like 'ife_type_%'
    order by column_name
""")
for row in cur.fetchall():
    print(" ", row)

cur.close()
conn.close()
print("\nDone.")
