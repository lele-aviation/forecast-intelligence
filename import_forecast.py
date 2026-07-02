"""
import_forecast.py
Lele Aviation Intelligence Platform — Forecast Data Importer

Imports one forecast vintage at a time into:
  subfleets       — one row per airline × aircraft model (seat config)
  forecast_master — one row per airline × subfleet × year
  forecast_spend  — one row per forecast_master row (all spend columns)

USAGE:
  python import_forecast.py 2026   # imports 2026_Forecast (default)
  python import_forecast.py 2024   # imports 2024_Forecast
  python import_forecast.py 2022   # imports 2022_Forecast
"""

import os, sys
import psycopg2
from psycopg2.extras import execute_values
import pandas as pd
import numpy as np
from dotenv import load_dotenv

load_dotenv()
BASE        = os.path.dirname(os.path.abspath(__file__))
SOURCE_DATA = os.path.join(os.path.dirname(BASE), 'source_data')   # Forecast Files/source_data/
VINTAGE = sys.argv[1] if len(sys.argv) > 1 else '2026'

# ── File config per vintage ────────────────────────────────────────────────
FILE_CONFIG = {
    '2026': dict(
        path   = '26-35 forecast_data.xlsx',
        sheet  = 'RAW_licensed',
        engine = 'openpyxl',
        header = 0,
        version_name = '2026_Forecast',
    ),
    '2024': dict(
        path   = '24-34 Interiors Forecast May 25 (version 1).xlsx',
        sheet  = 'Interiors MRO Forecast',
        engine = 'openpyxl',
        header = 0,
        version_name = '2024_Forecast',
    ),
    '2022': dict(
        path   = '2022-2032 Air Transport Seat and Interiors MRO-Refurb Forecast Output 23Oct2023 (1).xlsb',
        sheet  = 'Interiors MRO Forecast',
        engine = 'pyxlsb',
        header = 1,
        version_name = '2022_Forecast',
    ),
}

if VINTAGE not in FILE_CONFIG:
    sys.exit(f"Unknown vintage '{VINTAGE}'. Use 2022, 2024, or 2026.")

cfg = FILE_CONFIG[VINTAGE]
print(f"Importing {cfg['version_name']} …\n")

# ── Connect ────────────────────────────────────────────────────────────────
conn = psycopg2.connect(os.getenv("DATABASE_URL"), connect_timeout=15)
conn.autocommit = False
cur  = conn.cursor()
print("Connected.")

# ── Column mapping: Excel → database ──────────────────────────────────────
# Maps Excel column names to forecast_spend DB column names.
# Columns not listed here are skipped (subtotals we calculate ourselves).
SPEND_MAP = {
    'New Recliner First Seats $':           'new_first_recliner_seats',
    'New Lie-Flat First Seats $':           'new_first_lieflat_seats',
    'New Domestic First Seats $':           'new_domestic_first_seats',
    'New Recliner J Seats $':               'new_j_recliner_seats',
    'New Lie-Flat J Seats $':               'new_j_lieflat_seats',
    'New Y+ Seats $':                       'new_economy_plus_seats',
    'New Y Seats $':                        'new_economy_seats',
    'Total New Seats $':                    'total_new_seats',
    'Economy Seats Replace $':              'economy_seats_replace',
    'Economy Seats Repair/Ovhl $':          'economy_seats_repair',
    'True PY Seats Replace $':              'py_seats_replace',
    'True PY Seats Repair/Ovhl $':          'py_seats_repair',
    'Business Class Seats Replace $':       'business_seats_replace',
    'Business Class Seats Repair/Ovhl $':   'business_seats_repair',
    'Dom. First Class Seats Replace $':     'dom_first_seats_replace',
    'Dom. First Class Seats Repair/Ovhl $': 'dom_first_seats_repair',
    'First Class Seats Replace $':          'first_seats_replace',
    'First Class Seats Repair/Ovhl $':      'first_seats_repair',
    'Total Seats Replace $':                'total_seats_replace',
    'Total Seats Repair/Ovhl $':            'total_seats_repair',
    'Carpets Replace $':                    'carpets_replace',
    'Carpets Repair/Ovhl $':                'carpets_repair',
    'Flooring Replace $':                   'flooring_replace',
    'Flooring Repair/Ovhl $':              'flooring_repair',
    'Curtains Replace $':                   'curtains_replace',
    'Curtains Repair/Ovhl $':              'curtains_repair',
    'Seat Covers (Economy) Replace $':      'seat_covers_economy_replace',
    'Seat Covers (Economy) Repair/Ovhl $':  'seat_covers_economy_repair',
    'Seat Covers (Business) Replace $':     'seat_covers_business_replace',
    'Seat Covers (Business) Repair/Ovhl $': 'seat_covers_business_repair',
    'Seat Covers (Domestic First) Replace $':     'seat_covers_dom_first_replace',
    'Seat Covers (Domestic First) Repair/Ovhl $': 'seat_covers_dom_first_repair',
    'Seat Covers (First) Replace $':        'seat_covers_first_replace',
    'Seat Covers (First) Repair/Ovhl $':    'seat_covers_first_repair',
    'Seat Cushions (Economy) Replace $':    'seat_cushions_economy_replace',
    'Seat Cushions (Economy) Repair/Ovhl $':'seat_cushions_economy_repair',
    'Seat Cushions (Business) Replace $':   'seat_cushions_business_replace',
    'Seat Cushions (Business) Repair/Ovhl $':'seat_cushions_business_repair',
    'Seat Cushions (Domestic First) Replace $':     'seat_cushions_dom_first_replace',
    'Seat Cushions (Domestic First) Repair/Ovhl $': 'seat_cushions_dom_first_repair',
    'Seat Cushions (First) Replace $':      'seat_cushions_first_replace',
    'Seat Cushions (First) Repair/Ovhl $':  'seat_cushions_first_repair',
    'Cut & Sew (Economy) Replace $':        'cut_sew_economy_replace',
    'Cut & Sew (Business) Replace $':       'cut_sew_business_replace',
    'Cut & Sew (Domestic First) Replace $': 'cut_sew_dom_first_replace',
    'Cut & Sew (First) Replace $':          'cut_sew_first_replace',
    'Total Soft Goods Replace $':           'total_soft_goods_replace',
    'Total Soft Goods Repair/Ovhl $':       'total_soft_goods_repair',
    'Seat Belts (Flight Crew) Replace $':   'seatbelts_flight_crew_replace',
    'Seat Belts (Flight Crew) Repair/Ovhl $':'seatbelts_flight_crew_repair',
    'Seat Belts (Standard) Replace $':      'seatbelts_standard_replace',
    'Seat Belts (Standard) Repair/Ovhl $':  'seatbelts_standard_repair',
    'Seat Belts (Regulatory) Replace $':    'seatbelts_regulatory_replace',
    'Total Seat Belts Replace $':           'total_seatbelts_replace',
    'Total Seat Belts Repair/Ovhl $':       'total_seatbelts_repair',
    'Lavatories Replace $':                 'lavatories_replace',
    'Lavatories Repair/Ovhl $':            'lavatories_repair',
    'Laminates Replace $':                  'laminates_replace',
    'Laminates Repair/Ovhl $':             'laminates_repair',
    'Panels (Ceiling) Replace $':           'panels_ceiling_replace',
    'Panels (Ceiling) Repair/Ovhl $':       'panels_ceiling_repair',
    'Panels (Sidewalls) Replace $':         'panels_sidewalls_replace',
    'Panels (Sidewalls) Repair/Ovhl $':     'panels_sidewalls_repair',
    'Panels (Overhead Bins) Replace $':     'panels_overhead_bins_replace',
    'Panels (Overhead Bins) Repair/Ovhl $': 'panels_overhead_bins_repair',
    'Panels (Latches) Replace $':           'panels_latches_replace',
    'Panels (Latches) Repair/Ovhl $':       'panels_latches_repair',
    'Panels (Window Shades) Replace $':     'panels_window_shades_replace',
    'Panels (Window Shades) Repair/Ovhl $': 'panels_window_shades_repair',
    'Total Panels Replace $':               'total_panels_replace',
    'Total Panels Repair/Ovhl $':           'total_panels_repair',
    'Galleys Replace $':                    'galleys_replace',
    'Galleys Repair/Ovhl $':               'galleys_repair',
    'Ovens Replace $':                      'ovens_replace',
    'Ovens Repair/Ovhl $':                 'ovens_repair',
    'Coffee/Beverage Makers Replace $':     'coffee_makers_replace',
    'Coffee/Beverage Makers Repair/Ovhl $': 'coffee_makers_repair',
    'Carts Replace $':                      'carts_replace',
    'Carts Repair/Ovhl $':                 'carts_repair',
    'Chillers Replace $':                   'chillers_replace',
    'Chillers Repair/Ovhl $':              'chillers_repair',
    'Liquid Chillers Replace $':            'liquid_chillers_replace',
    'Liquid Chillers Repair/Ovhl $':        'liquid_chillers_repair',
    'Total Galley Inserts Replace $':       'total_galley_inserts_replace',
    'Total Galley Inserts Repair/Ovhl $':   'total_galley_inserts_repair',
    'Stowage/Closets Replace $':            'stowage_closets_replace',
    'Stowage/Closets Repair/Ovhl $':        'stowage_closets_repair',
    'Overhead Lighting Replace $':          'overhead_lighting_replace',
    'Overhead Lighting Repair/Ovhl $':      'overhead_lighting_repair',
    'IFEC Replace $':                       'ifec_replace',
    'IFEC Repair/Ovhl $':                  'ifec_repair',
    'Engineering / Certification Replace $':'engineering_certification',
    'Misc Parts Kits Replace $':            'misc_parts_kits',
    'Total Replace $ w/o soft goods':       'total_replace_excl_softgoods',
    'Total Replace $ w/ Soft Goods':        'total_replace_incl_softgoods',
    'Total Repair/Ovhl $':                  'total_repair',
    'Total $':                              'total_spend',
}

def val(x):
    """Convert NaN/None to 0.0 for numeric spend columns."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return 0.0
    return float(x)

# ── Load reference lookups ─────────────────────────────────────────────────
print("Loading reference lookups …")

# Airline name → id (direct names + aliases)
cur.execute("SELECT name, id FROM airlines")
airline_by_name = {r[0]: r[1] for r in cur.fetchall()}

cur.execute("SELECT source_name, canonical_airline_id FROM airline_name_map")
for r in cur.fetchall():
    airline_by_name.setdefault(r[0], r[1])

# Aircraft model → id
cur.execute("SELECT model, id FROM aircraft_types")
aircraft_by_model = {r[0]: r[1] for r in cur.fetchall()}

# Forecast version id
cur.execute("SELECT id FROM forecast_versions WHERE name = %s", (cfg['version_name'],))
row = cur.fetchone()
if not row:
    sys.exit(f"Forecast version '{cfg['version_name']}' not found in DB.")
version_id = row[0]
print(f"  Version id: {version_id}")

# ── Load Excel file ────────────────────────────────────────────────────────
print(f"Reading {cfg['path']} …")
df = pd.read_excel(
    os.path.join(SOURCE_DATA, cfg['path']),
    sheet_name=cfg['sheet'],
    engine=cfg['engine'],
    header=cfg['header'],
)
df['Operator']       = df['Operator'].astype(str).str.strip()
df['Aircraft Model'] = df['Aircraft Model'].astype(str).str.strip()
print(f"  {len(df):,} rows, {len(df.columns)} columns")

# ── STEP 1: Create subfleets ───────────────────────────────────────────────
# One subfleet per unique airline × aircraft model combination.
# Seat counts come from the first year's data for that combination
# (seats/ac don't change year-to-year in this model — they're a config property).
print("\nStep 1 — Creating subfleets …")

seat_cols = {
    'Recliner First Seats/AC': 'seats_first_recliner',
    'Lie-Flat First Seats/AC': 'seats_first_lieflat',
    'Domestic First Seats/AC': 'seats_domestic_first',
    'Recliner J Seats/AC':     'seats_j_recliner',
    'Lie-Flat J Seats/AC':     'seats_j_lieflat',
    'True Y+ Seats/AC':        'seats_premium_economy',
    'Y+ Seats/AC':             'seats_economy_plus',
    'Y Seats/AC':              'seats_economy',
    'Seats/AC':                'seats_total',
}

# Take first occurrence per airline × model (representative config)
first_occ = df.groupby(['Operator','Aircraft Model']).first().reset_index()

subfleet_rows  = []
missing_airline = set()
missing_aircraft = set()

for _, row in first_occ.iterrows():
    op_name  = row['Operator']
    model    = row['Aircraft Model']

    airline_id = airline_by_name.get(op_name)
    if not airline_id:
        missing_airline.add(op_name)
        continue

    aircraft_id = aircraft_by_model.get(model)
    if not aircraft_id:
        missing_aircraft.add(model)
        continue

    seats = {db_col: int(val(row.get(xl_col, 0)))
             for xl_col, db_col in seat_cols.items()
             if xl_col in df.columns}

    subfleet_rows.append((
        airline_id, aircraft_id, 'Standard',
        seats.get('seats_first_recliner', 0),
        seats.get('seats_first_lieflat',  0),
        seats.get('seats_domestic_first', 0),
        seats.get('seats_j_recliner',     0),
        seats.get('seats_j_lieflat',      0),
        seats.get('seats_premium_economy',0),
        seats.get('seats_economy_plus',   0),
        seats.get('seats_economy',        0),
        seats.get('seats_total',          0),
        'Manual', f"{cfg['version_name'][:4]}-01-01",  # source, last_updated
    ))

if missing_airline:
    print(f"  WARN: {len(missing_airline)} operators not found in airlines table")
    for n in sorted(missing_airline)[:10]:
        print(f"    – {n}")
    if len(missing_airline) > 10:
        print(f"    … and {len(missing_airline)-10} more")

if missing_aircraft:
    print(f"  WARN: {len(missing_aircraft)} aircraft models not found")
    for m in sorted(missing_aircraft)[:5]:
        print(f"    – {m}")

# Deduplicate — multiple operator name variants may resolve to same airline_id
seen_sf = set()
deduped = []
for r in subfleet_rows:
    key = (r[0], r[1])  # (airline_id, aircraft_type_id)
    if key not in seen_sf:
        seen_sf.add(key)
        deduped.append(r)
subfleet_rows = deduped

execute_values(cur, """
    INSERT INTO subfleets
        (airline_id, aircraft_type_id, subfleet_name,
         seats_first_recliner, seats_first_lieflat, seats_domestic_first,
         seats_j_recliner, seats_j_lieflat, seats_premium_economy,
         seats_economy_plus, seats_economy, seats_total,
         source, last_updated)
    VALUES %s
    ON CONFLICT (airline_id, aircraft_type_id, subfleet_name) DO UPDATE SET
        seats_first_recliner  = EXCLUDED.seats_first_recliner,
        seats_first_lieflat   = EXCLUDED.seats_first_lieflat,
        seats_domestic_first  = EXCLUDED.seats_domestic_first,
        seats_j_recliner      = EXCLUDED.seats_j_recliner,
        seats_j_lieflat       = EXCLUDED.seats_j_lieflat,
        seats_premium_economy = EXCLUDED.seats_premium_economy,
        seats_economy_plus    = EXCLUDED.seats_economy_plus,
        seats_economy         = EXCLUDED.seats_economy,
        seats_total           = EXCLUDED.seats_total,
        last_updated          = EXCLUDED.last_updated
""", subfleet_rows)
conn.commit()

# Build subfleet lookup: (airline_id, aircraft_type_id) → subfleet_id
cur.execute("SELECT id, airline_id, aircraft_type_id FROM subfleets WHERE subfleet_name = 'Standard'")
subfleet_lookup = {(r[1], r[2]): r[0] for r in cur.fetchall()}
print(f"  {len(subfleet_rows):,} subfleets created/updated")


# ── STEP 2: Import forecast_master ────────────────────────────────────────
print("\nStep 2 — Importing forecast_master …")

master_rows   = []
skipped_rows  = 0
seen_master   = set()  # dedup key: (airline_id, subfleet_id, year)
master_id_map = {}  # (operator, model, year) → master_id (populated after insert)

for _, row in df.iterrows():
    op_name  = str(row['Operator']).strip()
    model    = str(row['Aircraft Model']).strip()
    year     = int(row['Year']) if pd.notna(row.get('Year')) else None

    airline_id  = airline_by_name.get(op_name)
    aircraft_id = aircraft_by_model.get(model)
    if not airline_id or not aircraft_id:
        skipped_rows += 1
        continue

    subfleet_id = subfleet_lookup.get((airline_id, aircraft_id))
    if not subfleet_id:
        skipped_rows += 1
        continue

    master_key = (airline_id, subfleet_id, year)
    if master_key in seen_master:
        skipped_rows += 1
        continue
    seen_master.add(master_key)

    avg_age = val(row.get('Avg Age')) if 'Avg Age' in df.columns else None

    master_rows.append((
        version_id, airline_id, subfleet_id, year,
        val(row.get('Fleet',0)),
        val(row.get('Deliveries',0)),
        avg_age,
        val(row.get('Retrofit Interval Adjustment', 1)),
        val(row.get('Repair Interval Adjustment',   0)),
        val(row.get('Repair Interval Adjustment V2',0)),
        str(row.get('Seat Data Source', '')) or None,
        op_name, model, year,   # stored temporarily for id retrieval
    ))

# Insert in batches of 500 for reliability
BATCH = 500
total_master = 0
for i in range(0, len(master_rows), BATCH):
    batch = master_rows[i:i+BATCH]
    execute_values(cur, """
        INSERT INTO forecast_master
            (forecast_version_id, airline_id, subfleet_id, year,
             fleet_count, deliveries, avg_age,
             retrofit_interval_adj, repair_interval_adj, repair_interval_adj_v2,
             seat_data_source)
        VALUES %s
        ON CONFLICT (forecast_version_id, airline_id, subfleet_id, year)
        DO UPDATE SET
            fleet_count           = EXCLUDED.fleet_count,
            deliveries            = EXCLUDED.deliveries,
            avg_age               = EXCLUDED.avg_age,
            retrofit_interval_adj = EXCLUDED.retrofit_interval_adj,
            repair_interval_adj   = EXCLUDED.repair_interval_adj
    """, [r[:11] for r in batch])
    conn.commit()
    total_master += len(batch)
    print(f"  master rows inserted: {total_master:,}", end='\r')

print(f"\n  {total_master:,} forecast_master rows inserted ({skipped_rows} skipped)")
# Deduplicate spend rows too — same root cause
seen_sp_keys = set()
deduped_spend = []

# Build master_id lookup: (airline_id, subfleet_id, year) → master_id
cur.execute("""
    SELECT id, airline_id, subfleet_id, year
    FROM forecast_master
    WHERE forecast_version_id = %s
""", (version_id,))
master_lookup = {(r[1], r[2], r[3]): r[0] for r in cur.fetchall()}
print(f"  {len(master_lookup):,} master rows indexed")


# ── STEP 3: Import forecast_spend ─────────────────────────────────────────
print("\nStep 3 — Importing forecast_spend …")

# Only map columns that actually exist in this file
active_map = {xl: db for xl, db in SPEND_MAP.items() if xl in df.columns}
db_cols    = list(active_map.values())
print(f"  Mapping {len(active_map)} spend columns")

spend_rows   = []
skipped_sp   = 0
seen_spend   = set()  # deduplicate by master_id

for _, row in df.iterrows():
    op_name  = str(row['Operator']).strip()
    model    = str(row['Aircraft Model']).strip()
    year     = int(row['Year']) if pd.notna(row.get('Year')) else None

    airline_id  = airline_by_name.get(op_name)
    aircraft_id = aircraft_by_model.get(model)
    if not airline_id or not aircraft_id:
        skipped_sp += 1
        continue

    subfleet_id = subfleet_lookup.get((airline_id, aircraft_id))
    if not subfleet_id:
        skipped_sp += 1
        continue

    master_id = master_lookup.get((airline_id, subfleet_id, year))
    if not master_id:
        skipped_sp += 1
        continue

    if master_id in seen_spend:
        skipped_sp += 1
        continue
    seen_spend.add(master_id)

    spend_vals = [val(row.get(xl)) for xl in active_map.keys()]
    spend_rows.append(tuple([master_id] + spend_vals))

cols_sql = ', '.join(db_cols)
placeholders = ', '.join(['%s'] * (len(db_cols) + 1))

total_spend = 0
for i in range(0, len(spend_rows), BATCH):
    batch = spend_rows[i:i+BATCH]
    execute_values(cur, f"""
        INSERT INTO forecast_spend (master_id, {cols_sql})
        VALUES %s
        ON CONFLICT (master_id) DO UPDATE SET
            total_spend = EXCLUDED.total_spend,
            total_repair = EXCLUDED.total_repair,
            total_replace_incl_softgoods = EXCLUDED.total_replace_incl_softgoods
    """, batch)
    conn.commit()
    total_spend += len(batch)
    print(f"  spend rows inserted: {total_spend:,}", end='\r')

print(f"\n  {total_spend:,} forecast_spend rows inserted ({skipped_sp} skipped)")


# ── VERIFICATION ──────────────────────────────────────────────────────────
print("\n── Verification ──────────────────────────────────────────────────────")
cur.execute("SELECT COUNT(*) FROM subfleets")
print(f"  subfleets total:        {cur.fetchone()[0]:>7,}")

cur.execute("SELECT COUNT(*) FROM forecast_master WHERE forecast_version_id = %s", (version_id,))
print(f"  forecast_master rows:   {cur.fetchone()[0]:>7,}")

cur.execute("""
    SELECT COUNT(*) FROM forecast_spend fs
    JOIN forecast_master fm ON fs.master_id = fm.id
    WHERE fm.forecast_version_id = %s
""", (version_id,))
print(f"  forecast_spend rows:    {cur.fetchone()[0]:>7,}")

# Quick sanity check — total spend by region for 2030
print()
cur.execute("""
    SELECT a.region,
           ROUND(SUM(fs.total_spend)/1e6, 1) AS spend_m
    FROM forecast_master fm
    JOIN airlines a        ON fm.airline_id = a.id
    JOIN forecast_spend fs ON fs.master_id  = fm.id
    WHERE fm.forecast_version_id = %s AND fm.year = 2030
    GROUP BY a.region
    ORDER BY spend_m DESC
""", (version_id,))
rows = cur.fetchall()
print(f"  2030 total spend by region (${cfg['version_name']}):")
for r in rows:
    print(f"    {r[0] or 'Unknown':<20} ${r[1]:>8,.1f}m")

cur.close()
conn.close()
print(f"\nDone — {cfg['version_name']} imported.")
