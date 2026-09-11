"""
create_schema.py
Lele Aviation Intelligence Platform — Database Schema Builder

Creates all tables and views in your Supabase PostgreSQL database.
Safe to re-run at any time — every CREATE uses IF NOT EXISTS, so
existing tables and data are never touched.

RUN:  python create_schema.py
"""

import os
import sys
import psycopg2
from dotenv import load_dotenv

# ─────────────────────────────────────────────────────────────────────────────
# CONNECT
# ─────────────────────────────────────────────────────────────────────────────

load_dotenv()
url = os.getenv("DATABASE_URL")
if not url:
    sys.exit("DATABASE_URL not found in .env file. Check the file exists and has the right content.")

print("Connecting to Supabase...")
try:
    conn = psycopg2.connect(url, connect_timeout=10)
    conn.autocommit = False
    cur = conn.cursor()
    print("  Connected.\n")
except Exception as e:
    sys.exit(f"Connection failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# HELPER
# Each block of SQL is run as a transaction. If anything fails, we roll back
# and print the error so you know exactly which table caused the problem.
# ─────────────────────────────────────────────────────────────────────────────

def run(label, sql):
    try:
        cur.execute(sql)
        conn.commit()
        print(f"  ✓  {label}")
    except Exception as e:
        conn.rollback()
        print(f"  ✗  {label}: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# GROUP A — REFERENCE TABLES
# These are created first because all other tables point to them.
# ─────────────────────────────────────────────────────────────────────────────

print("Group A — Reference tables")

run("airlines", """
CREATE TABLE IF NOT EXISTS airlines (
    id                          SERIAL PRIMARY KEY,
    name                        TEXT NOT NULL,
    iata_code                   TEXT,
    icao_code                   TEXT,
    ticker                      TEXT,
    parent_group                TEXT,

    -- Primary classification: what kind of airline is it
    -- GL=Global Leader, FSC=Full-Service, RFSC=Regional Full-Service,
    -- LCC=Low Cost, ULCC=Ultra Low Cost, EMG=Emerging, LSR=Leisure
    airline_category            TEXT CHECK (airline_category IN
                                    ('GL','FSC','RFSC','LCC','ULCC','EMG','LSR')),

    -- Secondary behavioral attribute used by the Reaction Engine
    -- FE=Fleet-Event-Linked, TC=Time-Cycled, CR=Competitor-Responsive, HY=Hybrid
    investment_decision_pattern TEXT CHECK (investment_decision_pattern IN ('FE','TC','CR','HY')),

    -- What moves this airline to invest (primary + up to 2 secondary triggers)
    trigger_primary             TEXT,
    trigger_secondary_1         TEXT,
    trigger_secondary_2         TEXT,

    peer_sensitivity            TEXT CHECK (peer_sensitivity IN ('High','Moderate','Low')),
    region                      TEXT,
    country                     TEXT,
    alliance                    TEXT CHECK (alliance IN ('Star','Oneworld','SkyTeam','None')),

    -- How much this airline's decisions move the market (1=highest influence)
    influence_tier              INTEGER CHECK (influence_tier BETWEEN 1 AND 4),

    -- The five scoring components that produce influence_tier
    brand_product_score         INTEGER CHECK (brand_product_score BETWEEN 1 AND 5),
    competitive_visibility_score INTEGER CHECK (competitive_visibility_score BETWEEN 1 AND 5),
    network_relevance_score     INTEGER CHECK (network_relevance_score BETWEEN 1 AND 5),
    fleet_complexity_score      INTEGER CHECK (fleet_complexity_score BETWEEN 1 AND 5),
    reaction_trigger_rate_score INTEGER CHECK (reaction_trigger_rate_score BETWEEN 1 AND 5),

    is_active                   BOOLEAN DEFAULT TRUE,
    notes                       TEXT,
    created_at                  TIMESTAMPTZ DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ DEFAULT NOW()
);
""")

run("aircraft_types", """
CREATE TABLE IF NOT EXISTS aircraft_types (
    id              SERIAL PRIMARY KEY,
    oem             TEXT NOT NULL,
    family          TEXT NOT NULL,
    model           TEXT NOT NULL UNIQUE,
    category        TEXT CHECK (category IN ('Narrowbody','Widebody','Regional','Turboprop')),
    typical_range   TEXT CHECK (typical_range IN ('Short','Medium','Long','Ultra-Long')),
    notes           TEXT
);
""")

run("suppliers", """
CREATE TABLE IF NOT EXISTS suppliers (
    id                      SERIAL PRIMARY KEY,
    name                    TEXT NOT NULL,
    ticker                  TEXT,
    hq_country              TEXT,
    parent_company          TEXT,
    -- 1=sells direct to airline/OEM, 2=sells to seat OEM, 3=materials/components
    tier_in_supply_chain    INTEGER CHECK (tier_in_supply_chain BETWEEN 1 AND 3),
    is_public               BOOLEAN DEFAULT FALSE,
    is_active               BOOLEAN DEFAULT TRUE,
    notes                   TEXT,
    created_at              TIMESTAMPTZ DEFAULT NOW()
);
""")

run("competitive_clusters", """
CREATE TABLE IF NOT EXISTS competitive_clusters (
    id              SERIAL PRIMARY KEY,
    cluster_name    TEXT NOT NULL UNIQUE,
    cluster_type    TEXT CHECK (cluster_type IN ('route_overlap','product_segment','alliance_block')),
    description     TEXT,
    -- 0.0 to 1.0: how reliably one airline's move provokes another's within this cluster
    intensity       NUMERIC(3,2) CHECK (intensity BETWEEN 0 AND 1),
    notes           TEXT
);
""")

run("data_sources", """
CREATE TABLE IF NOT EXISTS data_sources (
    id               SERIAL PRIMARY KEY,
    name             TEXT NOT NULL UNIQUE,
    source_type      TEXT CHECK (source_type IN ('API','Manual','Licensed','Public')),
    refresh_cadence  TEXT CHECK (refresh_cadence IN ('Weekly','Monthly','Quarterly','Ad-Hoc')),
    last_refreshed   DATE,
    api_endpoint     TEXT,
    notes            TEXT
);
""")

run("airline_cluster_membership", """
CREATE TABLE IF NOT EXISTS airline_cluster_membership (
    id                  SERIAL PRIMARY KEY,
    airline_id          INTEGER NOT NULL REFERENCES airlines(id),
    cluster_id          INTEGER NOT NULL REFERENCES competitive_clusters(id),
    is_primary_cluster  BOOLEAN DEFAULT FALSE,
    UNIQUE (airline_id, cluster_id)
);
""")

run("supplier_product_categories", """
CREATE TABLE IF NOT EXISTS supplier_product_categories (
    id                  SERIAL PRIMARY KEY,
    supplier_id         INTEGER NOT NULL REFERENCES suppliers(id),
    product_category    TEXT NOT NULL,
    product_subcategory TEXT,
    market_position     TEXT CHECK (market_position IN ('Leader','Challenger','Niche')),
    cabin_class_focus   TEXT CHECK (cabin_class_focus IN ('Economy','Business','First','All')),
    UNIQUE (supplier_id, product_category, product_subcategory)
);
""")

run("subfleets", """
CREATE TABLE IF NOT EXISTS subfleets (
    id                      SERIAL PRIMARY KEY,
    airline_id              INTEGER NOT NULL REFERENCES airlines(id),
    aircraft_type_id        INTEGER NOT NULL REFERENCES aircraft_types(id),

    -- Name that identifies the specific configuration (from AeroLOPA)
    subfleet_name           TEXT NOT NULL,

    -- Seat counts by cabin class
    seats_first_recliner    INTEGER DEFAULT 0,
    seats_first_lieflat     INTEGER DEFAULT 0,
    seats_domestic_first    INTEGER DEFAULT 0,
    seats_j_recliner        INTEGER DEFAULT 0,
    seats_j_lieflat         INTEGER DEFAULT 0,
    seats_premium_economy   INTEGER DEFAULT 0,
    seats_economy_plus      INTEGER DEFAULT 0,
    seats_economy           INTEGER DEFAULT 0,
    seats_total             INTEGER DEFAULT 0,

    -- IFE and cabin equipment
    has_ife                 BOOLEAN DEFAULT FALSE,
    ife_type                TEXT CHECK (ife_type IN ('AVOD-Seatback','Overhead','BYOD-Streaming','No-IFE')),
    galley_type             TEXT CHECK (galley_type IN ('Standard','Premium','Galley-Heavy')),
    lav_count               INTEGER,

    -- Connectivity (v3.3): no source data exists anywhere for this yet --
    -- 100% manual entry by design, independent of the IFE fields above.
    has_connectivity        BOOLEAN DEFAULT FALSE,
    connectivity_notes      TEXT,

    -- Retirement modeling (v3.3): leave NULL to use the Size Class default
    -- from retirement_age_defaults (see Group F below).
    retirement_age_override NUMERIC(4,1),

    -- Config validity dates (configs change as airlines reconfigure aircraft)
    valid_from              DATE,
    valid_to                DATE,

    source                  TEXT CHECK (source IN ('AeroLOPA','Manual','OEM')),
    last_updated            DATE,
    notes                   TEXT,

    UNIQUE (airline_id, aircraft_type_id, subfleet_name)
);
""")


# ─────────────────────────────────────────────────────────────────────────────
# GROUP B — EVENT TABLES
# ─────────────────────────────────────────────────────────────────────────────

print("\nGroup B — Event tables")

run("cabin_events", """
CREATE TABLE IF NOT EXISTS cabin_events (
    id                          SERIAL PRIMARY KEY,
    event_id                    TEXT UNIQUE,  -- EVT-XXXX for historical records
    airline_id                  INTEGER NOT NULL REFERENCES airlines(id),
    event_date                  DATE NOT NULL,
    year                        INTEGER,
    quarter                     TEXT,

    event_type                  TEXT,
    signal_family               TEXT,
    cabin_class                 TEXT CHECK (cabin_class IN
                                    ('All','Economy','Business','First','Premium_Economy')),
    scope                       TEXT CHECK (scope IN
                                    ('New_Deliveries_Only','Full_Fleet','Partial_Fleet')),
    trigger_context             TEXT,

    -- Which competitor was cited as the driver (if any)
    peer_reference_airline_id   INTEGER REFERENCES airlines(id),

    capex_mentioned             BOOLEAN DEFAULT FALSE,
    capex_amount_text           TEXT,
    capex_amount_usd            NUMERIC(15,2),
    retrofit_target_year        INTEGER,

    -- CRITICAL: TRUE = program already announced/awarded (WON by a supplier).
    -- Not an open opportunity. IS a trigger for reaction analysis in peer airlines.
    is_announcement             BOOLEAN DEFAULT FALSE,

    event_summary               TEXT,
    confidence                  TEXT CHECK (confidence IN ('High','Medium','Low')),
    verified                    BOOLEAN DEFAULT FALSE,
    source_type                 TEXT CHECK (source_type IN
                                    ('SEC','Press_Release','Earnings_Call',
                                     'Trade_Press','Conference','AeroLOPA')),
    source_document             TEXT,

    -- Link back to the Notion Raw Signal Intake page that generated this event
    notion_signal_url           TEXT,

    created_at                  TIMESTAMPTZ DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ DEFAULT NOW(),
    notes                       TEXT
);
""")

run("event_aircraft", """
CREATE TABLE IF NOT EXISTS event_aircraft (
    id               SERIAL PRIMARY KEY,
    event_id         INTEGER NOT NULL REFERENCES cabin_events(id),
    aircraft_type_id INTEGER NOT NULL REFERENCES aircraft_types(id),
    aircraft_count   INTEGER,
    UNIQUE (event_id, aircraft_type_id)
);
""")

run("supplier_program_wins", """
CREATE TABLE IF NOT EXISTS supplier_program_wins (
    id                          SERIAL PRIMARY KEY,
    -- The cabin_event where the program was announced (is_announcement = TRUE)
    event_id                    INTEGER REFERENCES cabin_events(id),
    supplier_id                 INTEGER NOT NULL REFERENCES suppliers(id),
    product_category            TEXT NOT NULL,
    product_subcategory         TEXT,
    contract_type               TEXT CHECK (contract_type IN
                                    ('SFE','BFE','MRO_Sole_Source',
                                     'MRO_Approved_Vendor','Refurbishment')),
    fleet_count                 INTEGER,
    contract_value_usd          NUMERIC(15,2),
    announced_date              DATE,
    estimated_production_start  DATE,
    -- High = confirmed press release, Medium = inferred, Low = rumored
    confidence                  TEXT CHECK (confidence IN ('High','Medium','Low')),
    source                      TEXT,
    notes                       TEXT,
    created_at                  TIMESTAMPTZ DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ DEFAULT NOW()
);
""")

run("sub_supplier_relationships", """
CREATE TABLE IF NOT EXISTS sub_supplier_relationships (
    id                  SERIAL PRIMARY KEY,
    -- e.g. Recaro (Tier 1) uses this foam manufacturer (Tier 2)
    tier1_supplier_id   INTEGER NOT NULL REFERENCES suppliers(id),
    tier2_supplier_id   INTEGER NOT NULL REFERENCES suppliers(id),
    product_link        TEXT NOT NULL,  -- what Tier 2 provides to Tier 1
    relationship_type   TEXT CHECK (relationship_type IN
                            ('Sole_Source','Qualified','Occasional')),
    confidence          TEXT CHECK (confidence IN ('High','Medium','Low')),
    notes               TEXT,
    UNIQUE (tier1_supplier_id, tier2_supplier_id, product_link)
);
""")

run("retrofit_events", """
CREATE TABLE IF NOT EXISTS retrofit_events (
    id                          SERIAL PRIMARY KEY,
    event_id                    INTEGER NOT NULL REFERENCES cabin_events(id),
    airline_id                  INTEGER NOT NULL REFERENCES airlines(id),
    aircraft_type_id            INTEGER REFERENCES aircraft_types(id),
    subfleet_id                 INTEGER REFERENCES subfleets(id),
    announcement_date           DATE,
    retrofit_start_year         INTEGER,
    retrofit_complete_year_est  INTEGER,
    fleet_count                 INTEGER,
    cabin_classes_affected      TEXT,
    -- When TRUE, forecast_master rows for this airline x aircraft reset
    -- their retrofit interval calculator from this announcement date forward
    resets_forecast_timing      BOOLEAN DEFAULT TRUE,
    notes                       TEXT
);
""")

run("reaction_events", """
CREATE TABLE IF NOT EXISTS reaction_events (
    id                              SERIAL PRIMARY KEY,
    -- The announcing airline's event that triggered this analysis
    trigger_event_id                INTEGER NOT NULL REFERENCES cabin_events(id),
    -- The airline expected to respond
    target_airline_id               INTEGER NOT NULL REFERENCES airlines(id),

    -- Reaction Engine outputs
    reaction_probability            NUMERIC(4,3) CHECK (reaction_probability BETWEEN 0 AND 1),
    timing_window_min_months        INTEGER,
    timing_window_max_months        INTEGER,
    timing_bucket                   TEXT,  -- e.g. "18-36 months"

    -- Modifier components (from Decision Tree Engine)
    signal_multiplier               NUMERIC(4,2),
    age_modifier                    NUMERIC(6,4),
    cluster_modifier                NUMERIC(6,4),
    investment_pattern_modifier     NUMERIC(6,4),
    final_probability               NUMERIC(4,3) CHECK (final_probability BETWEEN 0 AND 1),

    priority_band                   TEXT CHECK (priority_band IN ('High','Medium','Low')),
    recommended_action              TEXT,

    -- The key output: probability-weighted dollar opportunity
    -- = target fleet x seat counts x spend rates x final_probability
    forecast_opportunity_value_usd  NUMERIC(15,2),

    status                          TEXT DEFAULT 'Open'
                                    CHECK (status IN ('Open','Materialized','Expired','Cancelled')),
    -- Populated when the reaction actually happens
    materialized_event_id           INTEGER REFERENCES cabin_events(id),

    week_identified                 TEXT,
    created_at                      TIMESTAMPTZ DEFAULT NOW(),
    updated_at                      TIMESTAMPTZ DEFAULT NOW(),
    notes                           TEXT,

    UNIQUE (trigger_event_id, target_airline_id)
);
""")


# ─────────────────────────────────────────────────────────────────────────────
# GROUP C — FORECAST TABLES
# ─────────────────────────────────────────────────────────────────────────────

print("\nGroup C — Forecast tables")

run("forecast_versions", """
CREATE TABLE IF NOT EXISTS forecast_versions (
    id                      SERIAL PRIMARY KEY,
    name                    TEXT NOT NULL UNIQUE,  -- e.g. '2022_Forecast'
    published_date          DATE,
    start_year              INTEGER NOT NULL,
    end_year                INTEGER NOT NULL,
    -- Only one forecast is 'live' at a time (used for opportunity calculations)
    is_live                 BOOLEAN DEFAULT FALSE,
    -- 2027_Forecast will reference 2026_Forecast here
    based_on_version_id     INTEGER REFERENCES forecast_versions(id),
    notes                   TEXT,
    created_at              TIMESTAMPTZ DEFAULT NOW()
);
""")

run("assumptions", """
CREATE TABLE IF NOT EXISTS assumptions (
    id                      SERIAL PRIMARY KEY,
    forecast_version_id     INTEGER NOT NULL REFERENCES forecast_versions(id),
    product_category        TEXT NOT NULL,
    service_type            TEXT CHECK (service_type IN ('Replace','Repair')),
    aircraft_category       TEXT CHECK (aircraft_category IN
                                ('Narrowbody','Widebody','Regional','All')),
    cabin_class             TEXT CHECK (cabin_class IN
                                ('Economy','Business','First','Premium_Economy','All')),
    -- For seat-based categories (cost per seat per cycle)
    cost_per_seat_usd       NUMERIC(10,2),
    -- For non-seat categories (cost per aircraft per cycle)
    cost_per_aircraft_usd   NUMERIC(10,2),
    -- How many years between replacement/repair events
    interval_years          NUMERIC(4,1),
    effective_date          DATE,
    source                  TEXT,
    notes                   TEXT,
    UNIQUE (forecast_version_id, product_category, service_type, aircraft_category, cabin_class)
);
""")

run("forecast_master", """
CREATE TABLE IF NOT EXISTS forecast_master (
    id                          SERIAL PRIMARY KEY,
    forecast_version_id         INTEGER NOT NULL REFERENCES forecast_versions(id),
    airline_id                  INTEGER NOT NULL REFERENCES airlines(id),
    -- Subfleet links to exact cabin configuration (replaces flat operator+model)
    subfleet_id                 INTEGER NOT NULL REFERENCES subfleets(id),
    year                        INTEGER NOT NULL,

    fleet_count                 NUMERIC(8,3),
    deliveries                  NUMERIC(8,3),
    avg_age                     NUMERIC(6,3),

    -- Retirement modeling (v3.3): fleet_count above is left untouched
    -- (licensed, no retirements) -- fleet_count_adjusted is a separate,
    -- transparent overlay. retirements = aircraft retiring that year (20%/yr
    -- phase-out once avg_age crosses the subfleet's effective retirement age).
    retirements                  NUMERIC(8,3),
    fleet_count_adjusted         NUMERIC(8,3),

    retrofit_interval_adj       NUMERIC(4,2),
    repair_interval_adj         NUMERIC(4,2),
    repair_interval_adj_v2      NUMERIC(4,2),

    -- Set when a retrofit_events record resets the timing calculator
    retrofit_last_completed_year INTEGER,

    seat_data_source            TEXT,
    data_confidence             TEXT CHECK (data_confidence IN ('High','Medium','Low')),
    last_updated                TIMESTAMPTZ DEFAULT NOW(),
    updated_by                  TEXT,
    notes                       TEXT,

    UNIQUE (forecast_version_id, airline_id, subfleet_id, year)
);
""")

run("forecast_spend", """
CREATE TABLE IF NOT EXISTS forecast_spend (
    id              SERIAL PRIMARY KEY,
    master_id       INTEGER NOT NULL REFERENCES forecast_master(id),

    -- ── NEW EQUIPMENT (linefit) ──────────────────────────────────────
    new_first_recliner_seats        NUMERIC(12,2) DEFAULT 0,
    new_first_lieflat_seats         NUMERIC(12,2) DEFAULT 0,
    new_domestic_first_seats        NUMERIC(12,2) DEFAULT 0,
    new_j_recliner_seats            NUMERIC(12,2) DEFAULT 0,
    new_j_lieflat_seats             NUMERIC(12,2) DEFAULT 0,
    new_economy_plus_seats          NUMERIC(12,2) DEFAULT 0,
    new_economy_seats               NUMERIC(12,2) DEFAULT 0,
    total_new_seats                 NUMERIC(12,2) DEFAULT 0,

    -- ── SEATS — REPLACE ──────────────────────────────────────────────
    economy_seats_replace           NUMERIC(12,2) DEFAULT 0,
    py_seats_replace                NUMERIC(12,2) DEFAULT 0,
    business_seats_replace          NUMERIC(12,2) DEFAULT 0,
    dom_first_seats_replace         NUMERIC(12,2) DEFAULT 0,
    first_seats_replace             NUMERIC(12,2) DEFAULT 0,
    total_seats_replace             NUMERIC(12,2) DEFAULT 0,

    -- ── SEATS — REPAIR ───────────────────────────────────────────────
    economy_seats_repair            NUMERIC(12,2) DEFAULT 0,
    py_seats_repair                 NUMERIC(12,2) DEFAULT 0,
    business_seats_repair           NUMERIC(12,2) DEFAULT 0,
    dom_first_seats_repair          NUMERIC(12,2) DEFAULT 0,
    first_seats_repair              NUMERIC(12,2) DEFAULT 0,
    total_seats_repair              NUMERIC(12,2) DEFAULT 0,

    -- ── SOFT GOODS — REPLACE ─────────────────────────────────────────
    carpets_replace                 NUMERIC(12,2) DEFAULT 0,
    flooring_replace                NUMERIC(12,2) DEFAULT 0,
    curtains_replace                NUMERIC(12,2) DEFAULT 0,
    seat_covers_economy_replace     NUMERIC(12,2) DEFAULT 0,
    seat_covers_business_replace    NUMERIC(12,2) DEFAULT 0,
    seat_covers_dom_first_replace   NUMERIC(12,2) DEFAULT 0,
    seat_covers_first_replace       NUMERIC(12,2) DEFAULT 0,
    seat_cushions_economy_replace   NUMERIC(12,2) DEFAULT 0,
    seat_cushions_business_replace  NUMERIC(12,2) DEFAULT 0,
    seat_cushions_dom_first_replace NUMERIC(12,2) DEFAULT 0,
    seat_cushions_first_replace     NUMERIC(12,2) DEFAULT 0,
    cut_sew_economy_replace         NUMERIC(12,2) DEFAULT 0,
    cut_sew_business_replace        NUMERIC(12,2) DEFAULT 0,
    cut_sew_dom_first_replace       NUMERIC(12,2) DEFAULT 0,
    cut_sew_first_replace           NUMERIC(12,2) DEFAULT 0,
    total_soft_goods_replace        NUMERIC(12,2) DEFAULT 0,

    -- ── SOFT GOODS — REPAIR ──────────────────────────────────────────
    carpets_repair                  NUMERIC(12,2) DEFAULT 0,
    flooring_repair                 NUMERIC(12,2) DEFAULT 0,
    curtains_repair                 NUMERIC(12,2) DEFAULT 0,
    seat_covers_economy_repair      NUMERIC(12,2) DEFAULT 0,
    seat_covers_business_repair     NUMERIC(12,2) DEFAULT 0,
    seat_covers_dom_first_repair    NUMERIC(12,2) DEFAULT 0,
    seat_covers_first_repair        NUMERIC(12,2) DEFAULT 0,
    seat_cushions_economy_repair    NUMERIC(12,2) DEFAULT 0,
    seat_cushions_business_repair   NUMERIC(12,2) DEFAULT 0,
    seat_cushions_dom_first_repair  NUMERIC(12,2) DEFAULT 0,
    seat_cushions_first_repair      NUMERIC(12,2) DEFAULT 0,
    total_soft_goods_repair         NUMERIC(12,2) DEFAULT 0,

    -- ── SEAT BELTS ───────────────────────────────────────────────────
    seatbelts_flight_crew_replace   NUMERIC(12,2) DEFAULT 0,
    seatbelts_standard_replace      NUMERIC(12,2) DEFAULT 0,
    seatbelts_regulatory_replace    NUMERIC(12,2) DEFAULT 0,
    total_seatbelts_replace         NUMERIC(12,2) DEFAULT 0,
    seatbelts_flight_crew_repair    NUMERIC(12,2) DEFAULT 0,
    seatbelts_standard_repair       NUMERIC(12,2) DEFAULT 0,
    total_seatbelts_repair          NUMERIC(12,2) DEFAULT 0,

    -- ── HARD GOODS — REPLACE ─────────────────────────────────────────
    lavatories_replace              NUMERIC(12,2) DEFAULT 0,
    laminates_replace               NUMERIC(12,2) DEFAULT 0,
    panels_ceiling_replace          NUMERIC(12,2) DEFAULT 0,
    panels_sidewalls_replace        NUMERIC(12,2) DEFAULT 0,
    panels_overhead_bins_replace    NUMERIC(12,2) DEFAULT 0,
    panels_latches_replace          NUMERIC(12,2) DEFAULT 0,
    panels_window_shades_replace    NUMERIC(12,2) DEFAULT 0,
    total_panels_replace            NUMERIC(12,2) DEFAULT 0,
    galleys_replace                 NUMERIC(12,2) DEFAULT 0,
    ovens_replace                   NUMERIC(12,2) DEFAULT 0,
    coffee_makers_replace           NUMERIC(12,2) DEFAULT 0,
    carts_replace                   NUMERIC(12,2) DEFAULT 0,
    chillers_replace                NUMERIC(12,2) DEFAULT 0,
    liquid_chillers_replace         NUMERIC(12,2) DEFAULT 0,
    total_galley_inserts_replace    NUMERIC(12,2) DEFAULT 0,
    stowage_closets_replace         NUMERIC(12,2) DEFAULT 0,
    overhead_lighting_replace       NUMERIC(12,2) DEFAULT 0,
    ifec_replace                    NUMERIC(12,2) DEFAULT 0,
    engineering_certification       NUMERIC(12,2) DEFAULT 0,
    misc_parts_kits                 NUMERIC(12,2) DEFAULT 0,

    -- ── HARD GOODS — REPAIR ──────────────────────────────────────────
    lavatories_repair               NUMERIC(12,2) DEFAULT 0,
    laminates_repair                NUMERIC(12,2) DEFAULT 0,
    panels_ceiling_repair           NUMERIC(12,2) DEFAULT 0,
    panels_sidewalls_repair         NUMERIC(12,2) DEFAULT 0,
    panels_overhead_bins_repair     NUMERIC(12,2) DEFAULT 0,
    panels_latches_repair           NUMERIC(12,2) DEFAULT 0,
    panels_window_shades_repair     NUMERIC(12,2) DEFAULT 0,
    total_panels_repair             NUMERIC(12,2) DEFAULT 0,
    galleys_repair                  NUMERIC(12,2) DEFAULT 0,
    ovens_repair                    NUMERIC(12,2) DEFAULT 0,
    coffee_makers_repair            NUMERIC(12,2) DEFAULT 0,
    carts_repair                    NUMERIC(12,2) DEFAULT 0,
    chillers_repair                 NUMERIC(12,2) DEFAULT 0,
    liquid_chillers_repair          NUMERIC(12,2) DEFAULT 0,
    total_galley_inserts_repair     NUMERIC(12,2) DEFAULT 0,
    stowage_closets_repair          NUMERIC(12,2) DEFAULT 0,
    overhead_lighting_repair        NUMERIC(12,2) DEFAULT 0,
    ifec_repair                     NUMERIC(12,2) DEFAULT 0,

    -- ── SUMMARY TOTALS ───────────────────────────────────────────────
    total_replace_excl_softgoods    NUMERIC(12,2) DEFAULT 0,
    total_replace_incl_softgoods    NUMERIC(12,2) DEFAULT 0,
    total_repair                    NUMERIC(12,2) DEFAULT 0,
    total_spend                     NUMERIC(12,2) DEFAULT 0,

    -- Probability-weighted: total_spend x allocation_score / 100
    -- Populated when Hoku allocation scores are applied
    probability_weighted_spend      NUMERIC(12,2),

    UNIQUE (master_id)
);
""")


# ─────────────────────────────────────────────────────────────────────────────
# GROUP D — HOKU ALLOCATION TABLES
# ─────────────────────────────────────────────────────────────────────────────

print("\nGroup D — Hoku allocation tables")

run("airline_allocation_scores", """
CREATE TABLE IF NOT EXISTS airline_allocation_scores (
    id                  SERIAL PRIMARY KEY,
    airline_id          INTEGER NOT NULL REFERENCES airlines(id),
    week_label          TEXT NOT NULL,  -- e.g. 'Wk23'
    score_date          DATE NOT NULL,

    stage               TEXT CHECK (stage IN ('Early','Emerging','Actionable','Urgent')),
    compression         NUMERIC(5,1),
    earnings            NUMERIC(5,1),
    capital_modifier    NUMERIC(4,1),
    cluster_intensity   NUMERIC(3,2),

    -- Calculated fields (match the Excel model)
    base_proximity      NUMERIC(8,4),
    stage_bonus         NUMERIC(4,1),
    allocation_score    NUMERIC(6,2),
    allocation_tier     TEXT CHECK (allocation_tier IN ('Tier 1','Tier 2','Tier 3')),
    influence_tier      INTEGER CHECK (influence_tier BETWEEN 1 AND 4),

    -- Points to previous week's row — enables score delta queries
    previous_score_id   INTEGER REFERENCES airline_allocation_scores(id),
    notes               TEXT,

    UNIQUE (airline_id, week_label)
);
""")

run("model_adjustments", """
CREATE TABLE IF NOT EXISTS model_adjustments (
    id                          SERIAL PRIMARY KEY,
    airline_id                  INTEGER NOT NULL REFERENCES airlines(id),
    week_label                  TEXT NOT NULL,
    adjustment_date             DATE NOT NULL,

    -- The Notion Raw Signal Intake page that triggered this adjustment
    notion_signal_url           TEXT,
    -- If the signal was also logged as a cabin event
    cabin_event_id              INTEGER REFERENCES cabin_events(id),

    stage_before                TEXT,
    stage_after                 TEXT,
    -- -2, -1, 0, +1, +2
    compression_delta           INTEGER CHECK (compression_delta BETWEEN -2 AND 2),
    earnings_delta              INTEGER CHECK (earnings_delta BETWEEN -2 AND 2),

    allocation_score_before     NUMERIC(6,2),
    allocation_score_after      NUMERIC(6,2),
    rationale                   TEXT,
    created_at                  TIMESTAMPTZ DEFAULT NOW()
);
""")

run("hoku_signals", """
CREATE TABLE IF NOT EXISTS hoku_signals (
    id                  SERIAL PRIMARY KEY,
    -- The Notion Raw Signal Intake page URL (cross-reference key)
    notion_signal_url   TEXT UNIQUE,
    week_label          TEXT,
    signal_date         DATE,
    signal_title        TEXT NOT NULL,

    -- Notion field: Pillar
    pillar              TEXT CHECK (pillar IN ('Airline','Supplier','OEM','Lessor','Macro')),
    -- Free-text company name (may be airline, supplier, OEM, or lessor)
    company             TEXT,
    -- FK set if company is a tracked airline
    airline_id          INTEGER REFERENCES airlines(id),
    -- FK set if company is a tracked supplier
    supplier_id         INTEGER REFERENCES suppliers(id),

    -- Notion field: Signal Type
    signal_type         TEXT CHECK (signal_type IN
                            ('Capital_Expansion','Competitive_Compression',
                             'Execution_Risk','Portfolio_Rotation','Noise')),
    -- Notion field: Trigger Category (9 options)
    trigger_category    TEXT,
    -- Notion field: Quick Score (1-5)
    quick_score         INTEGER CHECK (quick_score BETWEEN 1 AND 5),
    -- Notion field: Reaction Multiplier
    reaction_multiplier TEXT CHECK (reaction_multiplier IN ('Low','Medium','High')),
    -- Notion field: Market Impact Scope
    market_impact_scope TEXT CHECK (market_impact_scope IN
                            ('Airline_Allocation','Supplier_Competitive_Landscape','Both')),
    -- Notion field: Market Theme
    market_theme        TEXT,
    -- Notion field: Triage Worthy
    triage_worthy       BOOLEAN DEFAULT FALSE,
    -- Notion field: Why It Matters
    why_it_matters      TEXT,
    -- Notion field: Source Type
    source_type         TEXT,
    source_url          TEXT,

    -- Set if this signal was promoted to a cabin_events record
    linked_event_id     INTEGER REFERENCES cabin_events(id),

    synced_at           TIMESTAMPTZ DEFAULT NOW(),
    created_at          TIMESTAMPTZ DEFAULT NOW()
);
""")

run("watchlist", """
CREATE TABLE IF NOT EXISTS watchlist (
    id                  SERIAL PRIMARY KEY,
    airline_id          INTEGER NOT NULL REFERENCES airlines(id),
    aircraft_type_id    INTEGER REFERENCES aircraft_types(id),
    forward_signal      TEXT NOT NULL,
    probability_window  TEXT,
    priority            TEXT CHECK (priority IN ('High','Medium','Low')),
    status              TEXT DEFAULT 'Active'
                        CHECK (status IN ('Active','Triggered','Expired')),
    -- Set when the signal actually fires
    triggered_event_id  INTEGER REFERENCES cabin_events(id),
    identified_week     TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);
""")


# ─────────────────────────────────────────────────────────────────────────────
# GROUP E — AUDIT
# ─────────────────────────────────────────────────────────────────────────────

print("\nGroup E — Audit")

run("audit_log", """
CREATE TABLE IF NOT EXISTS audit_log (
    id              SERIAL PRIMARY KEY,
    table_name      TEXT NOT NULL,
    record_id       INTEGER NOT NULL,
    field_name      TEXT,
    old_value       TEXT,
    new_value       TEXT,
    changed_by      TEXT DEFAULT 'system',
    changed_at      TIMESTAMPTZ DEFAULT NOW(),
    change_reason   TEXT
);
""")


# ─────────────────────────────────────────────────────────────────────────────
# GROUP F — RETIREMENT MODELING + IFE/CONNECTIVITY (v3.3)
# retirement_age_defaults is a new table. The rest are ALTERs: subfleets and
# forecast_master already exist on a live database, so the CREATE TABLE IF
# NOT EXISTS blocks in Groups A/C above are no-ops there and won't pick up
# these new columns on their own. Safe to re-run -- every statement uses
# IF NOT EXISTS / IF EXISTS, including the constraint swap.
# ─────────────────────────────────────────────────────────────────────────────

print("\nGroup F — Retirement modeling + IFE/connectivity")

run("retirement_age_defaults", """
CREATE TABLE IF NOT EXISTS retirement_age_defaults (
    id                      SERIAL PRIMARY KEY,
    -- One row per Size Class; 01_Fleet_Baseline's retirement cascade
    -- (subfleet override -> this default) looks rows up by this column.
    aircraft_size_class     TEXT NOT NULL CHECK (aircraft_size_class IN
                                ('Narrowbody','Widebody','Regional','Turboprop')),
    default_retirement_age  NUMERIC(4,1) NOT NULL,
    notes                   TEXT
);
""")

run("subfleets.retirement_age_override", """
ALTER TABLE subfleets
    ADD COLUMN IF NOT EXISTS retirement_age_override NUMERIC(4,1);
""")

run("subfleets.has_connectivity", """
ALTER TABLE subfleets
    ADD COLUMN IF NOT EXISTS has_connectivity BOOLEAN DEFAULT FALSE;
""")

run("subfleets.connectivity_notes", """
ALTER TABLE subfleets
    ADD COLUMN IF NOT EXISTS connectivity_notes TEXT;
""")

run("subfleets.ife_type (updated CHECK values)", """
ALTER TABLE subfleets DROP CONSTRAINT IF EXISTS subfleets_ife_type_check;
ALTER TABLE subfleets
    ADD CONSTRAINT subfleets_ife_type_check
    CHECK (ife_type IN ('AVOD-Seatback','Overhead','BYOD-Streaming','No-IFE'));
""")

# subfleets.has_ife / ife_type (above) describe IFE for the whole subfleet row.
# 2026-06-22: Jon asked to break IFE out by seat type. AeroLOPA's source data
# only distinguishes IFE at the 4-way cabin-class grain (First/Business/
# Premium Economy/Economy), not the finer seat-hardware-variant grain (e.g.
# F Lie-Flat vs F Recliner vs F Domestic share one First-cabin IFE value), so
# that's the grain used here -- confirmed with Jon. These columns are NOT
# DEFAULT FALSE like the original has_ife (that mixed "confirmed no IFE" with
# "unknown/uncovered" -- see the None/False split in legacy data); NULL here
# means "not covered by AeroLOPA / no seats of this type," distinct from
# FALSE ("confirmed no IFE in this cabin"). The original has_ife/ife_type
# pair is left in place but is no longer surfaced in the workbook -- superseded
# by the four pairs below.
run("subfleets.has_ife_first / ife_type_first", """
ALTER TABLE subfleets ADD COLUMN IF NOT EXISTS has_ife_first BOOLEAN;
ALTER TABLE subfleets ADD COLUMN IF NOT EXISTS ife_type_first TEXT;
ALTER TABLE subfleets DROP CONSTRAINT IF EXISTS subfleets_ife_type_first_check;
ALTER TABLE subfleets
    ADD CONSTRAINT subfleets_ife_type_first_check
    CHECK (ife_type_first IN ('AVOD-Seatback','Overhead','BYOD-Streaming','No-IFE'));
""")

run("subfleets.has_ife_business / ife_type_business", """
ALTER TABLE subfleets ADD COLUMN IF NOT EXISTS has_ife_business BOOLEAN;
ALTER TABLE subfleets ADD COLUMN IF NOT EXISTS ife_type_business TEXT;
ALTER TABLE subfleets DROP CONSTRAINT IF EXISTS subfleets_ife_type_business_check;
ALTER TABLE subfleets
    ADD CONSTRAINT subfleets_ife_type_business_check
    CHECK (ife_type_business IN ('AVOD-Seatback','Overhead','BYOD-Streaming','No-IFE'));
""")

run("subfleets.has_ife_premium_economy / ife_type_premium_economy", """
ALTER TABLE subfleets ADD COLUMN IF NOT EXISTS has_ife_premium_economy BOOLEAN;
ALTER TABLE subfleets ADD COLUMN IF NOT EXISTS ife_type_premium_economy TEXT;
ALTER TABLE subfleets DROP CONSTRAINT IF EXISTS subfleets_ife_type_premium_economy_check;
ALTER TABLE subfleets
    ADD CONSTRAINT subfleets_ife_type_premium_economy_check
    CHECK (ife_type_premium_economy IN ('AVOD-Seatback','Overhead','BYOD-Streaming','No-IFE'));
""")

run("subfleets.has_ife_economy / ife_type_economy", """
ALTER TABLE subfleets ADD COLUMN IF NOT EXISTS has_ife_economy BOOLEAN;
ALTER TABLE subfleets ADD COLUMN IF NOT EXISTS ife_type_economy TEXT;
ALTER TABLE subfleets DROP CONSTRAINT IF EXISTS subfleets_ife_type_economy_check;
ALTER TABLE subfleets
    ADD CONSTRAINT subfleets_ife_type_economy_check
    CHECK (ife_type_economy IN ('AVOD-Seatback','Overhead','BYOD-Streaming','No-IFE'));
""")

run("forecast_master.retirements", """
ALTER TABLE forecast_master
    ADD COLUMN IF NOT EXISTS retirements NUMERIC(8,3);
""")

run("forecast_master.fleet_count_adjusted", """
ALTER TABLE forecast_master
    ADD COLUMN IF NOT EXISTS fleet_count_adjusted NUMERIC(8,3);
""")


# ─────────────────────────────────────────────────────────────────────────────
# ROLLUP VIEWS
# These are not tables — they're saved queries that calculate automatically
# from forecast_spend. Query a view exactly like a table.
# ─────────────────────────────────────────────────────────────────────────────

print("\nViews")

run("v_spend_by_major_category", """
CREATE OR REPLACE VIEW v_spend_by_major_category AS
SELECT
    fm.id                       AS master_id,
    fv.name                     AS forecast_version,
    a.name                      AS airline,
    a.airline_category,
    a.region,
    sf.subfleet_name,
    at.model                    AS aircraft_model,
    at.category                 AS aircraft_category,
    fm.year,
    fm.fleet_count,

    -- Seats (replace + repair combined)
    COALESCE(fs.total_seats_replace,0) + COALESCE(fs.total_seats_repair,0)
        AS seats_total,
    COALESCE(fs.total_seats_replace,0) AS seats_replace,
    COALESCE(fs.total_seats_repair,0)  AS seats_repair,

    -- Soft goods
    COALESCE(fs.total_soft_goods_replace,0) + COALESCE(fs.total_soft_goods_repair,0)
        AS soft_goods_total,

    -- Seat belts
    COALESCE(fs.total_seatbelts_replace,0) + COALESCE(fs.total_seatbelts_repair,0)
        AS seatbelts_total,

    -- Panels
    COALESCE(fs.total_panels_replace,0) + COALESCE(fs.total_panels_repair,0)
        AS panels_total,

    -- Galleys
    COALESCE(fs.total_galley_inserts_replace,0) + COALESCE(fs.total_galley_inserts_repair,0)
        AS galleys_total,

    -- Lavatories
    COALESCE(fs.lavatories_replace,0) + COALESCE(fs.lavatories_repair,0)
        AS lavatories_total,

    -- Lighting
    COALESCE(fs.overhead_lighting_replace,0) + COALESCE(fs.overhead_lighting_repair,0)
        AS lighting_total,

    -- IFE/Connectivity
    COALESCE(fs.ifec_replace,0) + COALESCE(fs.ifec_repair,0)
        AS ifec_total,

    -- Engineering
    COALESCE(fs.engineering_certification,0) AS engineering_total,

    -- Summary
    COALESCE(fs.total_replace_excl_softgoods,0)  AS total_replace_excl_softgoods,
    COALESCE(fs.total_replace_incl_softgoods,0)  AS total_replace_incl_softgoods,
    COALESCE(fs.total_repair,0)                  AS total_repair,
    COALESCE(fs.total_spend,0)                   AS total_spend,
    fs.probability_weighted_spend

FROM forecast_master fm
JOIN forecast_versions fv  ON fm.forecast_version_id = fv.id
JOIN airlines a            ON fm.airline_id = a.id
JOIN subfleets sf          ON fm.subfleet_id = sf.id
JOIN aircraft_types at     ON sf.aircraft_type_id = at.id
LEFT JOIN forecast_spend fs ON fs.master_id = fm.id;
""")

run("v_spend_comparison", """
CREATE OR REPLACE VIEW v_spend_comparison AS
SELECT
    a.name              AS airline,
    at.model            AS aircraft_model,
    sf.subfleet_name,
    fm.year,
    fv.name             AS forecast_version,
    fs.total_spend
FROM forecast_master fm
JOIN forecast_versions fv  ON fm.forecast_version_id = fv.id
JOIN airlines a            ON fm.airline_id = a.id
JOIN subfleets sf          ON fm.subfleet_id = sf.id
JOIN aircraft_types at     ON sf.aircraft_type_id = at.id
LEFT JOIN forecast_spend fs ON fs.master_id = fm.id
ORDER BY a.name, at.model, sf.subfleet_name, fm.year, fv.name;
""")

run("v_spend_by_region_year", """
CREATE OR REPLACE VIEW v_spend_by_region_year AS
SELECT
    fv.name                     AS forecast_version,
    a.region,
    fm.year,
    SUM(fs.total_seats_replace + fs.total_seats_repair)     AS seats,
    SUM(fs.total_soft_goods_replace + fs.total_soft_goods_repair) AS soft_goods,
    SUM(fs.total_panels_replace + fs.total_panels_repair)   AS panels,
    SUM(fs.total_galley_inserts_replace + fs.total_galley_inserts_repair) AS galleys,
    SUM(fs.lavatories_replace + fs.lavatories_repair)       AS lavatories,
    SUM(fs.ifec_replace + fs.ifec_repair)                   AS ifec,
    SUM(fs.total_replace_excl_softgoods)                    AS total_replace_excl_softgoods,
    SUM(fs.total_replace_incl_softgoods)                    AS total_replace_incl_softgoods,
    SUM(fs.total_repair)                                    AS total_repair,
    SUM(fs.total_spend)                                     AS total_spend
FROM forecast_master fm
JOIN forecast_versions fv  ON fm.forecast_version_id = fv.id
JOIN airlines a            ON fm.airline_id = a.id
LEFT JOIN forecast_spend fs ON fs.master_id = fm.id
GROUP BY fv.name, a.region, fm.year
ORDER BY fv.name, a.region, fm.year;
""")

run("v_reaction_opportunities", """
CREATE OR REPLACE VIEW v_reaction_opportunities AS
SELECT
    ce.event_date                                   AS trigger_date,
    trigger_airline.name                            AS trigger_airline,
    ce.event_type                                   AS trigger_event_type,
    ce.cabin_class,
    target_airline.name                             AS opportunity_airline,
    target_airline.airline_category,
    target_airline.region                           AS opportunity_region,
    re.final_probability,
    re.timing_bucket,
    re.priority_band,
    re.forecast_opportunity_value_usd,
    re.recommended_action,
    re.status,
    re.week_identified
FROM reaction_events re
JOIN cabin_events ce            ON re.trigger_event_id = ce.id
JOIN airlines trigger_airline   ON ce.airline_id = trigger_airline.id
JOIN airlines target_airline    ON re.target_airline_id = target_airline.id
ORDER BY re.forecast_opportunity_value_usd DESC NULLS LAST;
""")


# ─────────────────────────────────────────────────────────────────────────────
# VERIFICATION
# ─────────────────────────────────────────────────────────────────────────────

print("\n── Verification ──────────────────────────────────────────────────────")
cur.execute("""
    SELECT table_name, table_type
    FROM information_schema.tables
    WHERE table_schema = 'public'
    ORDER BY table_type, table_name;
""")
rows = cur.fetchall()
tables = [r for r in rows if r[1] == 'BASE TABLE']
views  = [r for r in rows if r[1] == 'VIEW']
print(f"  Tables created: {len(tables)}")
for t in tables:
    print(f"    • {t[0]}")
print(f"  Views created: {len(views)}")
for v in views:
    print(f"    • {v[0]}")

cur.close()
conn.close()
print("\nDone. Your Supabase database is ready.")
