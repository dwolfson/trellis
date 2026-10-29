# DDL record: step 8 (parked, work in progress), five columns on `database_value_profiles` (claude/re-quality-8-hashes)

**Status:** PARKED, not deployed, **not approved**. Step 8 was paused on 2026-10-29 so port step 7b could go first; this branch
keeps the work so far and is not for merge as it stands (see "What is not done"). Nothing here has run against the shared
registry (localhost:5442).

## The exact Postgres DDL

```sql
BEGIN; SET LOCAL lock_timeout = '10s'; ALTER TABLE database_value_profiles ADD COLUMN IF NOT EXISTS multiset_hash TEXT; COMMIT;
BEGIN; SET LOCAL lock_timeout = '10s'; ALTER TABLE database_value_profiles ADD COLUMN IF NOT EXISTS epoch_sum TEXT; COMMIT;
BEGIN; SET LOCAL lock_timeout = '10s'; ALTER TABLE database_value_profiles ADD COLUMN IF NOT EXISTS keyed_hash TEXT; COMMIT;
BEGIN; SET LOCAL lock_timeout = '10s'; ALTER TABLE database_value_profiles ADD COLUMN IF NOT EXISTS key_column_name TEXT; COMMIT;
BEGIN; SET LOCAL lock_timeout = '10s'; ALTER TABLE database_value_profiles ADD COLUMN IF NOT EXISTS hash_state TEXT; COMMIT;
```

Run by `ProjectRegistry._migrate_value_profile_columns`, one short transaction each. Nullable, no default: a catalog-only change.

## What each is, and what NULL means

`multiset_hash`, `epoch_sum` and `keyed_hash` are sums of 56-bit hashes (or epoch seconds) held as exact decimal text; they pass
64 bits, so they are never a BIGINT or a float. `key_column_name` is the table's inferred key. `hash_state` says whether hashes
were asked for and read: NULL (off, the default, or a row from before the columns), `taken`, `not_measured` (the read failed or
ran out of budget). NULL in a hash after `taken` means nothing was hashable. Hashes are off by default
(`VALUE_PROFILE_HASHES`, `ValueProfileSettings.value_hashes`).

## Rollback

`ALTER TABLE database_value_profiles DROP COLUMN multiset_hash, DROP COLUMN epoch_sum, DROP COLUMN keyed_hash, DROP COLUMN key_column_name, DROP COLUMN hash_state;` after stopping RE. Earlier code ignores them.

## What is not done (why this branch is parked)

The frequent-values child table and frequency analysis, and the three QUERY types (Match_Frequent_Values,
Match_Frequent_Patterns, Match_Distinct_Hash), are not built. No design note, PROVENANCE rows or sync-script check for the
hash sources yet. The 7 hash CAT types, the Postgres hash SQL (checked against TestGen's reference implementation on a real
Postgres), key inference, the opt-in profile and the check run path are built and tested.
