"""
add_turboprop_pricing.py
Lele Aviation Intelligence Platform — Turboprop Pricing Backfill

Closes the long-standing "Turboprop subfleets have no pricing assumptions"
gap flagged in 04_Import_Guide / ARCHITECTURE.md Part 7. Jon had already
added these 72 rows manually to his own copy of 03_Pricing_Reference;
this script:

  1. Widens the assumptions.aircraft_size_class CHECK constraint to allow
     'Turboprop' (previously Regional/Narrowbody/Widebody only -- this is
     why these rows could never have lived in the DB before now).
  2. Inserts the 72 Turboprop rows (24 product codes x New/Repair/Replace,
     except eng_cert which is per_program x Large/Medium/Small) sourced
     from Jon's file, with one correction: rows for the 'Monuments'
     product (New/Repair/Replace) had product_code typo'd as 'tue'/'wed'/
     'thu' in his file (an apparent autofill slip) -- corrected to 'mon'
     here, matching the existing Narrowbody/Regional/Widebody Monuments
     rows and satisfying the product_catalog FK.

Idempotent: safe to re-run (ON CONFLICT DO NOTHING on the existing unique
constraint; constraint swap uses DROP/ADD IF EXISTS).

RUN:  python add_turboprop_pricing.py
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

print("1. Widening assumptions_aircraft_size_class_check to include 'Turboprop'...")
cur.execute("""
    ALTER TABLE assumptions DROP CONSTRAINT IF EXISTS assumptions_aircraft_size_class_check;
    ALTER TABLE assumptions ADD CONSTRAINT assumptions_aircraft_size_class_check
        CHECK (aircraft_size_class = ANY (ARRAY['Regional','Narrowbody','Widebody','Turboprop']));
""")
conn.commit()
print("   done.\n")

# (product_code, service_type, mod_size, base_cost, escalation_rate)
TURBOPROP_ROWS = [
    ("eng_cert", "Replace", "Large", 1000000, 0.04),
    ("eng_cert", "Replace", "Medium", 150000, 0.04),
    ("eng_cert", "Replace", "Small", 40000, 0.04),

    ("carp", "New", None, 17500, 0.03),
    ("carp", "Repair", None, 3000, 0.03),
    ("carp", "Replace", None, 25000, 0.03),

    ("floor_ntf", "New", None, 20000, 0.03),
    ("floor_ntf", "Repair", None, 1000, 0.03),
    ("floor_ntf", "Replace", None, 25000, 0.03),

    ("gal", "New", None, 125000, 0.03),
    ("gal", "Repair", None, 7500, 0.03),
    ("gal", "Replace", None, 300000, 0.03),

    ("gal_bin", "New", None, 2500, 0.03),
    ("gal_bin", "Repair", None, 50, 0.03),
    ("gal_bin", "Replace", None, 5000, 0.03),

    ("gal_cart", "New", None, 6000, 0.03),
    ("gal_cart", "Repair", None, 75, 0.03),
    ("gal_cart", "Replace", None, 9000, 0.03),

    ("gal_chil_air", "New", None, 0, 0.03),
    ("gal_chil_air", "Repair", None, 0, 0.03),
    ("gal_chil_air", "Replace", None, 0, 0.03),

    ("gal_chil_liq", "New", None, 0, 0.03),
    ("gal_chil_liq", "Repair", None, 0, 0.03),
    ("gal_chil_liq", "Replace", None, 0, 0.03),

    ("gal_ins_cof", "New", None, 15000, 0.03),
    ("gal_ins_cof", "Repair", None, 1500, 0.03),
    ("gal_ins_cof", "Replace", None, 20000, 0.03),

    ("gal_ins_oven", "New", None, 0, 0.03),
    ("gal_ins_oven", "Repair", None, 0, 0.03),
    ("gal_ins_oven", "Replace", None, 0, 0.03),

    ("gal_ins_wh", "New", None, 10000, 0.03),
    ("gal_ins_wh", "Repair", None, 1000, 0.03),
    ("gal_ins_wh", "Replace", None, 20000, 0.03),

    ("conn", "New", None, 0, 0.02),
    ("conn", "Repair", None, 0, 0.02),
    ("conn", "Replace", None, 0, 0.02),

    ("div", "New", None, 0, 0.03),
    ("div", "Repair", None, 0, 0.03),
    ("div", "Replace", None, 0, 0.03),

    ("gal_bins_ovhd", "New", None, 175000, 0.03),
    ("gal_bins_ovhd", "Repair", None, 10000, 0.03),
    ("gal_bins_ovhd", "Replace", None, 250000, 0.03),

    ("lam", "New", None, 50000, 0.03),
    ("lam", "Repair", None, 10000, 0.03),
    ("lam", "Replace", None, 75000, 0.03),

    ("lav", "New", None, 100000, 0.03),
    ("lav", "Repair", None, 10000, 0.03),
    ("lav", "Replace", None, 150000, 0.03),

    # Source file had these typo'd as 'tue'/'wed'/'thu' -- corrected to 'mon'.
    ("mon", "New", None, 50000, 0.03),
    ("mon", "Repair", None, 5000, 0.03),
    ("mon", "Replace", None, 75000, 0.03),

    ("pan_ceil", "New", None, 150000, 0.03),
    ("pan_ceil", "Repair", None, 2000, 0.03),
    ("pan_ceil", "Replace", None, 225000, 0.03),

    ("pan_side", "New", None, 275000, 0.03),
    ("pan_side", "Repair", None, 4000, 0.03),
    ("pan_side", "Replace", None, 350000, 0.03),

    ("win_shade_elec", "New", None, 0, 0.03),
    ("win_shade_elec", "Repair", None, 0, 0.03),
    ("win_shade_elec", "Replace", None, 0, 0.03),

    ("win_shade_man", "New", None, 35000, 0.03),
    ("win_shade_man", "Repair", None, 5000, 0.03),
    ("win_shade_man", "Replace", None, 60000, 0.03),

    ("light_cab", "New", None, 50000, 0.03),
    ("light_cab", "Repair", None, 2500, 0.03),
    ("light_cab", "Replace", None, 75000, 0.03),

    ("light_seat", "New", None, 10000, 0.03),
    ("light_seat", "Repair", None, 2000, 0.03),
    ("light_seat", "Replace", None, 15000, 0.03),

    ("curt", "New", None, 5000, 0.03),
    ("curt", "Repair", None, 250, 0.03),
    ("curt", "Replace", None, 8000, 0.03),
]

assert len(TURBOPROP_ROWS) == 72, f"expected 72 rows, got {len(TURBOPROP_ROWS)}"

print(f"2. Inserting {len(TURBOPROP_ROWS)} Turboprop assumption rows...")
inserted = 0
for product_code, service_type, mod_size, base_cost, esc_rate in TURBOPROP_ROWS:
    cur.execute("""
        INSERT INTO assumptions
            (product_code, service_type, aircraft_size_class, mod_size,
             base_cost, escalation_rate, base_year, valid_from, is_active)
        VALUES (%s, %s, 'Turboprop', %s, %s, %s, 2026, '2026-01-01', true)
        ON CONFLICT (product_code, service_type, aircraft_size_class, mod_size, valid_from)
        DO NOTHING
    """, (product_code, service_type, mod_size, base_cost, esc_rate))
    inserted += cur.rowcount
conn.commit()
print(f"   inserted {inserted} new rows (0 = already present, re-run is idempotent).\n")

cur.execute("select aircraft_size_class, count(*) from assumptions group by aircraft_size_class order by 1")
print("3. assumptions row counts by size class:")
for row in cur.fetchall():
    print("  ", row)

cur.execute("select count(*) from assumptions where is_active = true")
print("\n   total active rows:", cur.fetchone()[0])

cur.close()
conn.close()
print("\nDone.")
