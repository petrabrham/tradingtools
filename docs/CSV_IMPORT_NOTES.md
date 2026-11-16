# CSV Import Compatibility Notes

## GUI synchronization and current-run conflicts

- **File > Read transactions from Trading212...** uses verified annual archives
  and the same importer as manual CSV import. **Options > Trading212 connection...**
  manages the account binding, first year, archive folder and native Windows
  credentials. The connection is verified and explicitly confirmed before saving.
- Schema remains **2**. Existing `settings` stores only non-secret connection
  details and compact versioned import status/counts per year and CSV hash.
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
- A legacy `Time` without an offset is **not** silently interpreted as UTC for
  identity matching. Its existing import timestamp behavior is preserved.
  Nearby old dividends are an ambiguity guard, never a reason to shift/match time.
- Before accepting overlapping UTC exports, use the original CSV with
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