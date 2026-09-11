"""
find_airline_name_conflicts.py
Finds airline names that appear differently across the three forecast files.
Outputs a CSV you can review and edit to confirm which names should be merged.

RUN:  python find_airline_name_conflicts.py
"""

import os
import pandas as pd
from difflib import SequenceMatcher

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)               # Forecast Files/ (this script lives in scripts/)
SOURCE_DATA = os.path.join(ROOT, 'source_data')
REFERENCE = os.path.join(ROOT, 'reference')

# ── Load operator names from each file ────────────────────────────────────────

print("Loading files...")

df22 = pd.read_excel(
    os.path.join(SOURCE_DATA, '2022-2032 Air Transport Seat and Interiors MRO-Refurb Forecast Output 23Oct2023 (1).xlsb'),
    sheet_name='Interiors MRO Forecast', engine='pyxlsb', header=1,
    usecols=['Operator'])
df24 = pd.read_excel(
    os.path.join(SOURCE_DATA, '24-34 Interiors Forecast May 25 (version 1).xlsx'),
    sheet_name='Interiors MRO Forecast', usecols=['Operator'])
df26 = pd.read_excel(
    os.path.join(SOURCE_DATA, '26-35 forecast_data.xlsx'),
    sheet_name='RAW_licensed', usecols=['Operator'])

ops22 = set(df22['Operator'].dropna().str.strip().unique())
ops24 = set(df24['Operator'].dropna().str.strip().unique())
ops26 = set(df26['Operator'].dropna().str.strip().unique())

all_ops = ops22 | ops24 | ops26
in_all  = ops22 & ops24 & ops26
in_26_only = ops26 - ops22 - ops24
in_22_only = ops22 - ops24 - ops26

print(f"  2022 file: {len(ops22)} unique operators")
print(f"  2024 file: {len(ops24)} unique operators")
print(f"  2026 file: {len(ops26)} unique operators")
print(f"  In all 3 files: {len(in_all)}")
print(f"  2022 only (retired/dropped): {len(in_22_only)}")
print(f"  2026 only (new entrants): {len(in_26_only)}")
print(f"  Total unique name strings: {len(all_ops)}")

# ── Find probable duplicates via similarity matching ──────────────────────────
# An airline in one file might be a probable duplicate of one in another file
# if their names are very similar but not identical.
# We compare names that are NOT in all three files (those are definitely fine).

print("\nFinding probable duplicate names...")

# Operators that differ across files — these are the candidates
candidates = list(all_ops - in_all)

def similarity(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def is_probable_duplicate(a, b):
    """True if two names likely refer to the same airline."""
    al, bl = a.lower().strip(), b.lower().strip()
    # One is a substring of the other
    if al in bl or bl in al:
        return True
    # Very high similarity score
    if similarity(a, b) > 0.85:
        return True
    # One ends in 'Airline' or 'Airlines' and the other doesn't
    for suffix in [' airline', ' airlines', ' airways', ' air', ' aoc', ' pty ltd',
                   ' p/l', ' asa', ' inc', ' ltd', ' (nigeria)', ' sa']:
        if al.replace(suffix, '') == bl or bl.replace(suffix, '') == al:
            return True
    return False

conflicts = []
seen_pairs = set()
ops_list = sorted(candidates)

for i, a in enumerate(ops_list):
    for b in ops_list[i+1:]:
        pair = tuple(sorted([a, b]))
        if pair in seen_pairs:
            continue
        if is_probable_duplicate(a, b):
            seen_pairs.add(pair)
            # Determine which files each appears in
            files_a = ','.join([f for f, s in [('2022',ops22),('2024',ops24),('2026',ops26)] if a in s])
            files_b = ','.join([f for f, s in [('2022',ops22),('2024',ops24),('2026',ops26)] if b in s])
            conflicts.append({
                'name_a':    a,
                'files_a':   files_a,
                'name_b':    b,
                'files_b':   files_b,
                'similarity': round(similarity(a, b), 3),
                'keep':      '',   # fill in: write the name to keep, or 'both' if they're actually different
                'action':    ''    # fill in: 'merge' or 'keep_both'
            })

conflicts_df = pd.DataFrame(conflicts).sort_values('similarity', ascending=False)

out = os.path.join(REFERENCE, 'airline_name_conflicts.csv')
conflicts_df.to_csv(out, index=False)

print(f"  Found {len(conflicts_df)} probable duplicate pairs")
print(f"  Saved to: reference/airline_name_conflicts.csv")
print()
print("── Top matches ─────────────────────────────────────────────────────────")
print(conflicts_df[['name_a','files_a','name_b','files_b','similarity']].head(30).to_string(index=False))
print()
print("Next step: open airline_name_conflicts.csv, review each pair,")
print("  fill in 'keep' (the name to keep) and 'action' (merge or keep_both),")
print("  then run apply_airline_name_fixes.py to clean up the database.")
