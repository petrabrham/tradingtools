# CSV Import Compatibility Notes

## GUI synchronization and current-run conflicts

- **File > Read transactions from Trading212...** uses verified annual archives
  and the same importer as manual CSV import. **Options > Trading212 connection...**
  manages the account binding, first year, archive folder and native Windows
  credentials. The account is verified before saving.
- Manual CSV imports never request or fill account metadata and never show
  account-confirmation prompts, whether the database is empty, populated or bound.
  First API setup of a populated, unbound database requires explicit confirmation
  that its unidentified transactions belong to the verified account/environment.
  This includes databases containing only trades, interest, dividends or fees.
  Declining saves neither the binding nor credentials. Empty databases and
  same-account settings changes need no extra account confirmation.
  Saving rechecks the database state; API account/environment mismatches are
  errors, never an overridable confirmation.
- Saved connections with a configured local archive root start normal
  synchronization directly, without a repeated setup/refresh question.
  When setup is shown, the archive folder is loaded from this computer's
  `config.json`; the dialog does not recover or adopt a path from the database.
  For an existing account binding, it identifies the credential pair with the
  first 12 hexadecimal characters of a domain-separated SHA-256 of the API key.
  Neither key nor secret is displayed. Blank fields reuse the saved pair; enter
  both values to replace it. The fingerprint distinguishes local credentials,
  but only account verification confirms the broker still accepts the key.
  New credentials are verified once and then stored for that verified account;
  storing them does not repeat the account-summary request. A rate-limited
  account-summary GET is retried at most twice, honoring `Retry-After` or the
  endpoint's bounded fallback delay. Invalid credentials and other HTTP errors
  are not retried.
  **File > Refresh older Trading212 years...** separately
  offers a clickable year list when an explicit historical refresh is needed.
- Report metadata timestamps are matched at the broker's observed millisecond
  precision when sub-millisecond digits were truncated. Requests, archive bounds
  and exact CSV coverage validation are not altered; different milliseconds,
  content or conflicting higher-precision timestamps remain errors.
- Schema remains **2**. Existing `settings` stores only non-secret connection
  details and compact versioned import status/counts per year and CSV hash.
  Connection metadata format 2 contains environment, account ID, first year and
  timezone, never an archive path. The shared machine-local root is stored in
  `config.json` under `trading212_archive_directory` and applies to all accounts,
  whose archives retain separate environment/account subfolders.
  Legacy format-1 bindings are readable but their paths are ignored. They are
  rewritten without the path on connection save or after successful account
  verification during sync. Missing local configuration opens setup before any
  synchronization; the old database path is never adopted automatically.
  Changing the root does not relocate existing archives.
  Running/partial/cancelled/failed reports are retried; a completed unchanged
  revision is skipped unless explicitly refreshed.
- Progress, cancellation and competing-operation guards apply to API imports.
  Closing the progress window leaves the app open; closing the main window waits
  for worker cleanup before normal exit. Committed rows and archives are retained.
- Row conflicts and unsupported actions produce a partial result and do not stop
  later years. Fatal account/archive/database failures stop synchronization.
  Missing exchange rates remain row errors, with no change of rate mode or zero
  substitution. Add the required rates and retry the retained CSV.
- Both import paths provide **View last import conflicts...**: read-only
  source/DB comparisons, all identified candidates, recorded original snapshots,
  and expected stored values only where already computed. Raw foreign-currency
  totals are not directly compared with CZK totals; unavailable values are not zero.
- Comparisons exist only in memory until the next import, database switch/release
  or exit. No conflict table, raw-row settings, permanent dismissal or correction
  controls are added. Restarting loses the list; reimport reconstructs it.
- The result distinguishes full-year/year-to-date archive coverage from complete/
  partial/cancelled/failed **import**, and shows per-category read/added counts,
  duplicates, unsupported actions, intentional skips and errors/conflicts.

## Recovery from annual archives

- Prefer a full database backup when pairings, locks, notes and settings must
  survive. CSV archives reconstruct transactions, not the complete application
  state or account binding.
- Restore the whole archive including `archive.json`. Use
  `Trading212API(environment, account_id=...).get_archived_csvs(root)` to verify
  metadata/hashes and select one recommended revision per year without API
  credentials or network access. Import only those files, oldest year first,
  through the existing manual CSV importer.
- Reuse the original daily/annual conversion mode and the same exchange rates.
  Annual rate tables must be imported separately; daily CNB lookup normally
  needs network access unless its rate provider already has the required data.
- The synthetic recovery regression covers both rate modes, revised archives,
  buys, sells, both interest types, dividend gross/net/withholding values,
  trade tax and signed ADR fees. It compares all transaction rows and explicit
  CZK totals with a clean import, then checks repeated imports add nothing.
- Unsupported actions and deliberately ignored cash movements remain visible
  in the import result. `Dividend adjustment` still means partial, not complete.
- On Windows, atomic archive-metadata replacement retries only access/sharing
  errors (WinError 5/32/33), at most three retries. Each retry logs a warning;
  persistent or other disk errors fail explicitly, preserve old metadata and
  clean up the temporary file. No export POST is repeated by this write retry.

## Broker export 2026

- Import supports both time column variants:
  - `Time`
  - `Time (UTC)`
- `ADR Fee` uses `Total` and `Currency (Total)` as its original amount/currency.
  `Total (Account CCY)` is not used as a fallback: its currency must not be
  inferred to be CZK. Missing required amount/currency is an explicit row error.

## Ignored transaction actions

The importer already ignores selected actions and does not store them in the database.

Current "insignificant" actions:
- `Deposit`
- `Currency conversion`
- `Card debit`
- `Withdrawal`
- `Result adjustment`

Any other unsupported action is treated as unknown, logged, and skipped.

Example action seen in 2026 export that is currently skipped as unknown:
- `Dividend adjustment`

## Notes

- This behavior is currently expected and intentional.
- Other standalone fee types require an explicit mapping before they can be imported.

## Standalone ADR fees

- Schema 2 includes `fees` with type `FeeType.ADR`, timestamp, nullable instrument,
  signed original amount/currency and signed `total_czk`. It is created both for
  new databases and within the existing backed-up 1 -> 2 migration. No schema 3
  or automatic copying from trade-fee fields is introduced.
- Only `ADR Fee` is recognized as a standalone fee. Its exported sign is preserved
  and the selected daily/annual conversion method supplies its CZK value.
  A missing instrument, broker ID, share count or price is allowed.
- Optional share/price detail is part of the canonical source when available;
  broker-computed account totals are not identity or conversion inputs.
- Fee rows use shared source identities and immutable snapshots, not a unique
  timestamp/instrument constraint. Different IDs may identify separate events.
  Same-ID changes, local edits, ambiguous no-ID matches and indistinguishable
  groups containing missing IDs are conflicts, not silently discarded fees.
  An anonymous singleton repeated in separate files is treated as a duplicate.
- Category `fee` appears in read/added/duplicate/failed counts and the existing
  import-result message. A fee, its new security and its source commit together.
- Historical ignored rows are not recovered by schema migration. Reimport the
  CSV to add them. Source reconciliation can link already stored fee rows with
  confirmed timezones, but reports a conflict instructing normal import when no
  historical fee record exists.
- No new GUI view/menu or financial/tax aggregation is provided. Fees on trades
  remain only on trades, and `Dividend adjustment` is not treated as a fee.

## Identity and historical time reconciliation (schema 2)

- Source identity includes the action, original source time, ISIN, shares,
  price/currency, total/currency, applicable tax/fees, and interest type.
  Display names, tickers, and broker export exchange-rate precision are not identity.
- A broker ID is preferred when present. Distinct IDs can identify legitimate
  same-time dividends; the old timestamp/ISIN uniqueness is no longer sufficient.
  A unique unchanged anonymous dividend can acquire its ID in a later export.
- Same-ID content changes, edited local records, multiple possible matches, and
  repeated indistinguishable dividend rows without complete IDs are explicit
  conflicts. They are included in `errors` and separately in `conflicts`.
  The manual import summary displays the conflict count.
- Original CSV source evidence and the transaction are committed atomically per
  row. Cancellation or an error does not leave an inserted row without its identity.
- A legacy `Time` without an offset keeps its original local-time interpretation
  on initial import. A later aware UTC source may prove the time-only correction
  described below; proximity alone never proves a timezone correction.
- For cases without that proof, use the original CSV with
  `DatabaseManager.reconcile_legacy_dataframe`, explicitly supplying both
  `source_timezone` and `imported_timezone`. This currently has no GUI workflow.
  A successful reconciliation retains the original naive source as an accepted
  alias, so both old and UTC exports can be retried.
- Reimporting an unchanged original trade/interest CSV does not require calling
  that helper manually: the importer can attach source evidence when broker ID,
  exact timestamp and all immutable values match the existing record. It uses
  the ordinary import timestamp/rate-date interpretation, without trying other
  timezones. The result is a duplicate, not a transaction rewrite. Different
  timestamps, financial values or unreproducible rates remain errors/conflicts.
- Legacy dividends without source identities, including those without broker
  IDs, can also be proven during original-CSV reimport: exactly one untracked
  record must match the ordinary import timestamp, ISIN, shares, price/currency,
  tax and financial totals. Only source metadata is attached. Multiple matching
  candidates or shifted times still require explicit reconciliation; nearby
  timestamps alone are never accepted.
- Reconciliation compares stored immutable values with the original import,
  requiring reproducible historical rates and unique candidates. Numeric proof
  allows only `rel_tol=1e-12`, `abs_tol=1e-8`; mismatches are conflicts.
  Local IDs, timestamps, financial values, remaining quantities, and pairings
  are not rewritten. Ambiguous/nonexistent DST times require an explicit offset.
- An anonymous singleton repeated across files is treated as a duplicate.
  Truly indistinguishable separate events without IDs cannot be proven apart.
  Broker ID stability across exports is not assumed to be verified by availability.
- Opening an old database automatically creates a sibling
  `<filename>.pre-v2-<random>.bak` before the transactional schema upgrade.
  Keep and protect that backup; older application versions cannot open schema 2.

### Automatic time-only normalization

- Both manual and API CSV imports can normalize a uniquely proven naive/UTC
  difference in an already recorded source. Canonical fields other than time
  must be identical, broker IDs must not disagree, and the stored immutable
  snapshot must still match. No source evidence is fabricated for untracked rows.
- The naive wall-clock value must equal the incoming UTC wall-clock value, and
  the old stored timestamp must exactly reproduce the original system-local
  parser. Fold checks and round trips reject ambiguous/nonexistent DST times.
  A changed machine timezone that cannot reproduce that interpretation remains
  a conflict; no fixed offset or tolerance is guessed.
- Normalization changes the timestamp, current source, accepted original source
  alias, stored snapshot and any affected recorded `holding_period_days`.
  A day count is updated only if its old value matches the old timestamps;
  inconsistent counts that would need updating remain conflicts, and NULL counts
  stay NULL. This applies to locked pairs too, without unlocking them.
  CZK values, quantities, IDs, pairing links, methods, time-test flags, notes and
  locks remain unchanged. Changes to the local rate date, UTC tax year, pairing
  chronology or calendar time test are still conflicts.
- Before the first attempted correction in each CSV import, a sibling SQLite
  backup `<filename>.pre-time-normalization-<random>.bak` is created from the
  committed database. Backup failure stops import before mutation. The row's
  timestamp, identity and derived holding-day updates roll back together on any
  subsequent failure.
- `time_normalized` counts committed corrections as a subset of `duplicates`,
  not `added` or `errors`. `time_backup` provides the backup path when created.
  Manual/API summaries display both; cancellation and partial imports retain
  honest committed counts. Both original and UTC sources remain idempotent.
- This uses existing schema-2 fields, with no schema-version bump, conflict
  table, API change or write to the broker. Backups contain sensitive database
  data and require the same protection.