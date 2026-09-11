"""
apply_airline_fixes.py
Lele Aviation Intelligence Platform — Airline Name Cleanup

Applies three types of fixes to the airlines table:
  1. SIMPLE MERGES   — same airline, different name formatting
                       Deletes the variant, maps old name → canonical in airline_name_map
  2. PARENT/CHILD    — subsidiaries kept as separate rows (Avianca pattern)
                       Sets parent_airline_id; maps old name variants via name_map
  3. FALSE POSITIVES — different airlines that looked similar; no action needed

RUN AFTER: 06 - Airline Name Map SQL has been run in Supabase
RUN:  python apply_airline_fixes.py
"""

import os
import sys
import psycopg2
from dotenv import load_dotenv

load_dotenv()
conn = psycopg2.connect(os.getenv("DATABASE_URL"), connect_timeout=15)
conn.autocommit = False
cur = conn.cursor()
print("Connected.\n")

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def get_id(name):
    """Return airline id for a given name, or None if not found."""
    cur.execute("SELECT id FROM airlines WHERE name = %s", (name,))
    row = cur.fetchone()
    return row[0] if row else None

def add_map(source_name, canonical_id, notes=""):
    """Insert a name alias into airline_name_map. Skips if already exists."""
    cur.execute("""
        INSERT INTO airline_name_map (source_name, canonical_airline_id, notes)
        VALUES (%s, %s, %s)
        ON CONFLICT (source_name) DO NOTHING
    """, (source_name, canonical_id, notes))

def delete_airline(airline_id):
    """Delete an airline row (safe only before forecast data is imported)."""
    cur.execute("DELETE FROM airlines WHERE id = %s", (airline_id,))

def set_parent(child_name, parent_name):
    """Set parent_airline_id on a subsidiary row."""
    child_id  = get_id(child_name)
    parent_id = get_id(parent_name)
    if child_id and parent_id:
        cur.execute("UPDATE airlines SET parent_airline_id = %s WHERE id = %s",
                    (parent_id, child_id))
        return True
    return False

merged   = 0
mapped   = 0
parented = 0
skipped  = 0

def get_id_ilike(pattern):
    """Find airline id using a ILIKE pattern (handles accent/encoding edge cases)."""
    cur.execute("SELECT id FROM airlines WHERE name ILIKE %s LIMIT 1", (pattern,))
    row = cur.fetchone()
    return row[0] if row else None

def merge(canonical, *variants, notes=""):
    """
    Simple merge: keep canonical, delete each variant, add name_map entries.
    Before deleting a variant, redirects any existing name_map references
    that pointed to it as canonical, so no foreign key violations occur.
    """
    global merged, mapped, skipped
    canon_id = get_id(canonical)
    if not canon_id:
        # Try ILIKE for accented/encoding edge cases
        canon_id = get_id_ilike(canonical)
    if not canon_id:
        print(f"  WARN: canonical '{canonical}' not found — skipping")
        skipped += 1
        return
    add_map(canonical, canon_id, "canonical self-map")
    mapped += 1
    for v in variants:
        v_id = get_id(v)
        if not v_id:
            v_id = get_id_ilike(v)
        if v_id:
            # Redirect any existing name_map entries that used this variant as canonical
            cur.execute("""UPDATE airline_name_map SET canonical_airline_id = %s
                           WHERE canonical_airline_id = %s""", (canon_id, v_id))
            # Update the source_name self-map entry if it exists
            cur.execute("""UPDATE airline_name_map SET canonical_airline_id = %s
                           WHERE source_name = %s""", (canon_id, v))
            add_map(v, canon_id, f"merged into {canonical}")
            mapped += 1
            cur.execute("DELETE FROM airlines WHERE id = %s", (v_id,))
            merged += 1
        else:
            add_map(v, canon_id, f"alias for {canonical}")
            mapped += 1

def parent_child(parent, *children):
    """
    Parent/subsidiary: set parent_airline_id on each child.
    Also map old name variants to the child's canonical name.
    """
    global parented, skipped
    parent_id = get_id(parent)
    if not parent_id:
        print(f"  WARN: parent '{parent}' not found — skipping")
        skipped += 1
        return
    for child in children:
        if isinstance(child, tuple):
            # (canonical_child_name, [list of old name variants])
            child_name, aliases = child[0], child[1]
            child_id = get_id(child_name)
            if child_id:
                cur.execute("UPDATE airlines SET parent_airline_id = %s WHERE id = %s",
                            (parent_id, child_id))
                parented += 1
                add_map(child_name, child_id, f"child of {parent}")
                for alias in aliases:
                    add_map(alias, child_id, f"old name for {child_name}, child of {parent}")
            else:
                print(f"  WARN: child '{child_name}' not found")
                skipped += 1
        else:
            child_id = get_id(child)
            if child_id:
                cur.execute("UPDATE airlines SET parent_airline_id = %s WHERE id = %s",
                            (parent_id, child_id))
                parented += 1
                add_map(child, child_id, f"child of {parent}")
            else:
                print(f"  WARN: child '{child}' not found")
                skipped += 1


# ─────────────────────────────────────────────────────────────────────────────
# 1. SIMPLE MERGES
# Format: merge(canonical_name, variant1, variant2, ...)
# The canonical name STAYS in the airlines table.
# All variants are DELETED and mapped to the canonical.
# ─────────────────────────────────────────────────────────────────────────────

print("── Simple merges ─────────────────────────────────────────────────────")

# Key airlines (important to get right)
merge('Emirates',                        'Emirates Airline')
merge('All Nippon Airways',              'All Nippon Airways (ANA)')
merge('Cathay Pacific Airways',          'Cathay Pacific')
merge('Korean Air Lines',                'Korean Air')
merge('Turkish Airlines (Turk Hava Yollari)', 'Turkish Airlines')

# Case / spacing differences
merge('Smartwings',        'SmartWings')
merge('Tuifly',            'TUIfly')
merge('TUS Airways',       'Tus Airways')
merge('CommuteAir',        'CommutAir', 'Commutair')
merge('avianca',           'Avianca')
merge('Transnusa Air Service',     'TransNusa Air Services')
merge('Arkia Israel Airlines',     'Arkia Israeli Airlines')
merge('Euro Atlantic Airways',     'euroAtlantic airways')
merge('Blue Bird Airways',         'Bluebird Airways')
merge('Bristow Helicopters Nigeria','Bristow Helicopters (Nigeria)')
merge('Eurowings Europe [Malta]',  'Eurowings Europe Malta')
merge('Gazprom Avia',              'Gazpromavia')
merge('air Baltic',                'airBaltic')
merge('Serene Air',                'SereneAir')
merge('Mocambique Expresso',       'Moçambique Expresso')
merge('Star Flyer',                'StarFlyer')
merge('Salam Air',                 'SalamAir')
merge('Tunis Air',                 'Tunisair')
merge('Fly Egypt',                 'FlyEgypt')
merge('Air Japan',                 'AirJapan')
merge('Malawian Airlines',         'Malawi Airlines')
merge('Compagnie Africaine D\'aviation', 'Compagnie Africaine d\'Aviation CAA')
merge('Druk Air',                  'Drukair')
merge('Jet2.com',                  'Jet2Com')
merge('Aer Lingus (UK)',           'Aer Lingus UK')
merge('Australian Corporate Jet Centres Pty Ltd', 'Australian Corporate Jet Centres P/L')
merge('Norwegian Air Shuttle',     'Norwegian Air Shuttle AOC', 'Norwegian Air Shuttle ASA')
merge('Norwegian Air Sweden',      'Norwegian Air Sweden AOC')
merge('TUI Airlines Netherlands',  'Tui Airlines Nederland')
merge('Xe Jet',                    'Xejet')
merge('Air Algerie',               'Air Algérie')
merge('Airlink [South Africa]',    'Airlink (South Africa)')
merge('Comair [South Africa]',     'Comair (South Africa)')
merge('Chair Airlines',            'Chair Airlines AG')
merge('Tuifly Nordic',             'TUIfly Nordic AB')
merge('Ata Airlines [Iran]',       'ATA Airlines (Iran)')
merge('National Airlines [USA]',   'National Airlines (US)')
merge('Hillwood Airways',          'Hillwood Airways LLC')
merge('Azerbaijan Airlines',       'Azerbaijan Airlines AZAL')
merge('Smartwings Poland',         'SmartWings Polska')
# Air Côte d'Ivoire — use keyword search to bypass accent encoding issues
cur.execute("SELECT id, name FROM airlines WHERE name ILIKE '%ivoire%' ORDER BY name")
_ivoire_rows = cur.fetchall()
if len(_ivoire_rows) >= 1:
    # Use the first result (whichever form is in the DB) as canonical
    _ivoire_id, _ivoire_name = _ivoire_rows[0]
    add_map(_ivoire_name, _ivoire_id, 'canonical self-map')
    mapped += 1
    for _id, _name in _ivoire_rows[1:]:
        cur.execute("UPDATE airline_name_map SET canonical_airline_id = %s WHERE canonical_airline_id = %s",
                    (_ivoire_id, _id))
        add_map(_name, _ivoire_id, f'merged into {_ivoire_name}')
        mapped += 1
        cur.execute("DELETE FROM airlines WHERE id = %s", (_id,))
        merged += 1
merge('Star Air [India]',          'Star Air (India)')
merge('Cebu Pacific Air',          'Cebu Pacific')
merge('Aeropostal Alas De Venezolana', 'Aeropostal, Alas De Venezuela S.A.')
merge('Rvr Air Charter',           'RVR Aircraft Charter')
merge('Chabahar Air',              'Chabahar Airline')
merge('TUI Airways',               'TUI Airways Ltd')
merge('Skywest Airlines [USA]',    'SkyWest Airlines')
merge('Spirit Airlines [USA]',     'Spirit Airlines')
merge('Firefly',                   'Flyfirefly')
merge('Blue Bird Aviation [Sudan]','Blue Bird Aviation')
merge('Juneyao Airlines',          'Juneyao Air')
merge('Urumqi Airlines',           'Urumqi Air')
merge('Skymark Airlines [Japan]',  'Skymark Airlines')
merge('Piedmont Airlines [Md-USA]','Piedmont Airlines')
merge('Meraj Airlines',            'Meraj Air')
merge('Virgin Australia Airlines', 'Virgin Australia')
merge('Garuda Indonesia',          'Garuda Indonesian Airways')
merge('Jettime',                   'Jettime A/S')
merge('Eva Airways',               'EVA Air')
merge('Smartlynx Airlines Malta',  'SmartLynx Malta')
merge('Royal Jordanian Airlines',  'Royal Jordanian')
merge('United Nigeria Airlines',   'United Nigeria')
merge('Eastern Airways [UK-1998]', 'Eastern Airways')
merge('Taban Air Lines',           'Taban Air')
merge('Legend Airlines [Romania]', 'Legend Airlines')
merge('Air Wisconsin Airlines',    'Air Wisconsin')
merge('Nok Air',                   'Nok Airlines')
merge('Trigana Air Service',       'Trigana Air')
merge('Sky Airline',               'SKY Airline (Chile)')
merge('Mauritania Airlines International', 'Mauritania Airlines')
merge('Royal Flight Airlines',     'Royal Flight')
merge('Spring Airlines Japan',     'Spring Japan')
merge('Envoy Air',                 'Envoy')
merge('Horizon Air [Wa-USA]',      'Horizon Air')
merge('Sky Express [Greece]',      'Sky Express')
merge('Pan Europeenne',            'Pan Europeenne Air Service')
merge('Lucky Air [China]',         'Lucky Air')
merge('Air Caraibes Atlantique',   'Air Caraibes')
merge('Fly Play',                  'PLAY')
merge('Transavia Airlines',        'Transavia')
merge('Southwind Airlines',        'Southwind')
merge('Smartavia Airlines',        'Smartavia')
merge('Hi Fly',          'Hi Fly Malta', 'Hi Fly [Malta]', 'Hi Fly [Portugal]')
merge('RwandAir',                  'Rwandair Express')
merge('Colorful Guizhou Airlines', 'Colorful Guizhou Airlines (Duocai Guizhou Airlines)')
merge('Atlantic Airways [Faeroe Islands]', 'Atlantic Airways')
merge('Air Peace [Nigeria]',       'Air Peace')
merge('Buraq Air Transport',       'Buraq Air')
merge('Airnorth Regional',         'Airnorth')
merge('Thai Airways International','Thai Airways')
merge('Citilink Indonesia',        'Citilink')
merge('Vueling Airlines',          'Vueling')
merge('Vistara',                   'Vistara Airlines')
merge('Volotea Airlines',          'Volotea')
merge('Go2Sky Airline',            'Go2Sky')
merge('Fly540 [Kenya]',            'Fly540')
merge('Cyprus Airways',            'Cyprus Airways (Charlie Airlines)')
merge('Air Europa',                'Air Europa Líneas Aéreas')
merge('Max Air (Nigeria)',         'Max Air')
merge('Air Nostrum',               'Iberia Regional Air Nostrum')
merge('People\'s Vienna Line',     'People\'s')
merge('Lion Air [Indonesia]',      'Lion Air')
merge('Zhejiang Loong Airlines',   'Loong Air')
merge('Congo Airways [Democratic Republic]', 'Congo Airways')
merge('Calm Air International',    'Calm Air')
merge('Skyup Airlines',            'SkyUp')
merge('Scoot',                     'Scoot Tigerair')
merge('Sarpa Colombia',            'SARPA')
merge('Peach Aviation',            'Peach')
merge('Gojet Airlines',            'GoJet')
merge('Condor',                    'Condor Flugdienst')
merge('Estelar Latinoamerica',     'Estelar')
merge('Aeroflot',                  'Aeroflot Russian Airlines')
merge('Jazz Aviation',             'Jazz')
merge('SCAT Airlines',             'SCAT')
merge('Uni Air',                   'Uni Airways Corporation')
merge('Aurora Airlines [Russia]',  'Aurora')
merge('Taag Angola Airlines',      'TAAG')
merge('Gol Linhas Aereas',         'GOL')
merge('Azul Linhas Aereas Brasileiras', 'Azul')
merge('Swiss International Air Lines', 'SWISS')
merge('Wizz Air Hungary',          'Wizz Air')
merge('Easyjet Europe Airline',    'easyJet Europe')
# Smartwings Slovakia — no variants, just ensure it exists in name_map
_ss_id = get_id('Smartwings Slovakia')
if _ss_id:
    add_map('Smartwings Slovakia', _ss_id, 'canonical self-map')
    mapped += 1

# Avianca group — parent is lowercase 'avianca' (rebranded post-2021)
merge('Avianca-Ecuador',           'Avianca Ecuador')

conn.commit()
print(f"  Merges applied: {merged} deleted, {mapped} mapped\n")


# ─────────────────────────────────────────────────────────────────────────────
# 2. PARENT / SUBSIDIARY LINKS (Avianca pattern)
# Both rows kept in airlines table. parent_airline_id set on subsidiary.
# ─────────────────────────────────────────────────────────────────────────────

print("── Parent / subsidiary links ─────────────────────────────────────────")

# Avianca group
parent_child('avianca',
    'Avianca-Ecuador',
    'Avianca Costa Rica',
)

# SAS group
parent_child('Scandinavian Airlines System',
    'Scandinavian Airlines Ireland',
    'SAS Connect',
)

# SmartWings group
parent_child('Smartwings',
    'Smartwings Poland',
    'Smartwings Slovakia',
    'SmartWings Hungary',
)

# Wizz Air group (Wizz Air Hungary is the main entity; others are siblings)
parent_child('Wizz Air Hungary',
    # No current siblings in DB, but structure is in place for future
    # Wizz Air UK, Wizz Air Abu Dhabi would go here when added
)

# TUI group
parent_child('Tuifly',
    'Tuifly Nordic',
    'TUI Airlines Netherlands',
    'TUI Airways',
)

# Batik Air group (Lion Air ecosystem)
parent_child('Lion Air [Indonesia]',
    'Batik Air (Malaysia)',
    'Batik Air (Indonesia)',
)
# Map "Batik Air" (2026 name) to Batik Air (Indonesia) — the Indonesian entity
ba_indo_id = get_id('Batik Air (Indonesia)')
if ba_indo_id:
    add_map('Batik Air', ba_indo_id, 'Batik Air 2026 name maps to Indonesian entity')

conn.commit()
print(f"  Parent/child links set: {parented}\n")


# ─────────────────────────────────────────────────────────────────────────────
# 3. VERIFICATION
# ─────────────────────────────────────────────────────────────────────────────

print("── Verification ──────────────────────────────────────────────────────")

cur.execute("SELECT COUNT(*) FROM airlines")
airline_count = cur.fetchone()[0]

cur.execute("SELECT COUNT(*) FROM airline_name_map")
map_count = cur.fetchone()[0]

cur.execute("SELECT COUNT(*) FROM airlines WHERE parent_airline_id IS NOT NULL")
child_count = cur.fetchone()[0]

print(f"  Airlines in table:      {airline_count}")
print(f"  Name map entries:       {map_count}")
print(f"  Airlines with parent:   {child_count}")
print(f"  Skipped (not found):    {skipped}")

# Spot-check Emirates
cur.execute("SELECT id, name FROM airlines WHERE name ILIKE '%emirates%'")
rows = cur.fetchall()
print(f"\n  Emirates check: {len(rows)} row(s)")
for r in rows:
    print(f"    ID {r[0]}: {r[1]}")

# Spot-check Avianca group
cur.execute("""
    SELECT a.name, p.name AS parent
    FROM airlines a
    LEFT JOIN airlines p ON a.parent_airline_id = p.id
    WHERE a.name ILIKE '%avianca%' OR p.name ILIKE '%avianca%'
    ORDER BY p.name NULLS LAST, a.name
""")
rows = cur.fetchall()
print(f"\n  Avianca group: {len(rows)} row(s)")
for r in rows:
    print(f"    {r[0]}  (parent: {r[1] or 'none'})")

cur.close()
conn.close()
print("\nDone.")
