"""Isolated Windows packaging checks, invoked only with --smoke-test."""

import json
import logging
import os
import socket
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _run_checks() -> dict[str, object]:
    from keyring.backends.Windows import WinVaultKeyring
    from win32ctypes.pywin32 import win32cred

    from tradingtools.app import TradingToolsApp
    from tradingtools.paths import DEFAULT_CONFIG_FILES, get_config_dir
    from tradingtools.trading212_api import Trading212API
    from tradingtools.trading212_sync import Trading212Connection, save_connection

    _check(sys.platform == "win32", "The packaging smoke test requires Windows")
    _check(ZoneInfo("Europe/Prague").key == "Europe/Prague", "Prague timezone is unavailable")
    for filename in DEFAULT_CONFIG_FILES:
        json.loads((get_config_dir() / filename).read_text(encoding="utf-8"))

    api = Trading212API("demo", account_id=123)
    backend = api._credential_backend()
    _check(type(backend) is WinVaultKeyring, "Native Windows credential backend is unavailable")
    storage: dict[tuple[str, str], str] = {}

    def write(credential, flags):
        storage[(credential["TargetName"], credential["UserName"])] = credential["CredentialBlob"]

    # Only the storage boundary and account response are replaced; never access the real vault.
    with (
        patch.object(api, "verify_credentials", return_value=123),
        patch.object(win32cred, "CredWrite", side_effect=write),
        patch.object(backend, "get_password", side_effect=lambda service, user: storage.get((service, user))),
        patch.object(backend, "delete_password", side_effect=lambda service, user: storage.pop((service, user))),
    ):
        api.save_credentials("synthetic-key", "synthetic-secret")
        _check(api.load_credentials() == ("synthetic-key", "synthetic-secret"), "Credential roundtrip failed")
        api.delete_credentials()
        _check(not storage, "Credential deletion failed")

    app = TradingToolsApp()
    try:
        app.root.withdraw()
        app.db.create_database(str(Path(os.environ["APPDATA"]) / "synthetic.db"))
        save_connection(app.db, Trading212Connection("demo", 123, 2024))
        app.update_title()
        _check(
            app.root.title() == "Trading Tools - synthetic.db - Trading212 account 123 (Demo)",
            "The database/account title was not updated",
        )
        app.root.update()
        _check(app.db.get_db_version() == 2, "Unexpected database schema")
    finally:
        app.db.close()
        app.root.destroy()
    return {
        "status": "passed",
        "frozen": bool(getattr(sys, "frozen", False)),
        "gui": "passed",
        "defaults": "passed",
        "timezone": "Europe/Prague",
        "credential_backend": f"{type(backend).__module__}.{type(backend).__name__}",
        "credential_storage": "in-memory adapter; no real vault access",
    }


def run_smoke_test(report_path: Path) -> None:
    """Run offline with temporary AppData and report failures through JSON and exit status."""
    if not report_path.is_absolute() or not report_path.parent.is_dir():
        raise ValueError("The smoke-test report requires an absolute path in an existing directory")
    try:
        with (
            tempfile.TemporaryDirectory(prefix="tradingtools-smoke-") as directory,
            patch.dict(os.environ, {"APPDATA": directory}),
            patch.object(socket.socket, "connect", side_effect=RuntimeError("Network disabled in smoke test")),
            patch.object(socket.socket, "connect_ex", side_effect=RuntimeError("Network disabled in smoke test")),
        ):
            try:
                result = _run_checks()
            finally:
                logging.shutdown()
    except Exception as error:
        report_path.write_text(json.dumps({
            "status": "failed", "error": str(error), "error_type": type(error).__name__,
        }), encoding="utf-8")
        raise SystemExit(1) from error
    report_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
