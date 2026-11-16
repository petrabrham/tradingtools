# Plán synchronizace Trading 212 přes export/import CSV

Datum: 2026-11-15  
Stav: etapová implementace; etapa 1 dokončena, etapa 2 čeká na potvrzení.

Tento plán nahrazuje [původní návrh přímého načítání JSON historií](TRADING212_API_IMPLEMENTATION_PLAN.md).

## 1. Cíl a zvolený přístup

Do menu `File` přidat `Read transactions from Trading212...`.
Aplikace požádá Trading 212 o CSV report, stáhne jej, bezpečně archivuje
a importuje pomocí současného CSV importu.

Uživatel nemusí ručně exportovat ani vybírat soubor. Současně získá
roční CSV přehledy pro případ obnovy transakčních dat do nové databáze.

- Spouštění je ruční; bez automatické synchronizace při startu.
- Vzdálený účet se používá výhradně pro čtení/export historie.
- Žádné obchodování ani změny portfolia.
- Ruční CSV import zůstává dostupný.
- Zachovat existující finanční výpočty, párování a režim směnných kurzů.
- První verze váže jednu databázi na jeden účet a prostředí Trading 212.
- Od první verze ukládat API Key a Secret do Windows Credential Manageru,
  nevyžadovat jejich opakované zadávání při každém spuštění.
- Veškerou logiku specifickou pro Trading 212 API soustředit do jedné
  třídy `Trading212API` v samostatném souboru
  `src/tradingtools/trading212_api.py`.

Read-only zde neznamená „jen HTTP GET“. Vytvoření reportu používá POST,
ale pouze vytváří export historie, nikoli objednávku.

## 2. Ověřený API postup

1. `GET /api/v0/equity/account/summary`: ověřit účet a jeho ID.
2. `POST /api/v0/equity/history/exports`: zadat časový rozsah a obsah reportu.
3. `GET /api/v0/equity/history/exports`: sledovat požadované `reportId`.
4. Při stavu `Finished` stáhnout CSV z `downloadLink`.

Požadavek na export obsahuje:

- `timeFrom`, `timeTo`;
- `dataIncluded.includeOrders`;
- `dataIncluded.includeDividends`;
- `dataIncluded.includeInterest`;
- `dataIncluded.includeTransactions`.

Pro roční archiv zapnout všechny čtyři přepínače. Archiv má zachovat
i události, které TradingTools nyní neumí analyticky zpracovat.
Ověřit, jaké konkrétní události broker do reportu skutečně zahrnuje.

Dokumentované limity:

- vytvoření reportu: 1 požadavek za 30 sekund;
- kontrola reportů: 1 požadavek za minutu;
- přehled účtu: 1 požadavek za 5 sekund.

Limity jsou na účet. Respektovat také rate-limit hlavičky. Při exportu
více roků jedním seznamem reportů kontrolovat všechny čekající `reportId`,
nikoli provádět samostatný polling pro každý rok.

Stavy `Queued`, `Processing`, `Running` znamenají čekání.
`Canceled`, `Failed` jsou neúspěšné terminální stavy.
Zavést konečný časový limit čekání a možnost zrušení.
Zrušení místního běhu nemusí zrušit report již generovaný brokerem.

## 3. Podmínky, které ověřit před implementací

- Je CSV z API kompatibilní s ručním exportem: hlavičky, kódování,
  oddělovač, ID, časová zóna, měny, dividendová daň a poplatky?
- Obsahuje `includeInterest` oba typy úroků, včetně lending interest?
- Jak broker interpretuje hranice `timeFrom` a `timeTo`:
  včetně/výlučně, přesnost a časová zóna?
- Je povolen celý kalendářní rok v jednom reportu? Existuje limit rozsahu,
  velikosti nebo dostupnosti starší historie?
- Jaká konkrétní oprávnění klíče vyžaduje vytvoření a čtení reportů?
  Dokumentace exportů uvádí pouze obecné `Missing Permissions`.
- Jak dlouho platí odkaz ke stažení a lze po restartu dohledat report?

Neodvozovat skutečnou srážkovou daň z odhadované sazby ani nedoplňovat
chybějící údaje nulami. Pokud CSV není kompatibilní, nejprve přesně
vymezit nutné úpravy importeru; nespoléhat na předpokládanou shodu.

Pokud se celý rok nevejde do jednoho reportu, nejprve navrhnout a odsouhlasit
skládání dílčích exportů. Nevydávat dílčí soubor za úplný roční přehled.

## 4. Roční archiv

### Časové pokrytí

- Uzavřený rok: od 1. ledna do konce 31. prosince daného roku.
- Aktuální rok: od 1. ledna do okamžiku exportu; jasně označit jako průběžný.
- Po přechodu do nového roku znovu exportovat celý předchozí rok,
  i když už existuje průběžný soubor vytvořený 31. prosince.
- První rok archivu zvolí uživatel, typicky rok prvních transakcí na účtu.
  Datum nejnovější transakce v DB samo neurčuje začátek úplného archivu.

Konkrétní API timestampy hranic stanovit až po ověření časové sémantiky.
Pro archiv použít jedno explicitně zvolené roční časové členění,
sladěné s brokerovým exportem a evidencí aplikace; nespoléhat na aktuální
časovou zónu počítače. Otestovat přelom roku a přestupný rok.
Názvem roku neskrývat nesoulad mezi požadovaným a skutečným pokrytím.

### Umístění a soubory

Uživatel při prvním propojení vybere složku archivu. Neumisťovat ji
do instalace aplikace ani automaticky vedle spustitelného souboru.
Archiv nesmí záviset na existenci konkrétní databáze.

Navržené členění:

```text
<vybraná složka>\Trading212\<prostředí>\<účet>\
    archive.json
    2025\
        Trading212_2025_full_<čas-stažení>_<reportId>.csv
    2026\
        Trading212_2026_partial_<čas-stažení>_<reportId>.csv
```

Jména mají obsahovat bezpečné identifikátory a UTC čas bez dvojteček.
Žádná credentials v názvech ani metadatech. Archiv obsahuje citlivá
finanční data; doporučit uživateli chráněné úložiště a samostatnou zálohu.

- Uchovat originální CSV bytes bez přepočtů, filtrace a přepisování sloupců.
- `archive.json` uložit mimo DB: rok, účet/prostředí, reportId, požadovaný
  interval, volby obsahu, čas stažení, cesta, velikost a SHA-256 souboru.
- Rozlišit úplný uzavřený rok a průběžné pokrytí; uvést doporučenou
  aktuální verzi pro obnovu. „Úplný“ znamená celý požadovaný rok
  dostupný při exportu, nikoli záruku, že broker nikdy neprovede opravu.
- Pokud se obsah nového exportu nezměnil, nevytvářet další identickou kopii.
- Pokud se změnil, zachovat novou verzi i předchozí soubor. Uzavřený
  rok může broker dodatečně opravit; nepřepisovat archiv destruktivně.
- V první verzi nepřidávat automatické mazání starších verzí.

### Bezpečnost zápisu

Stahovat do konkrétního dočasného souboru ve stejné složce, ověřit dokončení,
obsah a CSV strukturu, spočítat hash a teprve poté soubor atomicky zveřejnit.
HTML chybová stránka není CSV. Prázdný rok je přípustný jen jako validní
report se správnými hlavičkami, ne jako prázdná HTTP odpověď.

Metadata aktualizovat atomicky až po zveřejnění CSV. Při pádu mezi zápisy
musí jít nezapsaný CSV soubor dohledat a znovu ověřit. Selhání archivu
je viditelná chyba; nehlásit úspěšnou synchronizaci bez uchovaného reportu.

CSV archivovat před DB importem. Pokud import selže například kvůli
chybějícím kurzům, CSV zůstane dostupné pro opakovaný lokální import.

## 5. Výběr roků při synchronizaci

Pro první verzi preferovat jednoduchost: pro dotčený rok exportovat
celý roční interval a importovat celý soubor s deduplikací.
Nevytvářet paralelně inkrementální soubory a další odlišný roční archiv.

První běh:

1. Ověřit účet, zvolit archiv a první rok.
2. Pro každý rok do aktuálního roku získat úplný/průběžný report.
3. Archivovat a importovat po jednotlivých rocích.
4. Existující archiv lze použít pro lokální obnovu bez nového API exportu.
   Kontrolovat účet, pokrytí, obsahové volby a hash.

Běžný běh:

1. Aktualizovat aktuální rok.
2. Doplnit chybějící roky a finalizovat předchozí rok po přelomu roku.
3. Zopakovat lokální import již stažených roků s nedokončeným importem.
4. Aktualizovat také starší rok zasahující do navrženého sedmidenního
   překryvu, zejména na začátku ledna.

Nejnovější data v DB a stav importu jednotlivých kategorií jsou orientační
pomůcka. Jeden globální `MAX(timestamp)` nesmí způsobit vynechání úroků
nebo dividend ani chybějícího ročního archivu.

Starší dokončené roky při každém běhu znovu nestahovat. Nabídnout explicitní
obnovení exportu vybraných roků pro dodatečné opravy. Sedmidenní překryv
nezaručuje zachycení libovolně starých změn.

## 6. Import a deduplikace

Použít [DatabaseManager.import_dataframe](../src/tradingtools/db/dbmanager.py)
po načtení archivovaného CSV přes pandas. Zachovat finanční převody a
[existující pravidla CSV importu](CSV_IMPORT_NOTES.md).

Před automatizací cíleně upravit:

- Výsledky importu: skutečné počty vložených, duplicitních, vynechaných,
  neznámých a chybných záznamů; nespoléhat jen na `lastrowid`.
- Předání výsledku dividendového zápisu až k počítadlu importeru.
- Explicitní chyby jednotlivých řádků v konečném výsledku, nejen v logu.
- Opakování po částečném importu nesmí násobit data.
- Ověření ID mezi ručním a API CSV. Při shodě formátu není potřeba
  zavádět mapování jednotlivých JSON `fill.id`.
- Dividendy nyní mají `UNIQUE(timestamp, isin_id)`. Ověřit, zda export
  může obsahovat dvě legitimní výplaty se stejným klíčem a zda má stabilní
  ID. Pokud ano, cíleně doplnit dividendovou identitu a migraci, včetně
  kompatibility se starými záznamy bez ID.
- Stejné ID s rozdílným obsahem hlásit jako konflikt, ne jako obyčejnou
  duplicitu. Již spárované obchody automaticky nepřepisovat.
- Ošetřit přechod ze starého `Time` bez offsetu na `Time (UTC)`.
  Současný parser starou hodnotu interpretuje v místní časové zóně;
  při stejném brokerově čase proto nemusí vzniknout stejný DB timestamp.
  U dividend bez uloženého brokerova ID hrozí duplicity při novém importu.
  Před normalizací starých záznamů ověřit jejich původ a časovou sémantiku;
  neposouvat plošně všechny časy v existující DB.

Žádná plošná přestavba repositories ani nový obecný broker framework.
Migraci schématu zavést jen pro ověřenou potřebu identity/stavu importu;
zachovat existující záznamy, jejich místní ID a párování.

V DB uložit ne-tajnou vazbu na účet/prostředí a stav lokálního importu
verze reportu. Evidence archivu zůstává mimo DB, aby přežila její ztrátu.
Označení „staženo“ a „úspěšně importováno“ musí být oddělená.

Záměrně ignorované události i nepodporované akce zůstanou v originálním
CSV. V UI uvést, že úspěšné stažení celého reportu neznamená podporu
všech jeho akcí v analytických pohledech.

## 7. Obnova databáze z archivu

1. Vytvořit novou DB a vybrat stejný režim kurzů jako u původní DB.
2. U ročních GFŘ kurzů nejdříve importovat potřebné kurzové soubory;
   pro denní ČNB zajistit dostupnost potřebných kurzů.
3. Vybrat ověřenou nejnovější doporučenou verzi každého roku,
   ne všechny archivní revize současně.
4. Importovat od nejstaršího roku k nejnovějšímu pomocí běžného CSV
   importu; API klíč ani dostupnost Trading 212 nejsou nutné.
5. Zkontrolovat chyby, nepodporované akce a souhrny jednotlivých kategorií.

CSV obnoví jen brokerovy údaje, které importer podporuje. Neobnoví
uživatelsky vytvořená párování, nastavení, ruční opravy ani jiné lokální
údaje, které v exportu nejsou. Roční archiv proto není náhradou za
`Save Database Copy As...` a zálohu konfigurace/kurzů.

Pro první verzi stačí dokumentovaný postup se současným ručním importem.
Hromadný průvodce obnovou je případné pozdější rozšíření.

## 8. Credentials a read-only hranice

- Od první verze použít Windows Credential Manager (Správce pověření)
  aktuálního Windows uživatele, z Pythonu přes knihovnu `keyring`.
- Použít výhradně ověřený nativní Windows backend. Samotná dostupnost
  knihovny nestačí; nepřijmout plaintext backend ani jiné neověřené úložiště.
- Při prvním propojení uživatel zadá API Key a maskovaný Secret.
  Po ověření účtu uložit dvojici jako jeden credential záznam, aby při
  aktualizaci nemohla vzniknout kombinace starého klíče a nového Secretu.
- Záznam pojmenovat podle aplikace, prostředí a identity účtu.
  Konfigurace/DB obsahuje pouze ne-tajný odkaz na pověření.
  Při dalším spuštění jej aplikace načte ze systémového úložiště.
- Přihlašovací údaje nevkládat do repository, instalačního balíčku,
  souboru JSON, SQLite, CSV archivu ani logů. `.gitignore` není zabezpečení.
- Při chybě či nedostupnosti Credential Manageru zobrazit konkrétní
  chybu a zastavit API propojení/synchronizaci; žádný náhradní zápis do
  souboru ani tichý přechod na režim pouze v paměti.
  Ruční import místního CSV zůstává dostupný.
- Nabídnout změnu a odstranění uloženého pověření. Změnu ověřit proti
  vázanému účtu před nahrazením funkčního záznamu.
  Odstranění lokálního pověření nemaže DB ani archiv a nezneplatní klíč
  u Trading 212; vzdálené zneplatnění provádí uživatel u brokera.
- Pověření nejsou přenositelnou součástí zálohy DB. Na jiném počítači
  nebo pod jiným Windows uživatelem je nutné API propojení nastavit znovu.
- Úložiště chrání credentials na disku, ale není ochranou před malwarem
  běžícím pod stejným uživatelem. Používat samostatný klíč bez obchodních
  oprávnění a možnost jeho zneplatnění u brokera.
- Potřebná oprávnění ověřit pro exporty a přehled účtu; nežádat
  oprávnění pro zadávání, změny a rušení objednávek.
- Povolit pouze čtení přehledu účtu, seznamu exportů a jeden konkrétní
  POST pro vytvoření CSV reportu. Nepřidávat obchodní API metody.
- Používat HTTPS s ověřením TLS a konečnými timeouty.
- Download oddělit od autentizovaného API klienta. Na `downloadLink`
  ani na jeho přesměrování nepřidávat API Authorization.
- Ověřit bezpečný protokol a cíl stažení podle skutečného brokerova
  download workflow; nepřijímat libovolné lokální či nebezpečné URL.
- Nelogovat credentials, celé finanční payloady ani podepsané odkazy.

Archiv je lokální výstup pro uživatele. Žádné finanční údaje, klíče
ani archivní soubory neposílat jiným službám.

## 9. GUI a chyby

Nový příkaz zapojit přes [MenuManager](../src/tradingtools/ui/menu_manager.py)
a [TradingToolsApp](../src/tradingtools/app.py).

- Bez otevřené DB je příkaz zakázaný.
- První dialog: credentials, demo/live, archiv a první rok.
- Další spuštění používá uložené pověření bez opakovaného zadávání;
  přidat správu propojení pro změnu a odstranění pověření.
- Před prvním zápisem potvrdit vazbu účtu na DB; později ji vždy ověřit.
- Ukazovat fáze: požadavek reportu, čekání, stahování, archivace a import,
  včetně aktuálního roku a čekání na rate limit.
- Síť a souborové operace mimo GUI vlákno; komunikace přes frontu
  a `root.after()`. Tkinter volat jen z GUI vlákna.
- Existující SQLite spojení nepředávat do workeru. Import provádět
  přes vlastníka spojení po krátkých dávkách, aby zůstalo možné zrušení.
  Cíleně umožnit dávkování importeru bez změny jeho finanční logiky.
- Během běhu nepovolit další synchronizaci, CSV import ani výměnu DB.
- Po vložení dat obnovit seznam roků a pohledy.
- Při zrušení zachovat platná CSV a dokončené DB zápisy; dočasné
  soubory bezpečně uklidit. Import lze idempotentně zopakovat.

`401`/`403` mají konkrétní vysvětlení. Přechodné chyby a `429` mají
omezené retry a zrušitelné čekání. Timeout po POST nesmí vést k nekonečnému
vytváření reportů: nejprve ověřit, zda report vznikl, a případnou
nejednoznačnost přiznat. Pamatovat známé čekající `reportId` pro pokračování.

Selhání downloadu nebo archivu neoznačit jako dokončený rok.
Selhání importu neznehodnotí archivovaný CSV soubor.
Celkový dialog rozlišuje úspěch, částečný výsledek, zrušení a chybu;
uvádí roky, umístění CSV a skutečné počty importovaných záznamů.

## 10. Kroky implementace

### Závazné rozdělení odpovědností

Nová třída `Trading212API` bude v jediném modulu
`src/tradingtools/trading212_api.py`. Bude zajišťovat:

- správu API Key a Secret přes Windows Credential Manager;
- autentizaci, ověření účtu a povolené HTTP operace;
- vytvoření reportů, kontrolu stavu, rate limiting, timeouty a retry;
- bezpečné stahování CSV bez předávání API credentials na download URL;
- volbu ročních exportů, pokračování čekajících reportů a jejich stav;
- roční archiv, validaci souborů, verze, hash a archivní metadata;
- informace o průběhu a zrušení bez přímého přístupu k Tkinter widgetům.

Nevytvářet pro tuto integraci oddělené implementační třídy/moduly klienta,
credential storage, archivu a synchronizační služby. Jednotlivé kroky níže
jsou části implementace stejné třídy, nikoli návrh dalších tříd.

`Trading212API` nebude zapisovat do analytických tabulek ani provádět
daňové výpočty. Jejím výstupem budou ověřené cesty k archivovaným CSV
a metadata průběhu. Existující aplikační obsluha předá soubory importeru.
GUI zůstává v současných UI částech; CSV import a obecné DB operace
zůstávají v `DatabaseManager` a repositories.
Do `DatabaseManager` nepřidávat HTTP požadavky, credentials, polling
ani jinou logiku specifickou pro API.

### Etapový postup

Rozdělení odsouhlaseno jako způsob práce 2026-11-16. Implementovat vždy
jen jednu zadanou etapu. Po jejím dokončení uvést změny, výsledky testů
a případné otevřené otázky, poté zastavit. Další etapu zahájit až po
potvrzení uživatele; nespouštět automaticky celý plán.

Každá etapa musí být samostatně ověřitelná. Do dokončení etapy 6
nepřidávat funkční synchronizační příkaz do GUI. Skutečné klíče, osobní
CSV ani účetní údaje nevkládat do repository nebo testovacích fixtures.

#### Etapa 0 — ověření proveditelnosti

**Stav:** dokončeno v rozsahu popsaném v části 12.

- Ověřeno vytvoření a stažení CSV s přidělenými oprávněními.
- Porovnány aktuální a starší ruční exporty.
- Ověřen celoroční report, oba typy úroků a dividendové daňové údaje.
- Zjištěno riziko místního času ve starých DB.

Toto ověření nenahrazuje automatické testy ani řešení starých timestampů.
Není potřeba znovu začínat reálným API exportem.

#### Etapa 1 — třída a Windows Credential Manager

**Stav:** dokončeno 2026-11-16; další etapa nebyla zahájena.
**Předpoklad:** schválení etapy splněno.

- Vytvořit `Trading212API` v `src/tradingtools/trading212_api.py`.
- Přidat `keyring` do závislostí a ověřit nativní Windows backend.
- Implementovat správu dvojice API Key/Secret: uložení, načtení, změnu
  a odstranění; oddělení účtu/prostředí a explicitní chyby bez fallbacku.
- Doplnit jen čtecí ověření identity účtu a autentizaci potřebnou pro
  bezpečné první uložení či změnu klíče.

**Ověření:** testy s mockem úložiště a HTTP: opětovné načtení, oddělení
účtů/prostředí, odmítnutí nebezpečného backendu, zachování původního
pověření po neúspěšné změně, žádné tajné hodnoty v souborech/logu.

**Hranice etapy:** bez exportů, archivu, GUI a zápisů do analytické DB.

**Výsledek:**

- Implementováno v [Trading212API](../src/tradingtools/trading212_api.py):
  `save_credentials`, `load_credentials`, `verify_account`,
  `delete_credentials`; změna klíče používá opět `save_credentials`.
- Pověření jsou v jednom nativním záznamu pro účet/prostředí s lokální
  perzistencí. Zápis používá veřejné Windows `CredWrite` přes
  `pywin32-ctypes`: běžné `WinVaultKeyring.set_password` při přepsání
  uchovává kopii starého Secretu pod složeným názvem. Přímý nativní
  overwrite tomuto nežádoucímu uchovávání zabrání.
- Doplněny závislosti `keyring` a pro Windows `pywin32-ctypes`.
- [Offline testy](../tests/test_trading212_api.py): 8 testů prošlo,
  včetně chyb úložiště/HTTP, izolace účtů, změny pověření, odmítnutí
  jiného backendu a potlačení citlivých podrobností v chybách/logu.
- Pylance nehlásí syntaktické ani typové chyby v novém kódu.
- Na aktuálním Windows ověřena dostupnost `WinVaultKeyring`; skutečné
  uživatelské pověření nebylo načteno ani uloženo a API nebylo kontaktováno.

Použitý cílený příkaz:

```powershell
python -m unittest discover -s tests -p "test_trading212_api.py" -v
```

#### Etapa 2 — vytvoření a stažení jednoho CSV reportu

**Stav:** čeká. **Předpoklad:** etapa 1.

- Doplnit povolený POST pro report, GET seznamu reportů a jejich stavy.
- Zavést rate limits, timeouty, konečné retry, pokračování známého
  reportId a zrušitelné čekání.
- Bezpečně stáhnout a ověřit CSV do zadané lokální cesty bez předávání
  API Authorization na download URL.

**Ověření:** fiktivní report projde od požadavku po validní soubor;
testy pokryjí `Failed`, `Canceled`, `401`, `403`, `429`, timeout po POST,
neplatný CSV a nebezpečné přesměrování. Žádná obchodní API operace.

**Hranice etapy:** jeden zadaný interval, bez plánování více roků,
ročního archivu, GUI a importu do DB.

#### Etapa 3 — roční archiv a plánování exportů

**Stav:** čeká. **Předpoklad:** etapa 2.

- Do stejné třídy doplnit výběr roků od uživatelem zadaného prvního roku.
- Rozlišovat uzavřený rok a průběžný aktuální rok; finalizovat předchozí
  rok při přechodu do nového.
- Implementovat atomické CSV soubory a archivní metadata, hash,
  zachování změněných verzí a opakované použití nezměněného obsahu.
- Doplnit chybějící roky, obnovu vybraného staršího exportu a pokračování
  po přerušeném stahování; respektovat společné limity API.

**Ověření:** prázdný archiv, přelom roku, přestupný rok, neúplné pokrytí,
nezměněná/změněná revize, chyba disku a pád mezi CSV a metadaty.

**Hranice etapy:** archiv a API jsou použitelné bez Tkinter a otevřené DB.
Ještě neimportovat automaticky do databáze.

#### Etapa 4 — spolehlivý výsledek existujícího CSV importu

**Stav:** čeká. **Předpoklad:** dostupná ověřená CSV struktura z etapy 0.
Na etapách 1–3 technicky nezávisí; pořadí lze změnit pouze po dohodě.

- Opravit přímo související předávání výsledků zápisů a počítání
  vložených/duplicitních řádků.
- Vrátit explicitní chyby, neznámé a záměrně vynechané akce,
  aby konečný dialog nepovažoval částečný import za úplný úspěch.
- Umožnit krátké dávky a zrušení importu bez změny finančního mapování.
- Zachovat použitelnost současného ručního CSV importu.

**Ověření:** malé syntetické CSV; správné počty při prvním a opakovaném
importu, chyba jednoho řádku, neznámá akce a přerušení dávky.
Existující finanční souhrny se nezmění.

**Hranice etapy:** bez API logiky v `DatabaseManager`, bez plošné
migrace starých časů a bez nové GUI synchronizace.

#### Etapa 5 — dividendová identita a staré časové údaje

**Stav:** čeká. **Předpoklad:** etapa 4 a odsouhlasení konkrétního
postupu migrace/reconciliation před změnou historických dat.

- Ověřit a doplnit stabilní identitu dividend z CSV, pokud ji export
  poskytuje; odlišit legitimní výplaty stejného času a instrumentu.
- Vyřešit návaznost starých záznamů z `Time` na nové `Time (UTC)`,
  aniž by se plošně posouvaly neověřené timestampy.
- Nejednoznačné historické shody a změny finančního obsahu hlásit
  jako konflikty; nepřepisovat spárované obchody.
- Potřebnou migraci provést přes existující verze schématu,
  transakčně, po záloze a se zachováním místních ID/vazeb.

**Ověření:** starý ruční CSV -> nový UTC CSV, zimní/letní čas,
opakovaná migrace, dvě rozdílné dividendy stejného času a nejednoznačná
shoda. Žádné nové duplicity ani ztráta historických dat/párování.

**Hranice etapy:** bezpečnost lokálních importů; stále bez automatického
spouštění API synchronizace z GUI.

#### Etapa 6 — propojení s GUI a kompletní synchronizační průběh

**Stav:** čeká. **Předpoklady:** etapy 1–5.

- Přidat příkaz menu, první nastavení účtu/archivu/prvního roku
  a správu uloženého pověření.
- Spojit výstupy `Trading212API` s existujícím CSV importerem.
  HTTP, exportní a archivní logika zůstává v jediné třídě.
- Realizovat worker, frontu událostí a `root.after()`; SQLite a Tkinter
  obsluhovat na správném vlákně.
- Zavést průběh, zrušení, ochranu proti souběžným importům/výměně DB,
  stav importu jednotlivých reportů a pokračování po částečném běhu.
- Obnovit filtry/pohledy a zobrazit přesný úplný/částečný/chybový výsledek.

**Ověření:** prázdná DB se zadaným prvním rokem, DB s historickými CSV,
opakovaná synchronizace, chyba importu po archivaci, zrušení a zavření
okna během čekání. GUI zůstává ovladatelné a nevznikají duplicity.

**Hranice etapy:** žádný nový průvodce obnovou ani automatická synchronizace
při startu; jen dohodnutý ručně spouštěný příkaz.

#### Etapa 7 — obnova, Windows executable a závěrečná regrese

**Stav:** čeká. **Předpoklad:** etapa 6.

- Ověřit lokální obnovu prázdné DB z doporučených ročních CSV bez API,
  se stejnými kurzy a s přiznanými omezeními párování/nastavení.
- Spustit celou existující testovací sadu po cílených testech etap.
- Ověřit zabalenou Windows aplikaci a nativní backend `keyring`.
- Doplnit [README](../README.md) a [CSV poznámky](CSV_IMPORT_NOTES.md):
  první propojení, první rok, správa klíče, archiv, chyby a obnova.

**Ověření:** shoda podporovaných transakcí a finančních souhrnů po obnově,
funkční credential storage v executable a zachované běžné funkce aplikace.

Reálné API kontroly jen s výslovným souhlasem uživatele; automatické testy
musí fungovat offline s fiktivními daty a bez skutečného Správce pověření.

Při implementaci doplnit `keyring` do [pyproject.toml](../pyproject.toml);
ostatní závislosti vybírat podle potřeby. Použít existující
[paths helpers](../src/tradingtools/paths.py) pro aplikační konfiguraci,
ne však jako důvod k pevnému umístění uživatelského archivu do AppData.

## 11. Testy a akceptační kritéria

Testovat fiktivní HTTP odpovědi, malé CSV fixtures, dočasné archivní složky
a lokální SQLite DB. Automatické testy bez skutečných credentials a sítě.
Credential storage v automatických testech nahradit testovacím adaptérem;
nezapisovat do skutečného uživatelského Správce pověření.

- Uložení a následné načtení pověření nevyžaduje opětovné zadání;
  prostředí a účty mají oddělené záznamy.
- Změna/odstranění pověření nepoškodí DB ani archiv; chyba ověření nového
  klíče zachová původní funkční záznam.
- Chyba úložiště nebo nebezpečný backend blokuje API funkci bez zápisu
  credentials do souboru; configuration/DB/logy neobsahují tajné hodnoty.
- Report request zahrne správný rok a všechny obsahové přepínače;
  jiné POST/PUT/DELETE než vytvoření exportu klient nepoužije.
- Stavy reportu, rate limits, timeout a zrušení; polling více roků
  nepřekročí limit společného endpointu.
- Přelom roku a přestupný rok: žádná mezera ani nesprávně označené pokrytí.
- Aktuální rok je průběžný; při dalším roce vznikne finální předchozí rok.
- Identický obsah nevytvoří další kopii; změněný obsah vytvoří revizi
  bez ztráty předchozího souboru.
- Neúplný download, HTML místo CSV, chyba disku a poškozený hash
  nevedou k označení archivu za validní.
- Pád mezi CSV a metadaty neztratí již zveřejněný report.
- Opakovaný import i obnovení po částečném běhu vloží 0 duplicit;
  dvě legitimní stejnočasové události se nesloučí.
- CSV/API ID konflikty, dividendové daně, úroky a oba režimy kurzů
  mají ověřené výsledky; chybějící údaje nejsou nahrazeny nulou.
- Originální CSV obsahuje i nepodporované akce, které UI přizná.
- Jiný účet/prostředí se odmítne před importem; download neobdrží API klíč.
- Obnova nové DB z doporučených ročních CSV funguje bez API a dá stejné
  počty podporovaných transakcí a finanční souhrny při stejných kurzech.
- GUI zůstává ovladatelné a nepovolí souběžné změny DB.
- Třídu `Trading212API` lze testovat bez Tkinter okna a otevřené DB.
  API a credential logika není rozptýlena do `app.py` či `dbmanager.py`.

Nejdříve cílené testy, následně dotčené regresní testy a před dokončením:

```powershell
python -m unittest discover -s tests -v
```

Ruční ověření nejdříve demo, reálný účet až se souhlasem uživatele.
Ověřit také Windows executable, zabalení `keyring` a dostupnost jeho
nativního Windows backendu, nejen běh ze zdrojových souborů.

## 12. Výsledky prvního ověření

Datum ověření: 2026-11-15. API bylo ověřeno se souhlasem uživatele,
bez importu do DB a bez změny aplikace. Stažená CSV a podrobné porovnání
zůstávají mimo veřejné repository v soukromé složce uživatele.
Do tohoto dokumentu nepatří credentials, identita účtu ani finanční hodnoty.

- Se sadou oprávnění `Account data`, `History`, `History - Dividends`,
  `History - Orders`, `History - Transactions`, `Metadata` prošlo načtení
  přehledu účtu, vytvoření reportu se všemi čtyřmi obsahovými přepínači,
  kontrola stavu i download bez API Authorization.
  Ověření dokazuje dostatečnost této sady, nikoli její minimálnost;
  nezkoušelo se odebrání jednotlivých oprávnění.
- Prošel jeden celý uzavřený kalendářní rok i průběžný rozsah aktuálního roku.
  Nebyly testovány všechny možné roční hranice, limity velikosti a intervalů.
- V aktuálním CSV se všechny řádky shodovaly s ručním exportem na všech
  sloupcích po normalizaci numerického formátování a UTC času.
  Hlavičky byly stejné. Nejde o tvrzení o byte-for-byte shodě souborů.
- Starší ruční export a nově vytvořený API report obsahovaly stejné události
  podle akce, času normalizovaného jako UTC, ID a ISIN.
  Shodovaly se částky, ceny, poplatky, srážkové daně a příslušné měny.
  Byly ověřeny také oba typy úroků.
- U staršího vzorku se lišily některé názvy instrumentů, `Currency (Result)`
  u nákupů a drobná přesnost `Exchange rate` u dividend.
  Tyto rozdíly nelze samy o sobě klasifikovat jako změnu transakce.
  Při deduplikaci porovnávat finančně relevantní údaje, ne celý řádek
  bez zohlednění verze exportu.
- Starší ruční exporty používají `Time`; nové API CSV používá `Time (UTC)`.
  Uživatel potvrdil, že starší soubory exportoval dříve. V porovnaném vzorku
  byla UTC interpretace starého času konzistentní s API, nikoli však
  obecně ověřená pro všechny historické exporty.
- Přímý test současného `DatabaseManager.timestr_to_timestamp` pro stejné
  syntetické časy s offsetem a bez něj na aktuálním počítači prokázal
  zimní rozdíl -3600 sekund a letní -7200 sekund. To je blokující riziko
  pro deduplikaci starých dividend podle `(timestamp, isin_id)`.

Závěr: exportní přístup i zadaná oprávnění jsou prakticky ověřené.
Před automatickým zápisem vyřešit identitu dividend a návaznost časů
ve starých DB; normalizaci dat ani migraci toto ověření neprovedlo.
Credential Manager byl následně implementován v etapě 1 a ověřen offline
testy a kontrolou dostupnosti nativního backendu. Reálný zápis uživatelského
klíče a Windows executable zatím ověřeny nebyly.

## 13. Rozhodnutí před realizací

Zvolený směr: API export CSV, současný import a uchování ročních přehledů.
Potvrzeno: Windows Credential Manager od první verze, bez plaintext fallbacku.
Před implementací ještě potvrdit:

- Výchozí složku a UI výběru archivu, první rok a roční časové členění.
- Zachování změněných verzí bez automatického mazání.
- Způsob explicitního obnovení starých roků.
- Nutné úpravy CSV importu podle ověřených exportních fixtures.

Tento dokument eviduje etapový postup. Dokončení etapy není pokynem
k automatickému zahájení další etapy.

## 14. Oficiální zdroje

Ověřeno podle dokumentace dostupné 2026-11-15:

- [Přehled API a autentizace](https://docs.trading212.com/api)
- [Vytvoření CSV reportu](https://docs.trading212.com/api/historical-events/requestreport.md)
- [Seznam reportů, stavy a downloadLink](https://docs.trading212.com/api/historical-events/getreports.md)
- [Identita účtu](https://docs.trading212.com/api/accounts/getaccountsummary.md)
- [API klíče a oprávnění](https://helpcentre.trading212.com/hc/en-us/articles/14584770928157-Trading-212-API-key)
