# Forecast snapshots

Point-in-time freezes of the model, so a bespoke engagement's report stays reproducible while the live
forecast keeps moving. Built 2026-09-11 (workstream W2).

Referenced from `ARCHITECTURE.md`. This file covers the snapshot subsystem only — everything about how
the model itself works stays in ARCHITECTURE.md.

## Why

Three arms, two contradictory needs. **Hōkū** wants the live model — continuous updates are the
product. **Bespoke consulting** wants the model frozen at kickoff, because a client report must still
be defensible months later. Insperial Phase 1 kicked off 2026-07-21 and the model moved four times
underneath it (airline cleanup 08-04, observed materials 08-24, v9 deliveries 08-25, laminates and
placards 09-08) with the headline moving $1,609M → $1,688M → $2,050M. Nothing could assert what the
report rested on.

Snapshots resolve that without slowing the live model down.

## Schema

`snapshots` schema, entirely additive — no public table was altered.

| Object | What it is |
|---|---|
| `snapshots.snapshot_registry` | One row per snapshot: label, purpose, engagement, the live version captured, engine commit, timestamp, notes, and a `row_counts` jsonb |
| `snapshots.forecast_master` | Frozen outputs, scoped to the live version at capture |
| `snapshots.forecast_spend` | " |
| `snapshots.forecast_cabin_age` | " |
| `snapshots.subfleets` | Frozen inputs — the configurations the outputs rest on |
| `snapshots.assumptions` | Frozen inputs — the prices |
| `snapshots.product_catalog` | " |
| `snapshots.retrofit_baseline` | " |

Every copy carries `snapshot_id` referencing the registry, `on delete cascade`. Column sets mirror the
live tables via `LIKE`, so a snapshot query looks like a live query with one extra predicate.

Inputs are captured alongside outputs deliberately: reproducing a number is not the same as being able
to answer "why was this seat priced at that?". Defensibility needs both.

## Taking a snapshot

```sql
select snapshots.take_snapshot(
  p_label         => 'acme-phase1-2026-11-03',      -- unique, kebab-case, dated
  p_purpose       => 'client_engagement',            -- or 'annual_lock' | 'ad_hoc'
  p_engagement    => 'Acme Phase 1 — galley retrofit sizing',
  p_engine_commit => '<git rev-parse HEAD>',
  p_notes         => 'Baseline for the engagement. Engine scope at capture: ...'
);
```

Returns the new `snapshot_id`. The function reads `forecast_versions.is_live` — it never hardcodes a
version, and raises if no version is live.

Record the engine commit. Without it you know *what* the model said but not *which logic* produced it,
and that is exactly the gap that made engine v2.0's hard-goods scope invisible for three months.

## Using a snapshot

```sql
-- decade total as the engagement saw it
select sum(total_spend) from snapshots.forecast_spend where snapshot_id = 1;

-- what changed since the baseline
select round(sum(l.total_spend) - sum(s.total_spend)) as drift_usd
from   public.forecast_spend l
join   snapshots.forecast_spend s
       on s.master_id = l.master_id and s.snapshot_id = 1;

-- the prices the report quoted
select product_code, service_type, aircraft_size_class, base_cost
from   snapshots.assumptions where snapshot_id = 1 and product_code = 'sc_eco_lth';
```

Client build scripts should read `snapshots.*` with a pinned `snapshot_id`, never `public.*`. That is
what keeps a deliverable stable, and it is the mechanism behind the rule that **client work never
writes to shared tables** (W3).

## When to take one

| Trigger | Purpose | Label |
|---|---|---|
| Bespoke engagement kickoff | `client_engagement` | `<client>-<phase>-<date>` |
| Annual lock, by 11/30 | `annual_lock` | `lock-<start>-<end>` |
| Before a large model change | `ad_hoc` | `pre-<change>-<date>` |

The annual lock is the one to watch: `forecast_versions` 1 (2022) and 2 (2024) hold **zero**
`forecast_master` rows, so the lock mechanism has never actually carried data. The 2027–2036 lock due
2026-11-30 is its first real exercise — snapshot before and after.

## Existing snapshots

| id | label | taken | purpose |
|---|---|---|---|
| 1 | `insperial-phase1-2026-09-11` | 2026-09-11 | Insperial Phase 1 baseline |

Snapshot 1 captured 36,176 forecast_master · 33,496 forecast_spend · 34,212 forecast_cabin_age ·
3,631 subfleets · 510 assumptions · 92 product_catalog · 3,631 retrofit_baseline, at
`total_spend = $93,560,635,880`. Engine v2.0 scope: hard goods zeroed (W4 pending), and the laminates
and placards values in `forecast_spend` are **Insperial client patches at Insperial cost inputs**, not
engine output (W3).

21 July was not recoverable — no history existed before this subsystem. The engagement re-bases onto
this baseline; the July-to-September drift is documented in the WS refresh notes only.

## Cost

~108k rows per snapshot. Negligible at this scale. If it ever matters, drop a snapshot with
`delete from snapshots.snapshot_registry where id = <n>` — the cascade clears the copies.
