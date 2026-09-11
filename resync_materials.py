#!/usr/bin/env python3
"""
resync_materials.py  —  one-command material re-sync loop.

After you add/validate rows in the cabin_material master, this:
  1. BACKS UP forecast_spend (timestamped .csv.gz)
  2. SYNCS subfleets.{eco,pe,business,first}_material  <-  cabin_material (airline grain)
  3. RECOMPUTES the platform forecast_spend (calculate_forecast_spend.py, live v3)
  4. (optional) RE-RUNS the Insperial WS5 model + workbook on the new materials
and prints a before/after summary + confidence coverage.

Paths are resolved relative to THIS file, so it works in any session.

USAGE
  python resync_materials.py --dry-run          # preview only, no writes
  python resync_materials.py                     # steps 1-3 (backup, sync, engine recompute)
  python resync_materials.py --insperial         # also refresh Insperial WS5 (step 4)
  python resync_materials.py --skip-engine       # sync only (e.g. quick Insperial-only refresh with --insperial)
"""
import os, sys, gzip, argparse, subprocess, datetime, csv
import psycopg2
from collections import defaultdict

SCRIPTDIR = os.path.dirname(os.path.abspath(__file__))                      # .../Projects/Forecast Files/scripts
ROOT      = os.path.abspath(os.path.join(SCRIPTDIR, "..", "..", ".."))       # .../00_Cowork_HQ
ENGINE    = os.path.join(SCRIPTDIR, "calculate_forecast_spend.py")
INSP_BUILD= os.path.join(ROOT, "Outputs", "Insperial_Phase1_2026-07-21", "_build_2026-08-24_observed")
BACKUPDIR = os.path.join(ROOT, "Outputs", "Cabin_Material_Master_2026-08-24", "backups")
VERSION_ID= 3
COLMAP={'Economy':'eco_material','PremiumEconomy':'pe_material','Business':'business_material','First':'first_material'}

def db_url():
    for line in open(os.path.join(SCRIPTDIR, ".env")):
        if line.strip().startswith("LELE_DB_URL="):
            return line.split("=",1)[1].strip().strip("'\"")
    raise SystemExit("LELE_DB_URL not found in scripts/.env")

def spend_by_year(cur):
    cur.execute("""SELECT fm.year, round(sum(fs.total_spend)/1e9,3)
        FROM forecast_spend fs JOIN forecast_master fm ON fs.master_id=fm.id
        WHERE fm.forecast_version_id=%s GROUP BY 1 ORDER BY 1""",(VERSION_ID,))
    return dict(cur.fetchall())

def confidence_coverage(cur):
    cur.execute("""SELECT fm.airline_id, sf.id,
        COALESCE(sf.seats_economy,0)+COALESCE(sf.seats_economy_plus,0),COALESCE(sf.seats_premium_economy,0),
        COALESCE(sf.seats_j_recliner,0)+COALESCE(sf.seats_j_lieflat,0),
        COALESCE(sf.seats_first_recliner,0)+COALESCE(sf.seats_first_lieflat,0)+COALESCE(sf.seats_domestic_first,0),
        fm.fleet_count_adjusted
        FROM forecast_master fm JOIN subfleets sf ON fm.subfleet_id=sf.id
        WHERE fm.forecast_version_id=%s AND fm.year=2026""",(VERSION_ID,))
    seats=defaultdict(lambda:defaultdict(float))
    for aid,sfid,eco,pe,biz,fr,fca in cur.fetchall():
        f=float(fca or 0)
        for cab,v in (('Economy',eco),('PremiumEconomy',pe),('Business',biz),('First',fr)): seats[aid][cab]+=v*f
    cur.execute("SELECT airline_id,cabin_class,confidence FROM cabin_material WHERE cabin_class<>'All'")
    conf=defaultdict(float)
    for aid,cab,cf in cur.fetchall(): conf[cf]+=seats.get(aid,{}).get(cab,0.0)
    tot=sum(conf.values()) or 1
    return {k:f"{conf[k]/tot*100:.0f}%" for k in ('Observed','Inferred','Default')}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--dry-run',action='store_true')
    ap.add_argument('--insperial',action='store_true',help='also re-run Insperial WS5 model+workbook')
    ap.add_argument('--skip-engine',action='store_true',help='skip forecast_spend recompute')
    a=ap.parse_args()
    url=db_url(); c=psycopg2.connect(url); c.autocommit=False; cur=c.cursor()
    print(f"resync_materials  {'(DRY RUN)' if a.dry_run else ''}\nroot: {ROOT}\n")

    print("cabin_material coverage (by 2026 installed seats):", confidence_coverage(cur))
    before=spend_by_year(cur)

    # STEP 1 backup
    if not a.dry_run:
        os.makedirs(BACKUPDIR,exist_ok=True)
        ts=datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        bp=os.path.join(BACKUPDIR,f"forecast_spend_{ts}.csv.gz")
        with gzip.open(bp,'wt') as f: cur.copy_expert("COPY forecast_spend TO STDOUT WITH CSV HEADER",f)
        print(f"[1] backup -> {bp} ({os.path.getsize(bp)/1e6:.1f} MB)")
    else:
        print("[1] backup skipped (dry-run)")

    # STEP 2 sync subfleets <- cabin_material
    tot=0
    for cabin,col in COLMAP.items():
        q=(f"UPDATE subfleets sf SET {col}=cm.material_type "
           f"FROM (SELECT airline_id,material_type FROM cabin_material WHERE cabin_class=%s AND subfleet_id IS NULL) cm "
           f"WHERE sf.airline_id=cm.airline_id AND sf.valid_to IS NULL")
        if a.dry_run:
            cur.execute(f"SELECT count(*) FROM subfleets sf JOIN "
                        f"(SELECT airline_id,material_type FROM cabin_material WHERE cabin_class=%s AND subfleet_id IS NULL) cm "
                        f"ON sf.airline_id=cm.airline_id WHERE sf.valid_to IS NULL AND sf.{col} IS DISTINCT FROM cm.material_type",(cabin,))
            print(f"[2] {col}: {cur.fetchone()[0]} would change")
        else:
            cur.execute(q,(cabin,)); print(f"[2] {col}: {cur.rowcount} subfleets synced")
    if not a.dry_run: c.commit()
    c.close()

    # STEP 3 engine recompute
    if a.skip_engine:
        print("[3] engine recompute skipped (--skip-engine)")
    else:
        cmd=[sys.executable,ENGINE,"--version-id",str(VERSION_ID)]+(["--dry-run"] if a.dry_run else [])
        print(f"[3] {'DRY-RUN ' if a.dry_run else ''}recomputing forecast_spend ...")
        subprocess.run(cmd,check=True)

    # STEP 4 Insperial refresh
    if a.insperial:
        print("[4] re-running Insperial WS5 model + workbook ...")
        subprocess.run([sys.executable,os.path.join(INSP_BUILD,"build_insperial_model.py")],cwd=INSP_BUILD,check=True)
        subprocess.run([sys.executable,os.path.join(INSP_BUILD,"build_workbook.py")],cwd=INSP_BUILD,check=True)
        print(f"    workbook -> {os.path.join(INSP_BUILD,'Insperial_Phase1_Forecast_Workbook_DRAFT.xlsx')}")
        print("    NEXT (manual): recalc.py the workbook, then copy to a dated deliverable name.")
    else:
        print("[4] Insperial refresh skipped (use --insperial)")

    # summary
    if not a.dry_run and not a.skip_engine:
        c=psycopg2.connect(url); cur=c.cursor(); after=spend_by_year(cur); c.close()
        print("\nforecast_spend total $B by year (before -> after):")
        for y in sorted(after): print(f"  {y}: {before.get(y,0):.3f} -> {after[y]:.3f}")
    print("\nDone.")

if __name__=='__main__':
    main()
