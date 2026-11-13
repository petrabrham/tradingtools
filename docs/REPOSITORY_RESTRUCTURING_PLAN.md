# Plan reorganizace repozitáře TradingTools

## Cíl

Oddělit Python zdrojový kód, JSON konfiguraci, dokumentaci, testy a výstupy sestavení. Připravit aplikaci tak, aby šla spustit jako Python modul i distribuovat jako Windows `.exe`, aniž by potřebovala složku `data/`.

Tento dokument zachycuje cílovou strukturu a rozhodnutí o umístění runtime souborů.

## Navrhovaná struktura

```text
tradingtools/
├── pyproject.toml
├── README.md
├── .gitignore
├── docs/
├── packaging/
│   └── TradingTools.spec           # konfigurace PyInstalleru
├── scripts/
│   └── build_windows.ps1           # opakovatelný build pro Windows
├── src/
│   └── tradingtools/
│       ├── __init__.py
│       ├── __main__.py             # umožní `python -m tradingtools`
│       ├── app.py
│       ├── config/                 # Python logika pro konfiguraci a kurzy
│       ├── resources/
│       │   └── defaults/           # verzované výchozí JSON soubory
│       ├── db/
│       ├── dialogs/
│       ├── ui/
│       └── views/
├── tests/
├── build/                          # generované PyInstallerem, necommitovat
└── dist/                           # distribuční výstup, necommitovat
```

`data/` nebude součástí distribučního balíčku. Případná testovací data mohou zůstat lokálně nebo se později přidají jako anonymizované fixtures do `tests/`.

## Umístění konfigurace a uživatelských souborů

- Výchozí JSON soubory budou uloženy v `src/tradingtools/resources/defaults/` a sledovány v Gitu. To je zdrojová kopie, kterou vývojář mění a kontroluje.
- Při prvním spuštění aplikace vytvoří `%APPDATA%\TradingTools\config` a zkopíruje do něj chybějící výchozí soubory.
- Aplikace bude běžně číst i zapisovat konfiguraci v `%APPDATA%\TradingTools\config`, ne v repozitáři ani vedle `.exe`. Python spuštění i `.exe` tak budou používat stejné zapisovatelné umístění.
- PyInstaller přibalí výchozí JSON soubory do `.exe`; uživatel nebude muset mít vedle `.exe` konfigurační soubory. Při spuštění se potřebné soubory z přibalených výchozích hodnot zkopírují do AppData.
- Logy se budou ukládat do `%APPDATA%\TradingTools\logs`; aplikace adresáře vytvoří, pokud ještě neexistují.
- Databáze zůstane samostatným souborem, který uživatel vytváří nebo vybírá v aplikaci. Nebude zabudována do `.exe`.

### Aktualizace výchozí konfigurace

Při prvním spuštění se soubor zkopíruje jen tehdy, pokud v AppData ještě neexistuje. Aktualizace aplikace proto nesmí bez rozmyslu přepsat uživatelské úpravy. Pokud se výchozí konfigurace změní, změna se zavede cílenou migrací nebo sloučením, které zachová uživatelská data. Zvláštní pozornost vyžaduje `country_overrides.json`, který aplikace upravuje.

## Navržené fáze

1. **Připravit balicí základ** — přidat `pyproject.toml`, stanovit runtime závislosti a oddělit případné vývojové/Jupyter závislosti.
2. **Přesunout aplikační kód** — převést `app.py`, `db/`, `dialogs/`, `ui/`, `views/` a Python moduly z `config/` pod `src/tradingtools/`.
3. **Upravit importy a spouštění** — přejít na importy `tradingtools.*`, přidat `__main__.py` a ověřit spuštění přes `python -m tradingtools`.
4. **Sjednotit cesty k souborům** — implementovat rozlišení běhu ze zdrojů a z `.exe`; načítat JSON ze stanoveného umístění a ukládat logy do `%APPDATA%\TradingTools\logs`.
5. **Připravit sestavení Windows** — přidat PyInstaller spec a build skript; přibalit výchozí JSON soubory do `.exe` a při prvním spuštění je připravit v AppData.
6. **Ověřit chování** — spustit existující testy, ověřit importy a spuštění z čistého umístění bez `data/`, vytvoření konfigurace v AppData, zachování existující uživatelské konfigurace při dalším spuštění, zápis logů a uživatelských přepsání.

## Rozsah mimo plán

- Změny funkčnosti výpočtů, databázového schématu nebo grafického rozhraní.
- Distribuce uživatelských databází, CSV, logů nebo obsahu současné složky `data/`.
- Vytvoření instalátoru; první distribuční varianta bude samostatné `.exe`, které si při prvním spuštění připraví konfigurační soubory v AppData.

## Stav realizace

Struktura `src/tradingtools/`, AppData konfigurace a logování i PyInstaller one-file sestavení jsou realizovány. Ověření: všech 101 unit testů prošlo a vznikl `dist/TradingTools.exe`.
