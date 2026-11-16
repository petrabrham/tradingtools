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

## Trading 212 integration (stage 1)

[Trading212API](src/tradingtools/trading212_api.py) currently provides account
identity verification and credential management only. CSV export, archiving,
and the synchronization menu are not implemented yet.

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
