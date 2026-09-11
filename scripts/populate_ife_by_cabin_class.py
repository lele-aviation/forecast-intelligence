"""
populate_ife_by_cabin_class.py
Lele Aviation Intelligence Platform — IFE-by-Cabin-Class Auto-Draft

Populates the 8 new subfleets columns added by
add_ife_by_cabin_class_columns.py (has_ife_first/ife_type_first,
..._business, ..._premium_economy, ..._economy) from AeroLOPA's raw
per-cabin-segment IFE Description text.

JOIN PATH (verified against the live DB before writing this script):
  subfleets (source='AeroLOPA', 1,511 rows)
    -- notes column reads "AeroLOPA 2026-Q2 snapshot. LOPA config: <code>.
       Loaded 2026-06-19." for every one of these rows (regex match 100%,
       zero misses) --
    -> extract lopa_config_code
    -> aerolopa_snapshot_configs, matched on
       (db_airline_id = subfleets.airline_id,
        db_aircraft_type_id = subfleets.aircraft_type_id,
        lopa_config_code = <extracted code>)
       (this 3-way match is necessary because a single airline+aircraft-type
       pair can have multiple distinct LOPA configs -- up to 18 in one case --
       so airline_id+aircraft_type_id alone is not unique)
    -> aerolopa_snapshot_cabins, matched on
       (airline_slug = configs.airline_slug, lopa_config_code = configs.lopa_config_code)
       giving 1 row per cabin_type_code present in that config (confirmed:
       zero configs have more than one row for the same cabin_type_code).

CLASSIFICATION of the free-text ife_description into the existing
('AVOD-Seatback','Overhead','BYOD-Streaming','No-IFE') taxonomy
(same 4 values already used by subfleets.ife_type):
  - NULL description                                  -> No-IFE / has_ife=False
  - mentions overhead / drop down / communal           -> Overhead
  - mentions "personal device" / "personal electronic
    device" / "your own device" / "BYOD"                -> BYOD-Streaming
  - everything else (named system + "on demand" / "gate
    to gate" / "screening" etc., the large majority)     -> AVOD-Seatback
Dry-run against all 254 distinct description strings + the full 2,755-row
cabin table produced a sane distribution (no embarrassing surprises) before
this script was written: First 70/78 cabins AVOD, Business 480/805 some-IFE,
Premium Economy 197/252, Economy 501/1,298 (i.e. >half of economy cabins
across all AeroLOPA-covered aircraft have no IFE at all, which matches
general industry expectation -- short-haul/regional economy is the segment
least likely to carry IFE).

Cabin classes with NO row for that config (e.g. an aircraft with no First
cabin at all) are left NULL/NULL -- "not covered," not "confirmed false."
Manual-source subfleets (2,120 rows) are untouched -- all 8 columns stay
NULL, exactly like the original has_ife/ife_type pair for these rows.

Idempotent: bulk UPDATE by subfleet id, safe to re-run.

RUN:  python populate_ife_by_cabin_class.py
"""

import os
import re
import sys
import collections
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

load_dotenv()
url = os.getenv("DATABASE_URL")
if not url:
    sys.exit("DATABASE_URL not found in .env file.")

CABIN_CODE_TO_COLUMN_SUFFIX = {
    "F": "first",
    "J": "business",
    "W": "premium_economy",
    "M": "economy",
}


def classify(description):
    """Map a raw AeroLOPA IFE Description string to the 4-value taxonomy.
    Returns (has_ife, ife_type)."""
    if description is None:
        return False, "No-IFE"
    t = description.lower()
    if "overhead" in t or "drop down" in t or "drop-down" in t or "communal" in t:
        return True, "Overhead"
    if ("personal device" in t or "personal electronic device" in t
            or "your own device" in t or "byod" in t):
        return True, "BYOD-Streaming"
    return True, "AVOD-Seatback"


conn = psycopg2.connect(url, connect_timeout=15)
conn.autocommit = False
cur = conn.cursor()

print("1. Reading AeroLOPA-source subfleets + extracting LOPA config codes...")
cur.execute("""
    select id, airline_id, aircraft_type_id, notes
    from subfleets
    where source = 'AeroLOPA'
""")
subfleet_rows = cur.fetchall()
print(f"   {len(subfleet_rows)} AeroLOPA-source subfleets.")

code_re = re.compile(r"LOPA config:\s*(\S+)\.")
subfleet_codes = {}  # subfleet_id -> (airline_id, aircraft_type_id, lopa_config_code)
no_match = []
for sid, airline_id, aircraft_type_id, notes in subfleet_rows:
    m = code_re.search(notes or "")
    if not m:
        no_match.append(sid)
        continue
    subfleet_codes[sid] = (airline_id, aircraft_type_id, m.group(1))

if no_match:
    sys.exit(f"FATAL: {len(no_match)} AeroLOPA-source subfleets had no LOPA config code in notes: {no_match[:10]}")
print(f"   {len(subfleet_codes)} config codes extracted, zero misses.\n")

print("2. Resolving each subfleet to its (airline_slug, lopa_config_code) via aerolopa_snapshot_configs...")
cur.execute("""
    select db_airline_id, db_aircraft_type_id, lopa_config_code, airline_slug
    from aerolopa_snapshot_configs
    where db_airline_id is not null and db_aircraft_type_id is not null
""")
config_lookup = {}  # (airline_id, aircraft_type_id, lopa_config_code) -> airline_slug
dupe_keys = set()
for db_airline_id, db_aircraft_type_id, lopa_config_code, airline_slug in cur.fetchall():
    key = (db_airline_id, db_aircraft_type_id, lopa_config_code)
    if key in config_lookup:
        dupe_keys.add(key)
    config_lookup[key] = airline_slug
if dupe_keys:
    print(f"   WARNING: {len(dupe_keys)} (airline,aircraft,config) keys had >1 config row -- last one wins: {list(dupe_keys)[:5]}")

subfleet_to_slug_code = {}
unresolved = []
for sid, (airline_id, aircraft_type_id, code) in subfleet_codes.items():
    key = (airline_id, aircraft_type_id, code)
    if key not in config_lookup:
        unresolved.append(sid)
        continue
    subfleet_to_slug_code[sid] = (config_lookup[key], code)

print(f"   {len(subfleet_to_slug_code)} resolved, {len(unresolved)} unresolved (left untouched, same as today's NULLs).\n")

print("3. Reading per-cabin IFE Description rows from aerolopa_snapshot_cabins...")
cur.execute("""
    select airline_slug, lopa_config_code, cabin_type_code, ife_description
    from aerolopa_snapshot_cabins
    where cabin_type_code in ('F','J','W','M')
""")
cabin_lookup = collections.defaultdict(dict)  # (airline_slug, lopa_config_code) -> {cabin_type_code: ife_description}
for airline_slug, lopa_config_code, cabin_type_code, ife_description in cur.fetchall():
    cabin_lookup[(airline_slug, lopa_config_code)][cabin_type_code] = ife_description
print(f"   {len(cabin_lookup)} distinct (airline_slug, lopa_config_code) configs with cabin data.\n")

print("4. Classifying and building per-class update lists...")
updates = {suffix: [] for suffix in CABIN_CODE_TO_COLUMN_SUFFIX.values()}
covered_count = collections.Counter()
for sid, (airline_slug, code) in subfleet_to_slug_code.items():
    cabins = cabin_lookup.get((airline_slug, code))
    if not cabins:
        continue
    for cabin_code, suffix in CABIN_CODE_TO_COLUMN_SUFFIX.items():
        if cabin_code not in cabins:
            continue  # no seats of this type in this config -- leave NULL/NULL
        has_ife, ife_type = classify(cabins[cabin_code])
        updates[suffix].append((sid, has_ife, ife_type))
        covered_count[suffix] += 1

print("   Rows to be set per cabin class (covered by AeroLOPA):")
for suffix, rows in updates.items():
    true_count = sum(1 for _, h, _ in rows if h)
    print(f"     {suffix:18s}: {len(rows):4d} rows ({true_count} has_ife=True, {len(rows)-true_count} has_ife=False)")
print()

print("5. Applying bulk updates (one execute_values statement per cabin class)...")
for suffix, rows in updates.items():
    if not rows:
        continue
    execute_values(
        cur,
        f"UPDATE subfleets AS s SET has_ife_{suffix} = v.has_ife, ife_type_{suffix} = v.ife_type "
        f"FROM (VALUES %s) AS v(id, has_ife, ife_type) WHERE s.id = v.id",
        rows,
    )
conn.commit()
print("   Done.\n")

print("6. Verification:")
for suffix in CABIN_CODE_TO_COLUMN_SUFFIX.values():
    cur.execute(f"""
        select ife_type_{suffix}, count(*) from subfleets
        where has_ife_{suffix} is not null
        group by 1 order by 2 desc
    """)
    print(f"   {suffix}: {cur.fetchall()}")

cur.execute("""
    select count(*) from subfleets
    where has_ife_first is null and has_ife_business is null
      and has_ife_premium_economy is null and has_ife_economy is null
""")
print(f"\n   Subfleets with all 4 classes still NULL (uncovered/manual): {cur.fetchone()[0]} / {len(subfleet_rows) + 2120}")

cur.close()
conn.close()
print("\nDone.")
