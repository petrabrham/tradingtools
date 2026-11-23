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

## Trading 212 integration

[Trading212API](src/tradingtools/trading212_api.py) provides account
identity verification, credential management, and export/download of a CSV
report for a supplied interval, annual archiving, and restart recovery.
The GUI connects annual archives to the existing CSV importer. Synchronization
is started manually; it never runs automatically at startup.

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

### Using the GUI

1. Create or connect a database, choosing its normal daily/annual exchange-rate
   mode. For annual rates, import the required years before synchronization.
2. Select **Options > Trading212 connection...** (also offered on the first sync).
   Choose demo/live, the first year of account history, a protected archive folder,
   and enter the masked Key and Secret. Save verifies the account before storing
   the connection and credentials. If the database already contains transactions
   without an account binding, confirm that they belong to the displayed account.
   Declining leaves the binding and credentials unsaved. Empty databases need
   no additional account confirmation.
   The archive folder is prefilled from this computer's `config.json`. When an
   account is already bound, the dialog also displays a short SHA-256 fingerprint
   of the locally saved API key. The key and secret stay masked/blank; blank
   fields reuse that identified local key pair. If it was revoked at Trading 212,
   enter the replacement pair. The fingerprint identifies the local key only;
   successful account verification confirms whether Trading 212 still accepts it.
   The entered pair is verified once before storing. A temporary account-endpoint
   HTTP 429 is retried briefly according to `Retry-After`; invalid credentials
   and other errors are not retried.
3. Select **File > Read transactions from Trading212...** to start normal
   synchronization directly. Connection setup appears automatically for a
   database without a saved connection or when this computer has no archive
   folder configured.
   To recheck older years, use **File > Refresh older Trading212 years...**
   and click the desired years in the selection list; no comma-separated input
   is needed. Selected years are exported and rechecked even when unchanged.
4. Read the per-year result: archive coverage (full year/year to date) is separate
   from import status. Counts distinguish read/added transactions, duplicates,
   unsupported actions, intentional skips, errors and conflicts.

One database is bound to one account and environment; changing either is refused.
The window title shows the open database name and, when bound, its saved
Trading212 account ID and Live/Demo environment without an API request.
Portable account metadata (environment, account ID, first year and timezone) and
compact per-year/hash import statuses use the existing `settings` table, with
**no schema change (still version 2)**. Key replacement
must verify the bound account. Leave both credential fields blank to reuse the
saved pair. Removing local credentials keeps the DB, archive and binding.
Manual CSV import never asks for account metadata or confirmation, and does not
create or change the binding. Unbound CSV-only databases may remain unbound.
For API imports, an account mismatch stops synchronization before archive import.

The shared archive root is stored **only on this computer** in
`%APPDATA%\TradingTools\config\config.json`, under `trading212_archive_directory`.
Accounts and demo/live environments have separate subfolders beneath that root.
Moving a database does not move or select its archive: if the new computer has
no configured root, choose one in connection settings before synchronizing.
Legacy database bindings containing an archive path remain readable, but that
path is ignored, never used to initialize local configuration. Saving the
connection or starting synchronization after successful account verification
rewrites the binding without the path (metadata format 2, not DB schema 3).
Selecting a different root does not move existing archive files automatically.

Workers own their API and SQLite connections. The progress window shows phases,
rate-limit waits and processed rows. Closing it cancels locally but leaves the
application open. Closing the main application requests cancellation and exits
only after worker cleanup and normal session saving. An active CSV read, rate
lookup or socket operation must finish first. Competing imports and database
changes are blocked until cleanup.

Verified unfinished archived imports are retried before requesting more reports.
An identical successfully imported revision is skipped; partial/cancelled/failed
imports are retried safely through existing deduplication. Already committed rows
and verified archives survive cancellation or failure. Recoverable row conflicts
allow later years to continue with an overall partial result. Fatal account,
archive, database or status-persistence failures stop the run visibly.
Missing annual rates are errors, never guessed values: import the rates and retry.

**File > View last import conflicts...** opens read-only comparisons for the
current run, also available after manual CSV import. It separates raw CSV/source
values, stored fields, expected values when known, and recorded original snapshots;
missing conversions/timezone interpretations remain unavailable. Ambiguous
candidates are shown without choosing a match. There are no correction/accept/
ignore actions. Details live **only in memory**, disappear on the next import,
database switch/release or exit, and are not saved to a conflict table or settings.
Reimport the CSV to reconstruct them after restart. Proven time-only legacy
differences can be normalized during import as described below; the viewer itself
does not shift timestamps. Other timezone reconciliation uses the non-GUI helper.

### API surface and archive behavior

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

Both annual methods accept an optional `on_report` callback with a verified
`ArchivedCSV` descriptor. New reports are notified only after durable publication;
callback/import failures do not repeat export POSTs. The optional `on_progress`
constructor callback receives safe phase/year/wait metadata, never raw CSVs,
credentials or signed URLs. `verify_credentials` checks an entered pair without
overwriting saved credentials.

Calendar years use **Europe/Prague**, independently of the computer's timezone.
API requests use UTC. For example, full 2024 runs from
`2023-12-31T23:00:00Z` through `2024-12-31T22:59:59.999999Z`.
The current year ends at the captured sync cutoff (`as_of`, an optional aware
datetime, defaults to now). A partial report is never certified as a full year.
These precise Prague boundaries have offline tests, not yet a live-API
boundary verification.

Trading 212's report metadata may truncate timestamp fractions to milliseconds
(for example, `.999999Z` becomes `.999Z`). Matching recognizes that reported
precision only: another millisecond, a different interval/content or a conflicting
higher-precision timestamp is still rejected. Original request/archive boundaries
and exact CSV timestamp validation are unchanged. Recovery still requires exactly
one new matching report ID and never blindly repeats an uncertain POST.

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

### Recovering a database from the archive

A database backup is the preferred recovery method: CSVs do not contain manual
pairings, locks, notes, application settings, account bindings or exchange-rate
tables. Keep separate backups of the database and the complete archive.

To rebuild transactions without contacting Trading212:

1. Restore the complete account archive, including `archive.json` and all CSV
   revisions. Do not select every CSV revision for import.
2. Obtain the verified recommended CSVs in chronological order using the local
   API below (the account ID and environment must match the archive):

   ```python
   from tradingtools.trading212_api import Trading212API

   archive = Trading212API("demo", account_id=12345678)  # replace with your account
   paths = archive.get_archived_csvs(r"D:\TradingArchives")
   for path in paths:
       print(path)
   ```

   This checks identity, intervals and file hashes without credentials or network
   requests. An invalid archive is an error; incomplete coverage is not repaired
   by guessing which file to use.
3. Create a new database with the original daily/annual exchange-rate mode.
   For annual mode, import the same rate tables for every required year and
   currency before importing transactions. Daily mode normally obtains CNB rates
   online; a fully offline daily reconstruction needs those same rates available
   to the rate provider. Broker CSV conversion rates are not a substitute.
4. Use **File > Import CSV** on each listed file, oldest year first. Check each
   result for missing rates, unsupported actions and errors. Importing the same
   recommended files again does not insert duplicates.

With the same rates, supported transaction counts and stored CZK amounts can be
reconstructed. Manual pairings/locks and settings must be restored separately
or recreated; recalculated pairings are not guaranteed to match earlier manual
choices. Standalone ADR fees are restored but still excluded from tax/financial
summaries. `Dividend adjustment` remains unsupported and causes a partial result.
Manual recovery does not assign account metadata or require API credentials.
On another computer, select the local archive root and configure credentials
separately before the next API synchronization.

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
before accepting overlapping new exports. Reimporting an unchanged original
trade/interest CSV now automatically verifies the existing broker ID, exact
stored timestamp, and all immutable imported values (including conversions and
trade fees). A proven match adds only its source identity and counts as a
duplicate; local transaction values, remaining quantities, and pairings stay
unchanged. For legacy dividends (including those without broker IDs), the
importer similarly requires exactly one untracked record with the same timestamp,
ISIN and all immutable financial values. It attaches only source evidence and
counts a duplicate. A timestamp/financial mismatch or multiple possible matches
remains an explicit conflict unless the narrow time-only proof below succeeds.

When an incoming UTC source differs from a recorded naive source **only in time
interpretation**, import can automatically correct the actual stored timestamp.
It requires one uniquely identified transaction, otherwise identical canonical
source fields, an unchanged stored snapshot, and exact reproduction of the old
local-time parser (including DST checks). No fixed one/two-hour tolerance is used.
The correction must preserve the rate calendar date, UTC tax year, and existing
pairing chronology and time-test qualification. Consistent recorded holding-day
counts are recomputed from the corrected timestamps, including for locked pairs;
unset counts remain unset. An inconsistent count is a conflict if it would need
updating. All financial values, remaining quantities, IDs, pairing links,
quantities, methods, time-test flags, notes and locks stay unchanged.

Before the first such correction in each CSV import, a SQLite backup is saved
beside the database as `<filename>.pre-time-normalization-<random>.bak`; failure
stops import before correction. Timestamp, source alias, refreshed snapshot
and derived holding-day updates commit atomically per row. Both old and UTC
exports remain safe to reimport.
Manual/API summaries show the normalization count (a subset of duplicates) and
backup path. Protect these backups like the database. Ambiguous cases, changed
values, missing source evidence and unsafe date/pairing changes remain conflicts.

For timezone reconciliation, the headless method
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

Discovery is offline and uses synthetic data and credential adapters. The
optional network demonstration is excluded; run it explicitly with
`python tests\manual_annual_rates.py` only when CNB network access is intended.

## Build a single Windows executable

```powershell
python -m pip install -e ".[build]"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

The executable is written to `dist\TradingTools.exe`. The default JSON files
are bundled into the executable and copied to the user's AppData directory on
first launch.

To build and test the actual executable:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1 -SmokeTest
```

The smoke test checks GUI startup, bundled defaults, database/account title,
Prague timezone data, native Windows keyring backend selection and credential
roundtrip through an in-memory storage adapter. It uses temporary AppData,
blocks network connections and never reads/writes the real credential vault.
Failure is reported with a nonzero exit code and JSON diagnostics. This is not
a live API check or a real Windows Credential Manager persistence test.
For diagnostics on an existing build, run
`TradingTools.exe --smoke-test C:\Temp\TradingTools-smoke.json`
with an absolute report path in an existing directory.
