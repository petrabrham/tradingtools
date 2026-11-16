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

## Trading 212 integration (stages 1-2)

[Trading212API](src/tradingtools/trading212_api.py) currently provides account
identity verification, credential management, and export/download of a CSV
report for a supplied interval. Annual archiving, the synchronization menu,
and automatic database import are not implemented yet.

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
This recovery state is currently in memory; persistent restart recovery
belongs to the annual-archive stage.

Downloads and their redirects require HTTPS destinations under
`trading212.com` or `amazonaws.com` and never receive API credentials.
The current download limit is 100 MiB. Failed or cancelled transfers do not
publish incomplete CSV files. Deleting a local download does not delete a
broker-generated report; cancelling a local wait does not cancel remote
report generation.

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
