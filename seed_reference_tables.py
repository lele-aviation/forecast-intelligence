"""
seed_reference_tables.py
Lele Aviation Intelligence Platform — Reference Table Seeder

Populates:
  - aircraft_types      (82 models from the forecast files)
  - airlines            (all operators from the forecast, ~800+)
  - suppliers           (key suppliers tracked in Hoku)
  - competitive_clusters
  - forecast_versions   (2022, 2024, 2026)
  - data_sources

RUN:  python seed_reference_tables.py
"""

import os
import sys
import psycopg2
from psycopg2.extras import execute_values
import pandas as pd
from dotenv import load_dotenv

load_dotenv()
url = os.getenv("DATABASE_URL")
if not url:
    sys.exit("DATABASE_URL not found in .env file.")

BASE = os.path.dirname(os.path.abspath(__file__))
SOURCE_DATA = os.path.join(os.path.dirname(BASE), 'source_data')   # Forecast Files/source_data/

print("Connecting to Supabase...")
conn = psycopg2.connect(url, connect_timeout=15)
conn.autocommit = False
cur = conn.cursor()
print("  Connected.\n")


def run(label, sql, params=None):
    try:
        cur.execute(sql, params)
        conn.commit()
        print(f"  ✓  {label}")
    except Exception as e:
        conn.rollback()
        print(f"  ✗  {label}: {e}")


def bulk_insert(label, table, columns, rows, conflict=None):
    if not rows:
        print(f"  –  {label}: no rows to insert")
        return
    cols = ", ".join(columns)
    conflict_clause = f"ON CONFLICT {conflict} DO NOTHING" if conflict else "ON CONFLICT DO NOTHING"
    sql = f"INSERT INTO {table} ({cols}) VALUES %s {conflict_clause}"
    try:
        execute_values(cur, sql, rows)
        conn.commit()
        print(f"  ✓  {label}: {len(rows)} rows")
    except Exception as e:
        conn.rollback()
        print(f"  ✗  {label}: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# 1. AIRCRAFT TYPES
# Source: all unique models across the three forecast files
# Category mapped from forecast labels; family and range derived from model
# ─────────────────────────────────────────────────────────────────────────────

print("1. Aircraft types")

# Category mapping from forecast labels to our schema
cat_map = {
    'Narrowbody Jet': 'Narrowbody',
    'Widebody Jet':   'Widebody',
    'Regional Jet':   'Regional',
}

# Family derivation — group models into their family
def get_family(oem, model):
    m = model.upper()
    if oem == 'Airbus':
        for prefix in ['A220','A300','A310','A318','A319','A320','A321','A330','A340','A350','A380']:
            if m.startswith(prefix.upper()):
                return prefix
        return model
    elif oem == 'Boeing':
        for prefix in ['717','727','737','747','757','767','777','787','MD-80','MD-90']:
            if m.startswith(prefix) or m.replace(' ','').startswith(prefix.replace('-','')):
                return prefix
        return model
    elif oem == 'Embraer':
        if any(x in m for x in ['E17','E19','E175','E190','E195']): return 'E-Jet'
        if 'ERJ' in m: return 'ERJ'
        if 'E2' in m: return 'E-Jet E2'
        return model
    elif oem == 'Bombardier':
        if 'CRJ' in m: return 'CRJ'
        return model
    return model

# Range derivation from model characteristics
def get_range(oem, model, category):
    m = model.upper()
    if category == 'Regional':
        return 'Short'
    if category == 'Narrowbody':
        if any(x in m for x in ['XLR','LR','900NEO','MAX10']):
            return 'Long'
        return 'Medium'
    if category == 'Widebody':
        if any(x in m for x in ['A380','777-9','777-8','A350-1000','747-8','777-200LR']):
            return 'Ultra-Long'
        return 'Long'
    return 'Medium'

# Load from 24-34 file (most complete model list)
df = pd.read_excel(
    os.path.join(SOURCE_DATA, '24-34 Interiors Forecast May 25 (version 1).xlsx'),
    sheet_name='Interiors MRO Forecast'
)
models = df.groupby(['Aircraft OEM','Aircraft Model','Aircraft Category']).size().reset_index()
models = models[['Aircraft OEM','Aircraft Model','Aircraft Category']].drop_duplicates()

aircraft_rows = []
for _, row in models.iterrows():
    oem      = row['Aircraft OEM'].strip()
    model    = row['Aircraft Model'].strip()
    cat_raw  = row['Aircraft Category'].strip()
    category = cat_map.get(cat_raw, 'Narrowbody')
    family   = get_family(oem, model)
    rng      = get_range(oem, model, category)
    aircraft_rows.append((oem, family, model, category, rng))

bulk_insert(
    "aircraft_types",
    "aircraft_types",
    ["oem", "family", "model", "category", "typical_range"],
    aircraft_rows,
    "(model)"
)


# ─────────────────────────────────────────────────────────────────────────────
# 2. AIRLINES
# Extract all unique operators from the forecast.
# operator_class (A/B/C/D) maps roughly to influence tier.
# Detailed classification (airline_category, scores) added for key airlines.
# All others seeded with basic info and can be enriched later via Supabase UI.
# ─────────────────────────────────────────────────────────────────────────────

print("\n2. Airlines")

# operator_class → influence_tier (rough mapping; key airlines overridden below)
class_to_tier = {'A': 1, 'B': 2, 'C': 3, 'D': 4}

# Load operators from all three files
dfs = []
for fname, sheet, engine, header in [
    ('2022-2032 Air Transport Seat and Interiors MRO-Refurb Forecast Output 23Oct2023 (1).xlsb',
     'Interiors MRO Forecast', 'pyxlsb', 1),
    ('24-34 Interiors Forecast May 25 (version 1).xlsx',
     'Interiors MRO Forecast', 'openpyxl', 0),
    ('26-35 forecast_data.xlsx',
     'RAW_licensed', 'openpyxl', 0),
]:
    df = pd.read_excel(os.path.join(SOURCE_DATA, fname), sheet_name=sheet,
                       engine=engine, header=header,
                       usecols=['Operator','Operator Class','Region'])
    dfs.append(df)

all_ops = pd.concat(dfs)
all_ops = all_ops.dropna(subset=['Operator'])
all_ops['Operator'] = all_ops['Operator'].str.strip()        # strip BEFORE dedup
all_ops['Operator Class'] = all_ops['Operator Class'].str.strip()
all_ops = all_ops[all_ops['Operator'] != '']
all_ops = all_ops.drop_duplicates(subset=['Operator'])       # dedup AFTER strip

print(f"  Found {len(all_ops)} unique operators across all files")

# Key airline overrides — detailed classification for Hoku-tracked airlines
# Format: operator_name → (airline_category, investment_decision_pattern,
#          trigger_p, peer_sensitivity, iata, icao, alliance,
#          brand, vis, network, fleet, reaction)
key_airlines = {
    'Emirates':              ('GL','FE','fleet_delivery','High','EK','UAE','None',5,5,5,5,5),
    'Qatar Airways':         ('GL','CR','competitor_response','High','QR','QTR','Oneworld',3,4,5,5,5),
    'Singapore Airlines':    ('GL','TC','time_cycle','High','SQ','SIA','Star',4,5,5,5,5),
    'Cathay Pacific Airways':('GL','FE','fleet_delivery','High','CX','CPA','Oneworld',3,4,4,5,4),
    'Delta Air Lines':       ('GL','HY','financial_milestone','High','DL','DAL','SkyTeam',4,5,5,4,5),
    'Etihad Airways':        ('FSC','HY','fleet_delivery','Moderate','EY','ETD','None',4,4,4,5,4),
    'Lufthansa':             ('FSC','HY','fleet_delivery','Moderate','LH','DLH','Star',4,4,5,4,4),
    'British Airways':       ('FSC','CR','competitor_response','Moderate','BA','BAW','Oneworld',4,4,5,4,3),
    'Japan Airlines':        ('FSC','TC','time_cycle','Moderate','JL','JAL','Oneworld',4,3,5,4,4),
    'United Airlines':       ('FSC','FE','fleet_delivery','Low','UA','UAL','Star',4,4,4,4,4),
    'Qantas Airways':        ('FSC','HY','financial_milestone','Moderate','QF','QFA','Oneworld',3,3,5,4,4),
    'Air France':            ('FSC','CR','competitor_response','Moderate','AF','AFR','SkyTeam',3,3,4,4,4),
    'All Nippon Airways':    ('FSC','TC','time_cycle','Moderate','NH','ANA','Star',3,3,3,4,4),
    'Air New Zealand':       ('RFSC','HY','fleet_delivery','Moderate','NZ','ANZ','Star',3,3,3,4,4),
    'Korean Air Lines':      ('FSC','TC','time_cycle','Moderate','KE','KAL','SkyTeam',2,3,4,4,3),
    'Air Canada':            ('FSC','CR','competitor_response','Moderate','AC','ACA','Star',3,3,4,3,3),
    'Air India':             ('FSC','FE','fleet_delivery','Low','AI','AIC','Star',3,3,4,3,2),
    'Turkish Airlines (Turk Hava Yollari)': ('FSC','FE','fleet_delivery','Low','TK','THY','Star',2,3,3,3,3),
    'American Airlines':     ('FSC','FE','fleet_delivery','Moderate','AA','AAL','Oneworld',2,2,3,3,3),
    'JetBlue Airways':       ('LCC','FE','fleet_delivery','Moderate','B6','JBU','None',2,3,2,2,3),
    'Southwest Airlines':    ('LCC','FE','fleet_delivery','Low','WN','SWA','None',2,2,3,2,2),
    'Alaska Airlines':       ('RFSC','HY','fleet_delivery','Moderate','AS','ASA','Oneworld',3,3,3,3,3),
    'Ryanair':               ('ULCC','FE','fleet_delivery','Low','FR','RYR','None',1,2,3,2,2),
}

# Build airline rows
airline_rows = []
seen = set()
for _, row in all_ops.iterrows():
    name = row['Operator']
    if name in seen:
        continue
    seen.add(name)

    region  = row.get('Region', None)
    op_cls  = str(row.get('Operator Class', 'C')).strip()
    tier    = class_to_tier.get(op_cls, 3)

    if name in key_airlines:
        (cat, pattern, trig_p, peer_sens, iata, icao, alliance,
         brand, vis, network, fleet, reaction) = key_airlines[name]
        airline_rows.append((
            name, iata, icao, None, None,
            cat, pattern,
            trig_p, None, None,
            peer_sens, region, None, alliance,
            tier,
            brand, vis, network, fleet, reaction,
            True
        ))
    else:
        airline_rows.append((
            name, None, None, None, None,
            None, None,
            None, None, None,
            None, region, None, None,
            tier,
            None, None, None, None, None,
            True
        ))

bulk_insert(
    "airlines",
    "airlines",
    ["name","iata_code","icao_code","ticker","parent_group",
     "airline_category","investment_decision_pattern",
     "trigger_primary","trigger_secondary_1","trigger_secondary_2",
     "peer_sensitivity","region","country","alliance",
     "influence_tier",
     "brand_product_score","competitive_visibility_score",
     "network_relevance_score","fleet_complexity_score",
     "reaction_trigger_rate_score",
     "is_active"],
    airline_rows,
    "(name)"
)


# ─────────────────────────────────────────────────────────────────────────────
# 3. SUPPLIERS
# Key suppliers tracked in the Hoku Market State Library.
# Can be expanded via Supabase table editor or future scripts.
# ─────────────────────────────────────────────────────────────────────────────

print("\n3. Suppliers")

suppliers = [
    # (name, ticker, hq_country, parent_company, tier, is_public)
    ('Collins Aerospace',        'RTX',  'United States', 'RTX Corporation',      1, True),
    ('Safran Cabin',             None,   'France',         'Safran SA',           1, True),
    ('Safran Seats',             None,   'France',         'Safran SA',           1, True),
    ('Recaro Aircraft Seating',  None,   'Germany',        None,                  1, False),
    ('Geven',                    None,   'Italy',          None,                  1, False),
    ('FACC AG',                  'FACC', 'Austria',        None,                  1, True),
    ('Thompson Aero Seating',    None,   'United Kingdom', None,                  1, False),
    ('ZIM Flugsitz',             None,   'Germany',        None,                  1, False),
    ('Stelia Aerospace',         None,   'France',         'Safran SA',           1, True),
    ('Jamco Corporation',        None,   'Japan',          None,                  1, False),
    ('AIM Altitude',             None,   'United Kingdom', None,                  1, False),
    ('Diehl Aviation',           None,   'Germany',        'Diehl Group',         1, False),
    ('Bucher Leichtbau',         None,   'Switzerland',    None,                  1, False),
    ('Zodiac Aerospace',         None,   'France',         'Safran SA',           1, True),
    ('TransDigm Group',          'TDG',  'United States',  None,                  1, True),
    ('ST Engineering',           'S63',  'Singapore',      None,                  1, True),
    ('HAECO',                    None,   'Hong Kong',      'CITIC Pacific',       1, True),
    ('CCE Group',                None,   'United States',  None,                  1, False),
    ('Panasonic Avionics',       None,   'United States',  'Panasonic',           1, True),
    ('Thales InFlyt Experience', None,   'France',         'Thales Group',        1, True),
    ('Anuvu',                    None,   'United States',  None,                  1, False),
    ('Viasat',                   'VSAT', 'United States',  None,                  1, True),
    ('Intelsat',                 None,   'United States',  None,                  1, False),
    ('Astronics',                'ATRO', 'United States',  None,                  1, True),
    ('Adhetec',                  None,   'France',         'Insperial',           2, False),
    ('Perrone Aerospace',        None,   'United States',  'Insperial',           2, False),
    ('MGR Foamtex',              None,   'United Kingdom', 'Insperial',           2, False),
    ('Airline Graphics',         None,   'United States',  'Insperial',           2, False),
    ('Tapis Corporation',        None,   'United States',  None,                  2, False),
    ('Spectra',                  None,   'United Kingdom', None,                  2, False),
    ('Aircraft Cabin Interiors', None,   'United States',  None,                  2, False),
]

bulk_insert(
    "suppliers",
    "suppliers",
    ["name","ticker","hq_country","parent_company","tier_in_supply_chain","is_public"],
    suppliers,
    "(name)"
)


# ─────────────────────────────────────────────────────────────────────────────
# 4. COMPETITIVE CLUSTERS
# ─────────────────────────────────────────────────────────────────────────────

print("\n4. Competitive clusters")

clusters = [
    ('NA-Mainline',          'route_overlap',    'Delta, United, American — domestic + transatlantic overlap',                         0.90),
    ('NA-Premium',           'product_segment',  'Delta, United, American, Air Canada — premium cabin competition',                    0.85),
    ('Gulf-Big3',            'route_overlap',    'Emirates, Qatar, Etihad — long-haul premium competition',                           0.95),
    ('Europe-FSC',           'route_overlap',    'Lufthansa Group, IAG, Air France-KLM — transatlantic + intra-European premium',      0.80),
    ('Asia-Pacific-Premium', 'product_segment',  'Singapore, Cathay, ANA, JAL — long-haul premium',                                  0.85),
    ('Transatlantic-Premium','product_segment',  'Delta, United, Lufthansa, BA, Air France, Virgin Atlantic — long-haul premium',     0.75),
    ('Middle-East-Europe',   'route_overlap',    'Emirates, Qatar, Etihad, Lufthansa, BA — Asia-Europe long-haul',                    0.80),
    ('NA-LCC',               'product_segment',  'Southwest, JetBlue, Alaska — domestic US LCC/hybrid competition',                   0.70),
]

bulk_insert(
    "competitive_clusters",
    "competitive_clusters",
    ["cluster_name","cluster_type","description","intensity"],
    clusters,
    "(cluster_name)"
)


# ─────────────────────────────────────────────────────────────────────────────
# 5. FORECAST VERSIONS
# ─────────────────────────────────────────────────────────────────────────────

print("\n5. Forecast versions")

versions = [
    ('2022_Forecast', '2023-10-01', 2022, 2032, False, '2022-2032 forecast published Oct 2023'),
    ('2024_Forecast', '2025-05-01', 2024, 2034, False, '2024-2034 forecast published May 2025'),
    ('2026_Forecast', '2026-06-01', 2026, 2035, True,  '2026-2035 forecast — current live version'),
]

bulk_insert(
    "forecast_versions",
    "forecast_versions",
    ["name","published_date","start_year","end_year","is_live","notes"],
    versions,
    "(name)"
)


# ─────────────────────────────────────────────────────────────────────────────
# 6. DATA SOURCES
# ─────────────────────────────────────────────────────────────────────────────

print("\n6. Data sources")

sources = [
    ('AeroLOPA',      'API',      'Quarterly', 'https://aerolopa.com'),
    ('SEC EDGAR',     'Public',   'Ad-Hoc',    'https://sec.gov/edgar'),
    ('Notion',        'Manual',   'Weekly',    None),
    ('Trade Press',   'Manual',   'Ad-Hoc',    None),
    ('Cirium',        'Licensed', 'Quarterly', None),
    ('CAPA',          'Licensed', 'Monthly',   None),
    ('OEM Direct',    'Manual',   'Ad-Hoc',    None),
    ('Earnings Calls','Public',   'Quarterly', None),
]

bulk_insert(
    "data_sources",
    "data_sources",
    ["name","source_type","refresh_cadence","api_endpoint"],
    sources,
    "(name)"
)


# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────────────────────

print("\n── Summary ────────────────────────────────────────────────────────────")
for table in ['aircraft_types','airlines','suppliers','competitive_clusters',
              'forecast_versions','data_sources']:
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    count = cur.fetchone()[0]
    print(f"  {table:30s} {count:>5} rows")

cur.close()
conn.close()
print("\nDone.")
