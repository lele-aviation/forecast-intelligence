"""
import_2026_forecast.py
Lele Aviation Intelligence Platform — 2026 Forecast Importer

Source:  26-35 10 year interiors forecast.xlsb  /  Interiors MRO Forecast
Targets: subfleets, forecast_master, forecast_spend

Excludes zzz_Unassigned_* operators (regional remainder buckets).
All operators and aircraft models resolve 100% via existing DB records.

RUN:  python import_2026_forecast.py
"""

import os, sys, time
import psycopg2
from psycopg2.extras import execute_values
import pandas as pd
import pyxlsb
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)               # Forecast Files/ (this script lives in scripts/)
SOURCE_DATA = os.path.join(ROOT, 'source_data')
load_dotenv(dotenv_path=os.path.join(ROOT, ".env"))

# ── Connect ────────────────────────────────────────────────────────────────
print("Connecting to Supabase...")
conn = psycopg2.connect(os.getenv("DATABASE_URL"), connect_timeout=15)
conn.autocommit = False
cur = conn.cursor()
print("  Connected.\n")

# ── Load Excel ─────────────────────────────────────────────────────────────
XLSB = os.path.join(SOURCE_DATA, "26-35 10 year interiors forecast.xlsb")
print(f"Loading {os.path.basename(XLSB)} ...")
t0 = time.time()

raw_rows = []
with pyxlsb.open_workbook(XLSB) as wb:
    with wb.get_sheet('Interiors MRO Forecast') as ws:
        for row in ws.rows():
            raw_rows.append([c.v for c in row])

df = pd.DataFrame(raw_rows[2:], columns=raw_rows[1])
df = df[df['Year'].notna()].copy()
df = df[~df['Operator'].str.startswith('zzz', na=False)].copy()
df['Year'] = df['Year'].astype(int)

print(f"  {len(df):,} rows loaded ({time.time()-t0:.1f}s)\n")

# ── Build lookup maps ──────────────────────────────────────────────────────
cur.execute("SELECT source_name, canonical_airline_id FROM airline_name_map")
name_map = {r[0]: r[1] for r in cur.fetchall()}

cur.execute("SELECT name, id FROM airlines")
for name, aid in cur.fetchall():
    if name not in name_map:
        name_map[name] = aid

cur.execute("SELECT model, id, category FROM aircraft_types")
aircraft_map = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

cur.execute("SELECT id FROM forecast_versions WHERE name = '2026_Forecast'")
row = cur.fetchone()
if not row:
    sys.exit("ERROR: '2026_Forecast' row not found in forecast_versions. Run seed_reference_tables.py first.")
version_id = row[0]

print(f"  Forecast version ID: {version_id}")
print(f"  Airlines in name_map: {len(name_map)}")
print(f"  Aircraft models: {len(aircraft_map)}\n")

# ── Step 1: Build subfleets ────────────────────────────────────────────────
# One subfleet row per airline × aircraft_type (using 2026 seat config as baseline)
# Seat data comes from the earliest year available per combo (most complete)
print("Step 1 — Building subfleets ...")

SEAT_COLS = {
    'seats_first_recliner': 'Recliner First Seats/AC',
    'seats_first_lieflat':  'Lie-Flat First Seats/AC',
    'seats_domestic_first': 'Domestic First Seats/AC',
    'seats_j_recliner':     'Recliner J Seats/AC',
    'seats_j_lieflat':      'Lie-Flat J Seats/AC',
    'seats_premium_economy':'Y+ Seats/AC',
    'seats_economy_plus':   'True Y+ Seats/AC',
    'seats_economy':        'Y Seats/AC',
    'seats_total':          'Seats/AC',
}

# Get 2026 rows only for seat baseline (seat config per AC doesn't change year to year)
base = df[df['Year'] == 2026].copy()

subfleet_rows = []
subfleet_key_to_idx = {}  # (airline_id, aircraft_type_id) -> index in subfleet_rows

for _, row in base.iterrows():
    op   = row['Operator']
    mdl  = row['Aircraft Model']
    oem  = row.get('Aircraft OEM', '')
    cat  = row.get('Aircraft Category', '')

    airline_id      = name_map.get(op)
    aircraft_info   = aircraft_map.get(mdl)
    if not airline_id or not aircraft_info:
        continue
    aircraft_type_id = aircraft_info[0]

    key = (airline_id, aircraft_type_id)
    if key in subfleet_key_to_idx:
        continue  # already added this combo

    def safe(col):
        v = row.get(col)
        try:
            f = float(v) if v is not None else 0.0
            return round(f, 4) if f == f else 0.0  # nan check
        except (TypeError, ValueError):
            return 0.0

    subfleet_rows.append((
        airline_id,
        aircraft_type_id,
        mdl,                        # subfleet_name = aircraft model (no sub-config in this data)
        safe('Recliner First Seats/AC'),
        safe('Lie-Flat First Seats/AC'),
        safe('Domestic First Seats/AC'),
        safe('Recliner J Seats/AC'),
        safe('Lie-Flat J Seats/AC'),
        safe('Y+ Seats/AC'),
        safe('True Y+ Seats/AC'),
        safe('Y Seats/AC'),
        safe('Seats/AC'),
        '2026-01-01',               # valid_from
        None,                       # valid_to
        'Manual',                   # source (check constraint: AeroLOPA/Manual/OEM)
    ))
    subfleet_key_to_idx[key] = len(subfleet_rows) - 1

SF_COLS = (
    'airline_id', 'aircraft_type_id', 'subfleet_name',
    'seats_first_recliner', 'seats_first_lieflat', 'seats_domestic_first',
    'seats_j_recliner', 'seats_j_lieflat',
    'seats_premium_economy', 'seats_economy_plus', 'seats_economy', 'seats_total',
    'valid_from', 'valid_to', 'source'
)

execute_values(
    cur,
    f"""INSERT INTO subfleets ({', '.join(SF_COLS)}) VALUES %s
        ON CONFLICT DO NOTHING""",
    subfleet_rows
)
conn.commit()
print(f"  {len(subfleet_rows):,} subfleets inserted\n")

# Reload subfleet map: (airline_id, aircraft_type_id) -> subfleet_id
cur.execute("SELECT id, airline_id, aircraft_type_id FROM subfleets")
subfleet_map = {(r[1], r[2]): r[0] for r in cur.fetchall()}

# ── Step 2: forecast_master + forecast_spend ───────────────────────────────
print("Step 2 — Building forecast_master and forecast_spend ...")

SPEND_COLS = [
    # New seats (deliveries)
    'new_first_recliner_seats', 'new_first_lieflat_seats', 'new_domestic_first_seats',
    'new_j_recliner_seats', 'new_j_lieflat_seats', 'new_economy_plus_seats',
    'new_economy_seats', 'total_new_seats',
    # Seats replace
    'economy_seats_replace', 'py_seats_replace', 'business_seats_replace',
    'dom_first_seats_replace', 'first_seats_replace', 'total_seats_replace',
    # Seats repair
    'economy_seats_repair', 'py_seats_repair', 'business_seats_repair',
    'dom_first_seats_repair', 'first_seats_repair', 'total_seats_repair',
    # Soft goods replace
    'carpets_replace', 'flooring_replace', 'curtains_replace',
    'seat_covers_economy_replace', 'seat_covers_business_replace',
    'seat_covers_dom_first_replace', 'seat_covers_first_replace',
    'seat_cushions_economy_replace', 'seat_cushions_business_replace',
    'seat_cushions_dom_first_replace', 'seat_cushions_first_replace',
    'cut_sew_economy_replace', 'cut_sew_business_replace',
    'cut_sew_dom_first_replace', 'cut_sew_first_replace',
    'total_soft_goods_replace',
    # Soft goods repair
    'carpets_repair', 'flooring_repair', 'curtains_repair',
    'seat_covers_economy_repair', 'seat_covers_business_repair',
    'seat_covers_dom_first_repair', 'seat_covers_first_repair',
    'seat_cushions_economy_repair', 'seat_cushions_business_repair',
    'seat_cushions_dom_first_repair', 'seat_cushions_first_repair',
    'total_soft_goods_repair',
    # Seat belts replace
    'seatbelts_flight_crew_replace', 'seatbelts_standard_replace',
    'seatbelts_regulatory_replace', 'total_seatbelts_replace',
    # Seat belts repair
    'seatbelts_flight_crew_repair', 'seatbelts_standard_repair',
    'total_seatbelts_repair',
    # Hard goods replace
    'lavatories_replace', 'laminates_replace',
    'panels_ceiling_replace', 'panels_sidewalls_replace', 'panels_overhead_bins_replace',
    'panels_latches_replace', 'panels_window_shades_replace', 'total_panels_replace',
    'galleys_replace',
    'ovens_replace', 'coffee_makers_replace', 'carts_replace',
    'chillers_replace', 'liquid_chillers_replace', 'total_galley_inserts_replace',
    'stowage_closets_replace', 'overhead_lighting_replace', 'ifec_replace',
    'engineering_certification', 'misc_parts_kits',
    # Hard goods repair
    'lavatories_repair', 'laminates_repair',
    'panels_ceiling_repair', 'panels_sidewalls_repair', 'panels_overhead_bins_repair',
    'panels_latches_repair', 'panels_window_shades_repair', 'total_panels_repair',
    'galleys_repair',
    'ovens_repair', 'coffee_makers_repair', 'carts_repair',
    'chillers_repair', 'liquid_chillers_repair', 'total_galley_inserts_repair',
    'stowage_closets_repair', 'overhead_lighting_repair', 'ifec_repair',
    # Totals
    'total_replace_excl_softgoods', 'total_replace_incl_softgoods',
    'total_repair', 'total_spend',
]

# Excel column → DB spend column map
EXCEL_TO_DB = {
    # New seats
    'New Recliner First Seats $':       'new_first_recliner_seats',
    'New Lie-Flat First Seats $':       'new_first_lieflat_seats',
    'New Domestic First Seats $':       'new_domestic_first_seats',
    'New Recliner J Seats $':           'new_j_recliner_seats',
    'New Lie-Flat J Seats $':           'new_j_lieflat_seats',
    'New Y+ Seats $':                   'new_economy_plus_seats',
    'New True Y+ Seats $':              'new_economy_seats',
    'New Y Seats $':                    'new_economy_seats',     # Y economy
    'Total New Seats $':                'total_new_seats',
    # Seats replace/repair
    'Economy Seats Replace $':          'economy_seats_replace',
    'Economy Seats Repair/Ovhl $':      'economy_seats_repair',
    'True PY Seats Replace $':          'py_seats_replace',
    'True PY Seats Repair/Ovhl $':      'py_seats_repair',
    'Business Class Seats Replace $':   'business_seats_replace',
    'Business Class Seats Repair/Ovhl $':'business_seats_repair',
    'Dom. First Class Seats Replace $': 'dom_first_seats_replace',
    'Dom. First Class Seats Repair/Ovhl $':'dom_first_seats_repair',
    'First Class Seats Replace $':      'first_seats_replace',
    'First Class Seats Repair/Ovhl $':  'first_seats_repair',
    'Total Seats Replace $':            'total_seats_replace',
    'Total Seats Repair/Ovhl $':        'total_seats_repair',
    # Soft goods
    'Carpets Replace $':                'carpets_replace',
    'Carpets Repair/Ovhl $':            'carpets_repair',
    'Flooring Replace $':               'flooring_replace',
    'Flooring Repair/Ovhl $':           'flooring_repair',
    'Curtains Replace $':               'curtains_replace',
    'Curtains Repair/Ovhl $':           'curtains_repair',
    'Seat Covers (Economy) Replace $':  'seat_covers_economy_replace',
    'Seat Covers (Economy) Repair/Ovhl $':'seat_covers_economy_repair',
    'Seat Covers (Business) Replace $': 'seat_covers_business_replace',
    'Seat Covers (Business) Repair/Ovhl $':'seat_covers_business_repair',
    'Seat Covers (Domestic First) Replace $':'seat_covers_dom_first_replace',
    'Seat Covers (Domestic First) Repair/Ovhl $':'seat_covers_dom_first_repair',
    'Seat Covers (First) Replace $':    'seat_covers_first_replace',
    'Seat Covers (First) Repair/Ovhl $':'seat_covers_first_repair',
    'Seat Cushions (Economy) Replace $':'seat_cushions_economy_replace',
    'Seat Cushions (Economy) Repair/Ovhl $':'seat_cushions_economy_repair',
    'Seat Cushions (Business) Replace $':'seat_cushions_business_replace',
    'Seat Cushions (Business) Repair/Ovhl $':'seat_cushions_business_repair',
    'Seat Cushions (Domestic First) Replace $':'seat_cushions_dom_first_replace',
    'Seat Cushions (Domestic First) Repair/Ovhl $':'seat_cushions_dom_first_repair',
    'Seat Cushions (First) Replace $':  'seat_cushions_first_replace',
    'Seat Cushions (First) Repair/Ovhl $':'seat_cushions_first_repair',
    'Cut & Sew (Economy) Replace $':    'cut_sew_economy_replace',
    'Cut & Sew (Business) Replace $':   'cut_sew_business_replace',
    'Cut & Sew (Domestic First) Replace $':'cut_sew_dom_first_replace',
    'Cut & Sew (First) Replace $':      'cut_sew_first_replace',
    'Total Soft Goods Replace $':       'total_soft_goods_replace',
    'Total Soft Goods Repair/Ovhl $':   'total_soft_goods_repair',
    # Seat belts
    'Seat Belts (Flight Crew) Replace $':'seatbelts_flight_crew_replace',
    'Seat Belts (Flight Crew) Repair/Ovhl $':'seatbelts_flight_crew_repair',
    'Seat Belts (Standard) Replace $':  'seatbelts_standard_replace',
    'Seat Belts (Standard) Repair/Ovhl $':'seatbelts_standard_repair',
    'Seat Belts (Regulatory) Replace $':'seatbelts_regulatory_replace',
    'Total Seat Belts Replace $':       'total_seatbelts_replace',
    'Total Seat Belts Repair/Ovhl $':   'total_seatbelts_repair',
    # Hard goods
    'Lavatories Replace $':             'lavatories_replace',
    'Lavatories Repair/Ovhl $':         'lavatories_repair',
    'Laminates Replace $':              'laminates_replace',
    'Laminates Repair/Ovhl $':          'laminates_repair',
    'Panels (Ceiling) Replace $':       'panels_ceiling_replace',
    'Panels (Ceiling) Repair/Ovhl $':   'panels_ceiling_repair',
    'Panels (Sidewalls) Replace $':     'panels_sidewalls_replace',
    'Panels (Sidewalls) Repair/Ovhl $': 'panels_sidewalls_repair',
    'Panels (Overhead Bins) Replace $': 'panels_overhead_bins_replace',
    'Panels (Overhead Bins) Repair/Ovhl $':'panels_overhead_bins_repair',
    'Panels (Latches) Replace $':       'panels_latches_replace',
    'Panels (Latches) Repair/Ovhl $':   'panels_latches_repair',
    'Panels (Window Shades) Replace $': 'panels_window_shades_replace',
    'Panels (Window Shades) Repair/Ovhl $':'panels_window_shades_repair',
    'Total Panels Replace $':           'total_panels_replace',
    'Total Panels Repair/Ovhl $':       'total_panels_repair',
    'Galleys Replace $':                'galleys_replace',
    'Galleys Repair/Ovhl $':            'galleys_repair',
    'Ovens Replace $':                  'ovens_replace',
    'Ovens Repair/Ovhl $':              'ovens_repair',
    'Coffee/Beverage Makers Replace $': 'coffee_makers_replace',
    'Coffee/Beverage Makers Repair/Ovhl $':'coffee_makers_repair',
    'Carts Replace $':                  'carts_replace',
    'Carts Repair/Ovhl $':              'carts_repair',
    'Chillers Replace $':               'chillers_replace',
    'Chillers Repair/Ovhl $':           'chillers_repair',
    'Liquid Chillers Replace $':        'liquid_chillers_replace',
    'Liquid Chillers Repair/Ovhl $':    'liquid_chillers_repair',
    'Total Galley Inserts Replace $':   'total_galley_inserts_replace',
    'Total Galley Inserts Repair/Ovhl $':'total_galley_inserts_repair',
    'Stowage/Closets Replace $':        'stowage_closets_replace',
    'Stowage/Closets Repair/Ovhl $':    'stowage_closets_repair',
    'Overhead Lighting Replace $':      'overhead_lighting_replace',
    'Overhead Lighting Repair/Ovhl $':  'overhead_lighting_repair',
    'IFEC Replace $':                   'ifec_replace',
    'IFEC Repair/Ovhl $':               'ifec_repair',
    'Engineering / Certification Replace $':'engineering_certification',
    'Misc Parts Kits Replace $':        'misc_parts_kits',
    # Totals
    'Total Replace $ w/o soft goods':   'total_replace_excl_softgoods',
    'Total Replace $ w/ Soft Goods':    'total_replace_incl_softgoods',
    'Total Repair/Ovhl $':              'total_repair',
    'Total $':                          'total_spend',
}

def to_float(v):
    try:
        f = float(v) if v is not None else 0.0
        return 0.0 if f != f else round(f, 4)  # nan → 0
    except (TypeError, ValueError):
        return 0.0

master_rows = []
spend_rows  = []
skipped     = 0

for _, row in df.iterrows():
    op  = row['Operator']
    mdl = row['Aircraft Model']

    airline_id       = name_map.get(op)
    aircraft_info    = aircraft_map.get(mdl)
    if not airline_id or not aircraft_info:
        skipped += 1
        continue
    aircraft_type_id = aircraft_info[0]

    subfleet_id = subfleet_map.get((airline_id, aircraft_type_id))
    if not subfleet_id:
        skipped += 1
        continue

    fleet_count  = to_float(row.get('Fleet'))
    deliveries   = to_float(row.get('Deliveries'))
    avg_age      = to_float(row.get('Avg Age'))
    retro_adj    = to_float(row.get('Retrofit Interval Adjustment'))
    repair_adj   = to_float(row.get('Repair Interval Adjustment'))
    repair_adj2  = to_float(row.get('Repair Interval Adjustment V2'))
    seat_src     = row.get('Seat Data Source', 'Manual') or 'Manual'

    master_rows.append((
        version_id, airline_id, subfleet_id, int(row['Year']),
        fleet_count, deliveries, avg_age,
        retro_adj, repair_adj, repair_adj2,
        seat_src, 'Medium',
    ))

    # Build spend tuple (ordered to match SPEND_COLS)
    spend = {db_col: 0.0 for db_col in SPEND_COLS}
    for excel_col, db_col in EXCEL_TO_DB.items():
        if excel_col in row.index:
            spend[db_col] = to_float(row[excel_col])

    spend_rows.append(tuple(spend[c] for c in SPEND_COLS))

print(f"  Rows to insert: {len(master_rows):,}  |  Skipped: {skipped}")

# ── Insert forecast_master in batches ──────────────────────────────────────
FM_COLS = (
    'forecast_version_id', 'airline_id', 'subfleet_id', 'year',
    'fleet_count', 'deliveries', 'avg_age',
    'retrofit_interval_adj', 'repair_interval_adj', 'repair_interval_adj_v2',
    'seat_data_source', 'data_confidence',
)

print("  Inserting forecast_master ...")
BATCH = 2000
inserted_ids = []
for i in range(0, len(master_rows), BATCH):
    batch = master_rows[i:i+BATCH]
    execute_values(
        cur,
        f"""INSERT INTO forecast_master ({', '.join(FM_COLS)}) VALUES %s
            RETURNING id""",
        batch
    )
    inserted_ids.extend(r[0] for r in cur.fetchall())
    conn.commit()
    if (i // BATCH) % 5 == 0:
        print(f"    ... {len(inserted_ids):,} / {len(master_rows):,}")

print(f"  forecast_master: {len(inserted_ids):,} rows inserted")

# ── Insert forecast_spend ──────────────────────────────────────────────────
FS_COLS = ['master_id'] + SPEND_COLS
full_spend = [(inserted_ids[i],) + spend_rows[i] for i in range(len(spend_rows))]

print("  Inserting forecast_spend ...")
for i in range(0, len(full_spend), BATCH):
    execute_values(
        cur,
        f"INSERT INTO forecast_spend ({', '.join(FS_COLS)}) VALUES %s",
        full_spend[i:i+BATCH]
    )
    conn.commit()
    if (i // BATCH) % 5 == 0:
        print(f"    ... {i+BATCH:,} / {len(full_spend):,}")

print(f"  forecast_spend: {len(full_spend):,} rows inserted")
print(f"\nDone in {time.time()-t0:.1f}s")
conn.close()
