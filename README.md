# TradingTools

TradingTools is a Tkinter desktop application for analyzing trading data.

## Run from source

Requires Python 3.10 or newer with Tkinter available.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m tradingtools
```

The application copies its tracked default JSON configuration to
`%APPDATA%\TradingTools\config` on first run. User changes and logs are stored
under `%APPDATA%\TradingTools`; databases remain wherever the user creates or
opens them.

On normal exit (File > Exit or closing the window), the application saves the
absolute path of the connected database in `last_database_path` in
`%APPDATA%\TradingTools\config\config.json`. If no database is connected, the
value is an empty string. On startup, an existing saved database is connected
automatically, with the same filters and views as File > Connect Database.
Missing files are skipped without creating a new database. Existing user
configurations need no migration; the new setting is added on exit.

## Trading 212 integration (stages 1-3)

[Trading212API](src/tradingtools/trading212_api.py) currently provides account
identity verification, credential management, and export/download of a CSV
report for a supplied interval, annual archiving, and restart recovery.
The synchronization menu and automatic database import are not implemented yet.

The API integration requires Windows and the native Windows backend of
`keyring`. API Key and Secret are stored together in Windows Credential
Manager, separately for each account and demo/live environment, with
local-machine persistence. Credentials never belong in the repository,
configuration files, databases, or logs. Unavailable or non-native storage
causes an explicit error; there is no plaintext fallback.

`save_credentials` verifies the account before saving or replacing its key
pair. `load_credentials`, `verify_account`, and `delete_credentials` operate
on the connected account. Deleting local credentials does not revoke the
key at Trading 212 or delete the database. A database backup does not
include credentials; configure the connection again on another computer.

CSV report methods:

- `request_csv_report(time_from, time_to)` requires timezone-aware datetimes,
  includes all four history categories, and returns `reportId`.
- `list_csv_reports()` lists the account's requested reports.
- `wait_for_csv_report(report_id)` returns the finished report's signed URL.
  Treat this URL and report lists containing it as sensitive; do not log them.
- `download_csv_report(report_id, destination)` waits, downloads the original
  CSV bytes into a temporary file, validates them, and publishes a new `.csv`
  file. The parent directory must exist; existing files are never overwritten.

These methods support `cancel_event` (a `threading.Event`) and `wait_timeout`
(600 seconds by default, covering the entire individual operation). Waiting
respects endpoint limits and server rate-limit headers. Transient read failures
have bounded retries. Cancellation is checked between waits and transfer
chunks; an active socket operation remains bounded by its timeout.

After an uncertain POST outcome, the same instance looks for a new report
matching the exact interval and content rather than blindly repeating POST.
If the outcome cannot be confirmed, retrying the same request only rechecks
reports. Keep the returned report ID to resume waiting/downloading.
Standalone report methods keep this recovery state in memory. The annual
archive additionally persists it before dispatching POST, including the
pre-existing report IDs, and resumes a known report after a restart.

Downloads and their redirects require HTTPS destinations under
`trading212.com` or `amazonaws.com` and never receive API credentials.
The current download limit is 100 MiB. Failed or cancelled transfers do not
publish incomplete CSV files. Deleting a local download does not delete a
broker-generated report; cancelling a local wait does not cancel remote
report generation.

Annual archive methods:

- `sync_yearly_csv(archive_directory, first_year, refresh_years=())` exports
  missing years, the current year, and the preceding year within a seven-day
  overlap. Closed years are not otherwise exported again unless explicitly
  selected in `refresh_years`. A formerly partial year is finalized after rollover.
- `get_archived_csvs(archive_directory)` verifies the archive and returns the
  recommended CSV for each year without reading credentials or contacting the
  API. It can finish a validated local download whose metadata commit was
  interrupted. If a report still needs the API, it logs a warning and returns
  only already committed files.

Calendar years use **Europe/Prague**, independently of the computer's timezone.
API requests use UTC. For example, full 2024 runs from
`2023-12-31T23:00:00Z` through `2024-12-31T22:59:59.999999Z`.
The current year ends at the captured sync cutoff (`as_of`, an optional aware
datetime, defaults to now). A partial report is never certified as a full year.
These precise Prague boundaries have offline tests, not yet a live-API
boundary verification.

Choose a protected folder outside the public repository. Files are stored under
`Trading212\<environment>\<account>\<year>\Trading212_<year>_<UTC-time>_<reportId>.csv`.
`archive.json` in the account folder contains intervals, content selections,
completion status, report IDs, SHA-256, size, relative paths, and recommended
revisions; it never contains credentials or signed URLs. Filenames describe
immutable file versions; completion and the recommended version are in metadata.
Unchanged bytes reuse a file within the same year, while changed versions and
older files are preserved.

Downloads are flushed and validated before publication; metadata is replaced
atomically. Known partial files and interrupted publications are recovered
through the persisted journal. A Windows file lock prevents concurrent writers
and is released by the OS if the process terminates. Hash mismatches, unsafe paths,
wrong account/environment/timezone, untracked CSVs, and disk errors fail explicitly.
Restore both CSVs and `archive.json` when moving or recovering the archive.
Do not infer complete coverage from an orphan CSV alone.

Annual synchronization uses a separate `wait_timeout` budget per year (including
requesting, waiting and downloading), plus local archive validation; cancellation
and endpoint pacing remain active. Retrying finishes the saved interval first;
a newer cutoff may then request an additional report. There is no automatic
deletion of archive history. Annual CSVs do not back up manual trade pairings,
settings, or exchange rates; retain ordinary database backups too.

## CSV import results (stage 4)

`DatabaseManager.import_dataframe(df, cancel_event=None)` returns the existing
`records`, `columns`, `read`, and `added` fields plus:

- `processed`: rows actually attempted, not the number inserted.
- `status`: `complete`, `partial` (row errors or unsupported actions), or
  `cancelled`. Duplicates and intentionally skipped cash-flow actions do not
  make an otherwise complete import partial.
- `duplicates` and `failed`: category counts, separate from successful inserts.
- `errors`: every failed row's 1-based position in the DataFrame, action, and
  error message. Row 1 is the first data record, not the CSV header; this is
  independent of pandas index labels.
- `conflicts`: the subset of errors requiring source/identity reconciliation.
- `unknown_actions` and `skipped_actions`: action names and counts.

`import_dataframe_batches(df, batch_size=100, cancel_event=None)` yields
independent cumulative snapshots with `status="running"` between batches and
one final result. Batches limit execution between yields, not transaction size:
the existing per-row commits remain. Cancellation is checked before every row;
an active row or exchange-rate lookup finishes first. Previously committed
rows remain available, and the full CSV can be retried with existing deduplication.
Iterate on the thread owning the SQLite connection.

Manual CSV import displays a modal progress window with processed/total row
counts and a Cancel button. CSV reading and import run on a worker with its own
SQLite connection, leaving the UI responsive during exchange-rate lookups.
CSV loading initially uses an indeterminate indicator. Closing the progress
window requests cancellation; it waits for the active operation and preserves
already committed rows. Other application controls remain blocked until the
worker closes its connection. Cancellation during file reading or a rate lookup
takes effect after that operation returns.

Missing mandatory values, invalid/non-finite amounts, missing currencies for
nonzero amounts, and write/rate errors are reported instead of silently replaced
with defaults. Absent optional fees and withholding tax still mean zero.
Only the established unique identity conflicts are skipped as duplicates;
other SQLite constraints produce explicit errors. A failed SQL transaction
is rolled back before processing subsequent rows.

The existing manual CSV dialog now reports duplicates, failed rows, and
unsupported actions and warns on partial imports instead of showing Success.
Trade signs, currency conversions, action mappings, and the legacy timestamp
parser are preserved. Dividend identity and historical timestamp reconciliation
are described below. No automatic Trading 212 database import or new API menu
is connected yet.

## CSV identities and legacy databases (stage 5)

Opening a schema-1 database first saves a SQLite backup beside it as
`<filename>.pre-v2-<random>.bak`, then transactionally upgrades to schema 2.
Failure blocks migration; the backup is retained if SQL migration fails.
Existing local IDs, timestamps, monetary values and pairings are preserved.
Older application versions cannot open schema 2; retain the backup for rollback.
Backups contain the same sensitive data as the database and need equal protection.
Custom dividend triggers require manual migration instead of being discarded.

Imports retain normalized source fields, broker IDs when available, and a
snapshot of stored values. Distinct identified dividends may share a timestamp
and ISIN. Repeated unchanged rows are duplicates; changed same-ID content, local
edits, and ambiguous identity matches are conflicts, never silent overwrites.
ID availability alone does not establish stability across broker exports.

Previously imported records without source evidence require their original CSV
before accepting overlapping new exports. The headless method
`reconcile_legacy_dataframe(df, source_timezone="UTC", imported_timezone="Europe/Prague")`
links proven identities without changing transactions. These example zones must
be confirmed for the actual source and historical import; neither is guessed.
It returns `linked`, `conflicts` and `status` (`complete` or `partial`).
Both the original naive CSV and the equivalent UTC CSV then remain recognizable.
Reconciliation is not yet exposed in the GUI.

Proof requires a unique historical record and reproducible original conversion
rates; numeric comparison uses `rel_tol=1e-12`, `abs_tol=1e-8`. DST-ambiguous or
nonexistent naive times are rejected. No blanket timezone correction is applied.
Without broker IDs, indistinguishable events cannot always be resolved: repeated
identical rows in one CSV (including a mix with and without IDs) are conflicts;
a singleton repeated in separate files is treated as a duplicate. See
[CSV import notes](docs/CSV_IMPORT_NOTES.md) for source matching details.

## Standalone fees

Schema **2** also includes `fees`; this extends the same backed-up **1 -> 2**
migration, not a separate schema version. Migration creates an empty fee table:
previously ignored fees must be supplied by importing their CSV again.

Only `ADR Fee` is currently mapped to this table. It stores the timestamp, type
(`FeeType.ADR`), optional instrument, signed original amount/currency, and signed
CZK equivalent. `Total` and `Currency (Total)` are mandatory; `Total (Account CCY)`
is not assumed to be CZK or used as a fallback. The selected daily/annual
conversion mode applies. Negative charges and positive amounts retain their signs.
Shares, price and broker ID are optional; available share/price detail is retained
in the source identity.

The `fee` category is included in import read/added/duplicate/failed counts and
the existing import-result message. CSV identity checks also apply to fees,
including optional-ID adoption, content/local-edit conflicts, anonymous ambiguity,
and explicit naive/UTC reconciliation. Fee/security/source writes are atomic.
The reconciliation helper only links existing records: for previously ignored
fees it reports that normal CSV import is required, rather than fabricating history.

These are standalone records only. Trade fees are not copied into this table.
`Dividend adjustment` remains unsupported. Fees are **not included in financial
or tax summaries**, and there is no new fee view or menu.

## Run tests

```powershell
python -m unittest discover -s tests -v
```

## Build a single Windows executable

```powershell
python -m pip install -e ".[build]"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

The executable is written to `dist\TradingTools.exe`. The default JSON files
are bundled into the executable and copied to the user's AppData directory on
first launch.
