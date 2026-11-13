from pathlib import Path


spec_location = Path(SPECPATH).resolve()
spec_dir = spec_location if spec_location.is_dir() else spec_location.parent
project_root = spec_dir.parent
entry_point = project_root / "src" / "tradingtools" / "__main__.py"
defaults_dir = project_root / "src" / "tradingtools" / "resources" / "defaults"
default_names = (
    "config.json",
    "country_overrides.json",
    "withholding_tax_rates.json",
)

datas = []
for default_name in default_names:
    default_path = defaults_dir / default_name
    if not default_path.is_file():
        raise FileNotFoundError(f"Default configuration file not found: {default_path}")
    datas.append((str(default_path), "tradingtools/resources/defaults"))

a = Analysis(
    [str(entry_point)],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="TradingTools",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
