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