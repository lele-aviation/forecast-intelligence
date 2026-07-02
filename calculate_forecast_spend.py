"""
calculate_forecast_spend.py
Lele Aviation Intelligence Platform -- Forecast Spend Calculation Engine v2.0

Scope: seats, seat covers, cushions, cut&sew, carpet, curtains, flooring,
       seatbelts, IFE Replace (AVOD only).
Hard goods (galleys, panels, lav, lam, lighting) zeroed -- v2 scope.

IFE rules:
  - AVOD-Seatback / In-Flight-Entertainment / Overhead-Screen -> IFE Replace fires
  - BYOD-Streaming -> no hardware Replace (passenger owns device)
  - NULL has_ife_* -> False (unknown = conservative)
  - ife_f applies only to intl first (first_seats), NOT dom_first (baked into seat rate)
  - ife_pe applies only when biz_seats > 0 (intl PE proxy)

Fleet deduplication: fleet = fleet_count_adjusted / n_subfleets per airline+type
to avoid double-counting when multiple seat configs share the same fleet count.

RUN: python calculate_forecast_spend.py [--version-id 3] [--year 2026] [--dry-run]
"""

import os, sys, argparse, psycopg2, psycopg2.extras

def _load_db_url():
    """Load DB URL from environment variable or local .env file."""
    url = os.environ.get("LELE_DB_URL")
    if url:
        return url
    env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_file):
        for line in open(env_file):
            line = line.strip()
            if line.startswith("LELE_DB_URL=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip().strip("'\"")
    raise RuntimeError(
        "DB URL not found. Set the LELE_DB_URL environment variable, "
        "or create a .env file in the scripts folder with:\n"
        "  LELE_DB_URL=postgresql://postgres.<ref>:<password>@<host>:5432/postgres"
    )

DB_URL = _load_db_url()
WARRANTY_YEARS = 2.0

SOFT_INTERVAL = {
    'GL': 3.0, 'FSC': 4.0, 'RFSC': 4.0,
    'LCC': 4.0, 'ULCC': 5.0, 'REG': 5.0, 'LEI': 5.0, 'OTH': 4.0
}
BELT_REPLACE_INTERVAL = 6.0
IFE_REPLACE_INTERVAL  = 7.0

AVOD_IFE_TYPES = {'AVOD-Seatback', 'In-Flight-Entertainment', 'Overhead-Screen'}


# ---------------------------------------------------------------------------
def load_assumptions(cur):
    cur.execute("""
        SELECT product_code, service_type, aircraft_size_class, mod_size,
               base_cost, escalation_rate
        FROM assumptions WHERE is_active = TRUE
    """)
    rates = {}
    for code, svc, size, mod, cost, esc in cur.fetchall():
        rates[(code, svc, size, mod)] = (float(cost), float(esc))
    return rates


def get_rate(rates, code, svc, size_class=None, mod=None):
    for k in [(code, svc, size_class, mod),
              (code, svc, size_class, None),
              (code, svc, None, None)]:
        if k in rates:
            return rates[k]
    return (0.0, 0.03)


def load_retrofit_intervals(cur):
    cur.execute("SELECT aircraft_size_class, airline_category, default_retrofit_years FROM retrofit_interval_defaults")
    return {(r[0], r[1]): float(r[2]) for r in cur.fetchall()}


def load_material_defaults(cur):
    cur.execute("SELECT airline_category, cabin_class, material FROM category_material_defaults")
    mat_map = {'Fabric': 'fab', 'Leather': 'lth', 'Synthetic': 'syn'}
    return {(r[0], r[1]): mat_map.get(r[2], 'fab') for r in cur.fetchall()}


def load_forecast_rows(cur, version_id, year):
    cur.execute("""
        SELECT
            fm.id AS master_id,
            fm.fleet_count_adjusted
              / COUNT(*) OVER (
                    PARTITION BY fm.airline_id, sf.aircraft_type_id,
                                 fm.year, fm.forecast_version_id
                ) AS fleet,
            fm.avg_age, fm.year,
            a.airline_category AS category,
            a.spend_intensity,
            a.eco_material AS a_eco_mat, a.pe_material AS a_pe_mat,
            a.business_material AS a_biz_mat, a.first_material AS a_first_mat,
            at.category AS size_class,
            COALESCE(sf.seats_economy, 0) AS eco_seats,
            COALESCE(sf.seats_economy_plus, 0) AS ep_seats,
            COALESCE(sf.seats_premium_economy, 0) AS pe_seats,
            COALESCE(sf.seats_j_recliner, 0) AS j_rec_seats,
            COALESCE(sf.seats_j_lieflat, 0) AS j_lf_seats,
            COALESCE(sf.seats_first_recliner, 0) AS f_rec_seats,
            COALESCE(sf.seats_first_lieflat, 0) AS f_lf_seats,
            COALESCE(sf.seats_domestic_first, 0) AS f_dom_seats,
            COALESCE(sf.seats_total, 0) AS total_seats,
            sf.has_ife_economy, sf.ife_type_economy,
            sf.has_ife_business, sf.ife_type_business,
            sf.has_ife_first, sf.ife_type_first,
            sf.has_ife_premium_economy, sf.ife_type_premium_economy,
            sf.eco_material AS sf_eco_mat, sf.pe_material AS sf_pe_mat,
            sf.business_material AS sf_biz_mat, sf.first_material AS sf_first_mat
        FROM forecast_master fm
        JOIN airlines a ON fm.airline_id = a.id
        JOIN subfleets sf ON fm.subfleet_id = sf.id
        JOIN aircraft_types at ON sf.aircraft_type_id = at.id
        WHERE fm.forecast_version_id = %s AND fm.year = %s
          AND fm.fleet_count_adjusted IS NOT NULL AND fm.fleet_count_adjusted > 0
        ORDER BY fm.id
    """, (version_id, year))
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
def escalate(cost, esc, year, base=2026):
    return cost * (1 + esc) ** (year - base)


def material_suffix(row, cabin, mat_defaults):
    col_map = {
        'Economy':       ('sf_eco_mat',  'a_eco_mat'),
        'PremiumEconomy':('sf_pe_mat',   'a_pe_mat'),
        'Business':      ('sf_biz_mat',  'a_biz_mat'),
        'First':         ('sf_first_mat','a_first_mat'),
    }
    m2s = {'Fabric': 'fab', 'Leather': 'lth', 'Synthetic': 'syn'}
    sf_col, a_col = col_map.get(cabin, ('sf_eco_mat', 'a_eco_mat'))
    for col in (sf_col, a_col):
        v = row.get(col)
        if v and v in m2s:
            return m2s[v]
    return mat_defaults.get((row['category'], cabin), 'fab')


def ife_present(row, cabin):
    """True only when seat-back IFE hardware is recorded in DB.
    BYOD or NULL -> False (no hardware to replace)."""
    col_map = {
        'Economy': ('has_ife_economy', 'ife_type_economy'),
        'Business':('has_ife_business','ife_type_business'),
        'First':   ('has_ife_first',   'ife_type_first'),
        'PE':      ('has_ife_premium_economy','ife_type_premium_economy'),
    }
    has_col, type_col = col_map.get(cabin, ('has_ife_economy','ife_type_economy'))
    ife_type = row.get(type_col)
    has_val  = row.get(has_col)
    if ife_type is not None:
        return ife_type in AVOD_IFE_TYPES
    if has_val is not None:
        return bool(has_val)
    return False


def biz_seat_type(row):
    return 'lf' if row['j_lf_seats'] >= row['j_rec_seats'] else 'rec'


def first_seat_type(row):
    if row['f_dom_seats'] > 0 and row['f_lf_seats'] == 0 and row['f_rec_seats'] == 0:
        return 'dom'
    return 'lf' if row['f_lf_seats'] >= row['f_rec_seats'] else 'rec'


# ---------------------------------------------------------------------------
def calc_spend(row, rates, retrofit_intervals, mat_defaults):
    fleet    = float(row['fleet'])
    avg_age  = float(row['avg_age'] or 0)
    year     = int(row['year'])
    cat      = row['category'] or 'OTH'
    size     = row['size_class'] or 'Narrowbody'
    intensity = float(row['spend_intensity'] or 1.0)
    warranty = (avg_age < WARRANTY_YEARS)

    eco  = int(row['eco_seats'])
    ep   = int(row['ep_seats'])
    pe   = int(row['pe_seats'])
    jrec = int(row['j_rec_seats'])
    jlf  = int(row['j_lf_seats'])
    frec = int(row['f_rec_seats'])
    flf  = int(row['f_lf_seats'])
    fdom = int(row['f_dom_seats'])
    tot  = int(row['total_seats'])
    biz  = jrec + jlf
    first = frec + flf

    retrofit_yrs = retrofit_intervals.get((size, cat), 10.0)
    soft_yrs     = SOFT_INTERVAL.get(cat, 4.0)
    cush_yrs     = soft_yrs + 1.0

    eco_ife   = ife_present(row, 'Economy')
    biz_ife   = ife_present(row, 'Business')
    first_ife = ife_present(row, 'First')
    pe_ife    = ife_present(row, 'PE')
    biz_type  = biz_seat_type(row)
    f_type    = first_seat_type(row)
    eco_mat   = material_suffix(row, 'Economy', mat_defaults)
    biz_mat   = material_suffix(row, 'Business', mat_defaults)
    f_mat     = material_suffix(row, 'First', mat_defaults)

    def rate_val(code, svc):
        base, esc = get_rate(rates, code, svc, size)
        return escalate(base, esc, year)

    def seat_repair(code, n):
        if warranty or n <= 0:
            return 0.0
        return rate_val(code, 'Repair') * n * fleet * intensity

    def seat_replace(code, n, intv):
        if n <= 0 or intv <= 0:
            return 0.0
        return (rate_val(code, 'Replace') / intv) * n * fleet * intensity

    def ac_repair(code, intv=1.0):
        if warranty:
            return 0.0
        return (rate_val(code, 'Repair') / intv) * fleet * intensity

    def ac_replace(code, intv):
        if intv <= 0:
            return 0.0
        return (rate_val(code, 'Replace') / intv) * fleet * intensity

    # Seat codes
    eco_code = 'seat_eco_ife' if eco_ife else 'seat_eco_noife'
    ep_code  = 'seat_ep_ife'  if eco_ife else 'seat_ep_noife'
    pe_code  = 'seat_pe_ife'  if pe_ife  else 'seat_pe_noife'

    if biz_type == 'lf':
        biz_code = 'seat_b_lf_ife'
    elif biz_ife:
        biz_code = 'seat_b_rec_ife'
    else:
        biz_code = 'seat_b_rec_noife'

    if f_type == 'dom':
        f_code  = 'seat_f_dom_ife' if first_ife else 'seat_f_dom_noife'
        df_code = f_code
    elif f_type == 'lf':
        f_code  = 'seat_f_lf_ife'
        df_code = 'seat_f_dom_ife' if first_ife else 'seat_f_dom_noife'
    else:
        f_code  = 'seat_f_rec_ife' if first_ife else 'seat_f_rec_noife'
        df_code = 'seat_f_dom_ife' if first_ife else 'seat_f_dom_noife'

    # Seats
    economy_seats_repair  = seat_repair(eco_code, eco)
    economy_seats_replace = seat_replace(eco_code, eco, retrofit_yrs)
    py_seats_repair  = seat_repair(ep_code, ep) + seat_repair(pe_code, pe)
    py_seats_replace = seat_replace(ep_code, ep, retrofit_yrs) + seat_replace(pe_code, pe, retrofit_yrs)
    business_seats_repair  = seat_repair(biz_code, biz)
    business_seats_replace = seat_replace(biz_code, biz, retrofit_yrs)

    if f_type == 'dom':
        dom_first_seats_repair   = seat_repair(df_code, fdom)
        dom_first_seats_replace  = seat_replace(df_code, fdom, retrofit_yrs)
        first_seats_repair = first_seats_replace = 0.0
    else:
        first_seats_repair   = seat_repair(f_code, first)
        first_seats_replace  = seat_replace(f_code, first, retrofit_yrs)
        dom_first_seats_repair  = seat_repair(df_code, fdom)
        dom_first_seats_replace = seat_replace(df_code, fdom, retrofit_yrs)

    total_seats_repair  = (economy_seats_repair + py_seats_repair +
                           business_seats_repair + dom_first_seats_repair + first_seats_repair)
    total_seats_replace = (economy_seats_replace + py_seats_replace +
                           business_seats_replace + dom_first_seats_replace + first_seats_replace)

    # Hard goods -- cabin aircraft-level (carpet, floor, curtains)
    carpets_repair   = ac_repair('carp', 1.0)
    carpets_replace  = ac_replace('carp', soft_yrs)
    flooring_repair  = ac_repair('floor_ntf', 2.0)
    flooring_replace = ac_replace('floor_ntf', soft_yrs + 2)
    curtains_repair  = ac_repair('curt', 2.0)
    curtains_replace = ac_replace('curt', soft_yrs)

    # Seat covers (economy + EP together; PE goes to biz bucket)
    sc_eco = f'sc_eco_{eco_mat}'
    seat_covers_economy_repair  = seat_repair(sc_eco, eco + ep)
    seat_covers_economy_replace = seat_replace(sc_eco, eco + ep, soft_yrs)

    sc_biz = f'sc_b_{biz_type}_{biz_mat}'
    seat_covers_business_repair  = seat_repair(sc_biz, biz + pe)
    seat_covers_business_replace = seat_replace(sc_biz, biz + pe, soft_yrs)

    if f_type == 'dom':
        sc_f  = f'sc_f_dom_{f_mat}'
        seat_covers_dom_first_repair  = seat_repair(sc_f, fdom)
        seat_covers_dom_first_replace = seat_replace(sc_f, fdom, soft_yrs)
        seat_covers_first_repair = seat_covers_first_replace = 0.0
    else:
        sc_f   = f'sc_f_{f_type}_{f_mat}'
        sc_df  = f'sc_f_dom_{f_mat}'
        seat_covers_first_repair   = seat_repair(sc_f, first)
        seat_covers_first_replace  = seat_replace(sc_f, first, soft_yrs)
        seat_covers_dom_first_repair  = seat_repair(sc_df, fdom)
        seat_covers_dom_first_replace = seat_replace(sc_df, fdom, soft_yrs)

    # Cushions
    seat_cushions_economy_repair  = seat_repair('scush_eco', eco + ep)
    seat_cushions_economy_replace = seat_replace('scush_eco', eco + ep, cush_yrs)
    scush_biz = f'scush_b_{biz_type}'
    seat_cushions_business_repair  = seat_repair(scush_biz, biz + pe)
    seat_cushions_business_replace = seat_replace(scush_biz, biz + pe, cush_yrs)
    if f_type == 'dom':
        seat_cushions_dom_first_repair   = seat_repair('scush_f_dom', fdom)
        seat_cushions_dom_first_replace  = seat_replace('scush_f_dom', fdom, cush_yrs)
        seat_cushions_first_repair = seat_cushions_first_replace = 0.0
    else:
        scush_f = f'scush_f_{f_type}'
        seat_cushions_first_repair   = seat_repair(scush_f, first)
        seat_cushions_first_replace  = seat_replace(scush_f, first, cush_yrs)
        seat_cushions_dom_first_repair  = seat_repair('scush_f_dom', fdom)
        seat_cushions_dom_first_replace = seat_replace('scush_f_dom', fdom, cush_yrs)

    # Cut & sew (Replace only -- schema has no cut_sew_*_repair columns)
    cut_sew_economy_replace  = seat_replace('csew_eco', eco + ep, soft_yrs)
    csew_biz = f'csew_b_{biz_type}'
    cut_sew_business_replace = seat_replace(csew_biz, biz + pe, soft_yrs)
    cut_sew_dom_first_replace = seat_replace('csew_f_dom', fdom, soft_yrs)
    csew_f = f'csew_f_{f_type}' if f_type != 'dom' else 'csew_f_rec'
    cut_sew_first_replace = seat_replace(csew_f, first, soft_yrs)

    total_soft_goods_repair  = (seat_covers_economy_repair + seat_covers_business_repair +
                                seat_covers_dom_first_repair + seat_covers_first_repair +
                                seat_cushions_economy_repair + seat_cushions_business_repair +
                                seat_cushions_dom_first_repair + seat_cushions_first_repair +
                                carpets_repair + flooring_repair + curtains_repair)
    total_soft_goods_replace = (seat_covers_economy_replace + seat_covers_business_replace +
                                seat_covers_dom_first_replace + seat_covers_first_replace +
                                seat_cushions_economy_replace + seat_cushions_business_replace +
                                seat_cushions_dom_first_replace + seat_cushions_first_replace +
                                cut_sew_economy_replace + cut_sew_business_replace +
                                cut_sew_dom_first_replace + cut_sew_first_replace +
                                carpets_replace + flooring_replace + curtains_replace)

    # Seatbelts
    seatbelts_standard_repair  = seat_repair('belt_std', tot)
    seatbelts_standard_replace = seat_replace('belt_std', tot, BELT_REPLACE_INTERVAL)
    CREW = 4
    seatbelts_flight_crew_repair  = seat_repair('belt_crew', CREW)
    seatbelts_flight_crew_replace = seat_replace('belt_crew', CREW, BELT_REPLACE_INTERVAL)
    lf_seats = jlf + flf
    seatbelts_regulatory_replace = seat_replace('belt_multi', lf_seats, BELT_REPLACE_INTERVAL)
    total_seatbelts_repair  = seatbelts_standard_repair + seatbelts_flight_crew_repair
    total_seatbelts_replace = (seatbelts_standard_replace + seatbelts_flight_crew_replace +
                               seatbelts_regulatory_replace)

    # IFE system Replace (AVOD only; ife_f = intl first only; ife_pe = intl PE only)
    ife_eco_seats = (eco + ep) if eco_ife else 0
    ife_biz_seats = biz if biz_ife else 0
    ife_f_seats   = first if first_ife else 0          # NOT fdom
    ife_pe_seats  = pe if (pe_ife and biz > 0) else 0  # intl PE only
    ifec_replace = (seat_replace('ife_eco', ife_eco_seats, IFE_REPLACE_INTERVAL) +
                    seat_replace('ife_b',   ife_biz_seats, IFE_REPLACE_INTERVAL) +
                    seat_replace('ife_f',   ife_f_seats,   IFE_REPLACE_INTERVAL) +
                    seat_replace('ife_pe',  ife_pe_seats,  IFE_REPLACE_INTERVAL))
    ifec_repair = 0.0

    # Hard goods -- zeroed v1 (galleys, panels, lav, lam, lighting, monuments)
    Z = 0.0

    total_replace_excl_softgoods = total_seats_replace + total_seatbelts_replace + ifec_replace
    total_replace_incl_softgoods = total_replace_excl_softgoods + total_soft_goods_replace
    total_repair = total_seats_repair + total_soft_goods_repair + total_seatbelts_repair
    total_spend  = total_replace_incl_softgoods + total_repair

    return {
        'master_id': row['master_id'],
        'economy_seats_replace': round(economy_seats_replace, 2),
        'economy_seats_repair':  round(economy_seats_repair, 2),
        'py_seats_replace':      round(py_seats_replace, 2),
        'py_seats_repair':       round(py_seats_repair, 2),
        'business_seats_replace':round(business_seats_replace, 2),
        'business_seats_repair': round(business_seats_repair, 2),
        'dom_first_seats_replace':round(dom_first_seats_replace, 2),
        'dom_first_seats_repair': round(dom_first_seats_repair, 2),
        'first_seats_replace':   round(first_seats_replace, 2),
        'first_seats_repair':    round(first_seats_repair, 2),
        'total_seats_replace':   round(total_seats_replace, 2),
        'total_seats_repair':    round(total_seats_repair, 2),
        'carpets_replace':       round(carpets_replace, 2),
        'carpets_repair':        round(carpets_repair, 2),
        'flooring_replace':      round(flooring_replace, 2),
        'flooring_repair':       round(flooring_repair, 2),
        'curtains_replace':      round(curtains_replace, 2),
        'curtains_repair':       round(curtains_repair, 2),
        'seat_covers_economy_replace': round(seat_covers_economy_replace, 2),
        'seat_covers_economy_repair':  round(seat_covers_economy_repair, 2),
        'seat_covers_business_replace':round(seat_covers_business_replace, 2),
        'seat_covers_business_repair': round(seat_covers_business_repair, 2),
        'seat_covers_dom_first_replace':round(seat_covers_dom_first_replace, 2),
        'seat_covers_dom_first_repair': round(seat_covers_dom_first_repair, 2),
        'seat_covers_first_replace':   round(seat_covers_first_replace, 2),
        'seat_covers_first_repair':    round(seat_covers_first_repair, 2),
        'seat_cushions_economy_replace':round(seat_cushions_economy_replace, 2),
        'seat_cushions_economy_repair': round(seat_cushions_economy_repair, 2),
        'seat_cushions_business_replace':round(seat_cushions_business_replace, 2),
        'seat_cushions_business_repair': round(seat_cushions_business_repair, 2),
        'seat_cushions_dom_first_replace':round(seat_cushions_dom_first_replace, 2),
        'seat_cushions_dom_first_repair': round(seat_cushions_dom_first_repair, 2),
        'seat_cushions_first_replace':   round(seat_cushions_first_replace, 2),
        'seat_cushions_first_repair':    round(seat_cushions_first_repair, 2),
        'cut_sew_economy_replace':   round(cut_sew_economy_replace, 2),
        'cut_sew_business_replace':  round(cut_sew_business_replace, 2),
        'cut_sew_dom_first_replace': round(cut_sew_dom_first_replace, 2),
        'cut_sew_first_replace':     round(cut_sew_first_replace, 2),
        'total_soft_goods_replace':  round(total_soft_goods_replace, 2),
        'total_soft_goods_repair':   round(total_soft_goods_repair, 2),
        'seatbelts_flight_crew_replace': round(seatbelts_flight_crew_replace, 2),
        'seatbelts_flight_crew_repair':  round(seatbelts_flight_crew_repair, 2),
        'seatbelts_standard_replace':    round(seatbelts_standard_replace, 2),
        'seatbelts_standard_repair':     round(seatbelts_standard_repair, 2),
        'seatbelts_regulatory_replace':  round(seatbelts_regulatory_replace, 2),
        'total_seatbelts_replace':       round(total_seatbelts_replace, 2),
        'total_seatbelts_repair':        round(total_seatbelts_repair, 2),
        # Hard goods zeroed (v1)
        'lavatories_replace': Z, 'lavatories_repair': Z,
        'laminates_replace':  Z, 'laminates_repair':  Z,
        'panels_ceiling_replace': Z, 'panels_ceiling_repair': Z,
        'panels_sidewalls_replace': Z, 'panels_sidewalls_repair': Z,
        'panels_overhead_bins_replace': Z, 'panels_overhead_bins_repair': Z,
        'panels_latches_replace': Z, 'panels_latches_repair': Z,
        'panels_window_shades_replace': Z, 'panels_window_shades_repair': Z,
        'total_panels_replace': Z, 'total_panels_repair': Z,
        'galleys_replace': Z, 'galleys_repair': Z,
        'ovens_replace': Z, 'ovens_repair': Z,
        'coffee_makers_replace': Z, 'coffee_makers_repair': Z,
        'carts_replace': Z, 'carts_repair': Z,
        'chillers_replace': Z, 'chillers_repair': Z,
        'liquid_chillers_replace': Z, 'liquid_chillers_repair': Z,
        'total_galley_inserts_replace': Z, 'total_galley_inserts_repair': Z,
        'stowage_closets_replace': Z, 'stowage_closets_repair': Z,
        'overhead_lighting_replace': Z, 'overhead_lighting_repair': Z,
        'ifec_replace': round(ifec_replace, 2), 'ifec_repair': Z,
        'engineering_certification': Z, 'misc_parts_kits': Z,
        'total_replace_excl_softgoods': round(total_replace_excl_softgoods, 2),
        'total_replace_incl_softgoods': round(total_replace_incl_softgoods, 2),
        'total_repair': round(total_repair, 2),
        'total_spend':  round(total_spend, 2),
    }


# ---------------------------------------------------------------------------
SPEND_COLS = [
    'economy_seats_replace','economy_seats_repair',
    'py_seats_replace','py_seats_repair',
    'business_seats_replace','business_seats_repair',
    'dom_first_seats_replace','dom_first_seats_repair',
    'first_seats_replace','first_seats_repair',
    'total_seats_replace','total_seats_repair',
    'carpets_replace','carpets_repair',
    'flooring_replace','flooring_repair',
    'curtains_replace','curtains_repair',
    'seat_covers_economy_replace','seat_covers_economy_repair',
    'seat_covers_business_replace','seat_covers_business_repair',
    'seat_covers_dom_first_replace','seat_covers_dom_first_repair',
    'seat_covers_first_replace','seat_covers_first_repair',
    'seat_cushions_economy_replace','seat_cushions_economy_repair',
    'seat_cushions_business_replace','seat_cushions_business_repair',
    'seat_cushions_dom_first_replace','seat_cushions_dom_first_repair',
    'seat_cushions_first_replace','seat_cushions_first_repair',
    'cut_sew_economy_replace','cut_sew_business_replace',
    'cut_sew_dom_first_replace','cut_sew_first_replace',
    'total_soft_goods_replace','total_soft_goods_repair',
    'seatbelts_flight_crew_replace','seatbelts_flight_crew_repair',
    'seatbelts_standard_replace','seatbelts_standard_repair',
    'seatbelts_regulatory_replace',
    'total_seatbelts_replace','total_seatbelts_repair',
    'lavatories_replace','lavatories_repair',
    'laminates_replace','laminates_repair',
    'panels_ceiling_replace','panels_ceiling_repair',
    'panels_sidewalls_replace','panels_sidewalls_repair',
    'panels_overhead_bins_replace','panels_overhead_bins_repair',
    'panels_latches_replace','panels_latches_repair',
    'panels_window_shades_replace','panels_window_shades_repair',
    'total_panels_replace','total_panels_repair',
    'galleys_replace','galleys_repair',
    'ovens_replace','ovens_repair',
    'coffee_makers_replace','coffee_makers_repair',
    'carts_replace','carts_repair',
    'chillers_replace','chillers_repair',
    'liquid_chillers_replace','liquid_chillers_repair',
    'total_galley_inserts_replace','total_galley_inserts_repair',
    'stowage_closets_replace','stowage_closets_repair',
    'overhead_lighting_replace','overhead_lighting_repair',
    'ifec_replace','ifec_repair',
    'engineering_certification','misc_parts_kits',
    'total_replace_excl_softgoods','total_replace_incl_softgoods',
    'total_repair','total_spend',
]


def upsert_spend_batch(cur, spend_list):
    """Batch upsert using execute_values — ~10× faster than row-by-row."""
    if not spend_list:
        return
    cols = ['master_id'] + SPEND_COLS
    upd  = ', '.join([f"{c} = EXCLUDED.{c}" for c in SPEND_COLS])
    sql  = (f"INSERT INTO forecast_spend ({', '.join(cols)}) VALUES %s "
            f"ON CONFLICT (master_id) DO UPDATE SET {upd}")
    template = '(' + ', '.join(['%s'] * len(cols)) + ')'
    data = [[s.get(c, 0) for c in cols] for s in spend_list]
    psycopg2.extras.execute_values(cur, sql, data, template=template, page_size=500)


# ---------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser()
    p.add_argument('--version-id', type=int, default=3)
    p.add_argument('--year',       type=int, default=None)
    p.add_argument('--dry-run',    action='store_true')
    p.add_argument('--sample',     type=int, default=0)
    args = p.parse_args()

    conn = psycopg2.connect(DB_URL, connect_timeout=30)
    conn.autocommit = False
    cur = conn.cursor()

    print("Loading reference data...")
    rates     = load_assumptions(cur)
    intervals = load_retrofit_intervals(cur)
    mat_defs  = load_material_defaults(cur)
    print(f"  {len(rates)} rates | {len(intervals)} intervals | {len(mat_defs)} material defaults")

    if args.year:
        years = [args.year]
    else:
        cur.execute("SELECT DISTINCT year FROM forecast_master WHERE forecast_version_id=%s ORDER BY year",
                    (args.version_id,))
        years = [r[0] for r in cur.fetchall()]

    print(f"\nProcessing version_id={args.version_id}, years={years}")
    if args.dry_run:
        print("  ** DRY RUN -- nothing written **\n")

    grand = {}
    for year in years:
        rows = load_forecast_rows(cur, args.version_id, year)
        if args.sample:
            rows = rows[:args.sample]

        ytotal = yrepair = yreplace = 0.0
        errors = 0
        batch  = []

        for row in rows:
            try:
                s = calc_spend(row, rates, intervals, mat_defs)
                ytotal   += s['total_spend']
                yrepair  += s['total_repair']
                yreplace += s['total_replace_incl_softgoods']
                if not args.dry_run:
                    batch.append(s)
            except Exception as e:
                errors += 1
                if errors <= 5:
                    print(f"  ERROR id={row['master_id']}: {e}")

        if not args.dry_run:
            upsert_spend_batch(cur, batch)
            conn.commit()

        grand[year] = ytotal
        etag = f" | {errors} errors" if errors else ""
        print(f"  {year}: {len(rows):>5} rows | ${ytotal/1e9:.3f}B total "
              f"(repair ${yrepair/1e9:.3f}B + replace ${yreplace/1e9:.3f}B){etag}")

    print("\n-- Global totals --")
    for yr, t in sorted(grand.items()):
        print(f"  {yr}: ${t/1e9:.2f}B")

    cur.close()
    conn.close()
    print("\nDone.")


if __name__ == '__main__':
    main()
