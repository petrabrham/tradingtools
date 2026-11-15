import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tradingtools.config.config_loader import ConfigLoader
from tradingtools.config.country_resolver import CountryResolver
from tradingtools.config.tax_rates_loader import TaxRatesLoader
from tradingtools.paths import DEFAULT_CONFIG_FILES, get_config_dir, get_log_dir


class TestApplicationPaths(unittest.TestCase):
    def test_config_defaults_are_copied_once_to_appdata(self):
        with tempfile.TemporaryDirectory() as appdata:
            with patch.dict(os.environ, {"APPDATA": appdata}):
                config_dir = get_config_dir()

                self.assertEqual(
                    config_dir, Path(appdata) / "TradingTools" / "config"
                )
                self.assertEqual(
                    {path.name for path in config_dir.glob("*.json")},
                    set(DEFAULT_CONFIG_FILES),
                )
                for path in config_dir.glob("*.json"):
                    with path.open(encoding="utf-8") as file:
                        json.load(file)

                config_file = config_dir / "config.json"
                config_file.write_text('{"user": true}', encoding="utf-8")
                get_config_dir()
                self.assertEqual(
                    config_file.read_text(encoding="utf-8"), '{"user": true}'
                )

    def test_log_directory_is_created_under_appdata(self):
        with tempfile.TemporaryDirectory() as appdata:
            with patch.dict(os.environ, {"APPDATA": appdata}):
                log_dir = get_log_dir()
                self.assertEqual(
                    log_dir, Path(appdata) / "TradingTools" / "logs"
                )
                self.assertTrue(log_dir.is_dir())

    def test_default_loaders_read_from_user_config(self):
        with tempfile.TemporaryDirectory() as appdata:
            with patch.dict(os.environ, {"APPDATA": appdata}):
                with (
                    patch.object(ConfigLoader, "_instance", None),
                    patch.object(ConfigLoader, "_config", None),
                ):
                    self.assertEqual(
                        ConfigLoader().get_default_pairing_method(), "FIFO"
                    )

                self.assertAlmostEqual(TaxRatesLoader().get_rate("US"), 0.15)
                self.assertEqual(
                    CountryResolver().get_country("US05606L1008"),
                    ("CN", "override"),
                )

    def test_session_path_is_absolute_and_preserves_user_changes(self):
        with tempfile.TemporaryDirectory() as appdata:
            with (
                patch.dict(os.environ, {"APPDATA": appdata}),
                patch.object(ConfigLoader, "_instance", None),
                patch.object(ConfigLoader, "_config", None),
            ):
                config_path = get_config_dir() / "config.json"
                config_path.write_text('{"custom": 1}', encoding="utf-8")
                loader = ConfigLoader()
                self.assertEqual(loader.get_last_database_path(), "")
                config_path.write_text('{"custom": 2}', encoding="utf-8")

                loader.save_last_database_path("example.db")
                saved = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertEqual(saved["custom"], 2)
                self.assertEqual(
                    saved["last_database_path"], str(Path("example.db").resolve())
                )
                loader.reload()
                self.assertEqual(
                    loader.get_last_database_path(), saved["last_database_path"]
                )

                loader.save_last_database_path(None)
                saved = json.loads(config_path.read_text(encoding="utf-8"))
                self.assertEqual(saved, {"custom": 2, "last_database_path": ""})

    def test_session_write_failure_preserves_config_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as appdata:
            with (
                patch.dict(os.environ, {"APPDATA": appdata}),
                patch.object(ConfigLoader, "_instance", None),
                patch.object(ConfigLoader, "_config", None),
            ):
                loader = ConfigLoader()
                config_path = get_config_dir() / "config.json"
                original = config_path.read_bytes()
                with patch(
                    "tradingtools.config.config_loader.os.replace",
                    side_effect=PermissionError("Config is read-only"),
                ):
                    with self.assertRaises(PermissionError):
                        loader.save_last_database_path("example.db")
                self.assertEqual(config_path.read_bytes(), original)
                self.assertEqual(list(config_path.parent.glob("config-*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
