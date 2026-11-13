import os
import shutil
from pathlib import Path


DEFAULT_CONFIG_FILES = (
    "config.json",
    "country_overrides.json",
    "withholding_tax_rates.json",
)


def get_app_data_dir() -> Path:
    """Return the per-user TradingTools data directory."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        base_dir = Path(appdata)
    elif os.name == "nt":
        raise RuntimeError("The APPDATA environment variable is not set.")
    else:
        base_dir = Path(
            os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
        )

    return base_dir / "TradingTools"


def get_config_dir() -> Path:
    """Create the user config directory and seed missing files from package defaults."""
    config_dir = get_app_data_dir() / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    defaults_dir = Path(__file__).resolve().parent / "resources" / "defaults"

    for filename in DEFAULT_CONFIG_FILES:
        default_path = defaults_dir / filename
        if not default_path.is_file():
            raise FileNotFoundError(
                f"Default configuration file not found: {default_path}"
            )

        user_path = config_dir / filename
        if not user_path.exists():
            shutil.copyfile(default_path, user_path)

    return config_dir


def get_log_dir() -> Path:
    """Create and return the per-user log directory."""
    log_dir = get_app_data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir
