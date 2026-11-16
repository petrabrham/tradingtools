# CSV Import Compatibility Notes

## Broker export 2026

- Import supports both time column variants:
  - `Time`
  - `Time (UTC)`
- The `Total (Account CCY)` column is currently ignored on import.
  - In current samples, it appears with `ADR Fee` entries.
  - This is intentional for now and does not block import.

## Ignored transaction actions

The importer already ignores selected actions and does not store them in the database.

Current "insignificant" actions:
- `Deposit`
- `Currency conversion`
- `Card debit`
- `Withdrawal`
- `Result adjustment`

Any other unsupported action is treated as unknown, logged, and skipped.

Example actions seen in 2026 export that are currently skipped as unknown:
- `ADR Fee`
- `Dividend adjustment`

## Notes

- This behavior is currently expected and intentional.
- If needed later, `ADR Fee` can be mapped to a dedicated stored type or a fee table.

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