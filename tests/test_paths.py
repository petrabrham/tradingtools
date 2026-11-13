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


if __name__ == "__main__":
    unittest.main()
