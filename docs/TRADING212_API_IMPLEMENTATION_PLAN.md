# Plán integrace Trading 212 API

> **Nahrazený návrh (2026-11-15):** Rozhodli jsme se místo přímého mapování
> JSON historií použít automatický export CSV přes API a následný import
> do TradingTools, včetně uchování ročních CSV pro obnovu dat.
> Platný návrh je v [plánu exportu/importu CSV](TRADING212_CSV_SYNC_IMPLEMENTATION_PLAN.md).
> Tento dokument zůstává zachován jako historický návrh; jeho požadavek
> na pouze GET požadavky se na nové řešení nevztahuje.

Datum: 2026-11-15  
Stav: návrh k odsouhlasení; implementace nezačala.

## 1. Cíl

Umožnit uživateli načíst nové události z investičního účtu Trading 212
přímo do otevřené databáze, bez ručního exportu a importu CSV.

- V menu `File` přidat `Read transactions from Trading212...`.
- Synchronizaci spouští uživatel; nezavádět automatické načítání při startu.
- Integrace je vůči Trading 212 výhradně read-only.
- Existující import CSV, výpočty, párování obchodů a režim kurzů zachovat.
- Žádné zadávání, změny ani rušení objednávek.

Read-only se týká vzdáleného účtu. Zápis načtených dat do místní databáze
je samozřejmě součástí funkce.

## 2. Rozsah dat

| Kategorie | Zdroj API | Návrh pro první verzi |
| --- | --- | --- |
| Nákupy/prodeje akcií a ETF | `/equity/history/orders` | Ano; jednotlivá provedení typu `TRADE`, včetně částečných provedení. |
| Dividendy | `/equity/history/dividends` | Ano, podmíněno ověřením částek a srážkové daně. |
| Náhradní dividendové platby | `/equity/history/dividends` | Ano pro podporované dividendové typy `...MANUFACTURED_PAYMENT`; zachovat původní typ. |
| Výnos ze zapůjčení akcií | `/equity/history/transactions`, `LENDING_INTEREST` | Ano. |
| Úrok z volné hotovosti | `/equity/history/transactions`, `INTEREST_ON_FREE_CASH` | Ano. |
| Vklady, výběry a převody | `DEPOSIT`, `WITHDRAW`, `TRANSFER` | Zatím neukládat do analytických tabulek; uvést v přehledu záměrně vynechaných událostí. |
| Samostatné poplatky | `FEE` | Zatím mimo rozsah; výslovně hlásit. Poplatky u obchodů řešit při mapování obchodů. |
| Splity a ostatní korporátní události | Typy `fill.type` jiné než `TRADE` | Nezaměňovat za běžný obchod; evidovat upozornění a řešit samostatně. |
| Ostatní dividendové distribuce | Další hodnoty dividendového `type` | Nepřevádět automaticky na běžnou dividendu bez ověřeného mapování. |

Vynechané korporátní události mohou způsobit neúplný přehled pozic a párování.
Výsledek synchronizace na to musí viditelně upozornit; nesmí tvrdit, že byl
účet načten kompletně. Jejich plná podpora je případné navazující rozšíření.

## 3. Ověřené možnosti a omezení API

- API je v beta verzi a podporuje účty Invest a Stocks ISA.
- Demo a live prostředí mají oddělené adresy.
- Autentizace používá API Key a API Secret přes HTTP Basic nad HTTPS.
- Historické endpointy mají limit 20 požadavků za minutu, maximálně
  50 položek na stránku a vracejí `nextPagePath`.
- Historie obchodů a dividend dokumentuje `cursor`, `ticker`, `limit`,
  nikoli přímý filtr „od data“.
- Historie peněžních pohybů má navíc parametr `time`.
- Provedení obchodu má `fill.id` a `fill.filledAt`; objednávka má vlastní
  `order.id`. ID objednávky není identifikátor jednotlivého provedení.
- Dividendy a peněžní pohyby mají `reference`.
- Přehled účtu vrací `id` a hlavní měnu; vyžaduje oprávnění `account`.
- Dividendový endpoint nemá samostatné pole pro sraženou daň.
  `amount` je v hlavní měně účtu, `grossAmountPerShare` v měně instrumentu.
- API uvádí omezení multi-currency podpory. Úplnou shodu částek s CSV
  a použitelnost pro stávající daňové výpočty nelze předem předpokládat.

Pořadí historických záznamů, přesnou interpretaci `time`, význam dividendové
částky jako čisté/hrubé a návaznost ID na CSV je nutné ověřit.
Bez potvrzeného pořadí nelze bezpečně ukončit stránkování při první staré události.

## 4. Návaznost na současnou aplikaci

- [MenuManager](../src/tradingtools/ui/menu_manager.py) spravuje menu
  a dostupnost importu podle otevřené databáze.
- [TradingToolsApp](../src/tradingtools/app.py) obsluhuje import CSV,
  aktualizaci roků ve filtrech a obnovení pohledů.
- [DatabaseManager](../src/tradingtools/db/dbmanager.py) mapuje CSV,
  převádí částky do CZK a zprostředkovává zápisy do repositories.
- [TradesRepository](../src/tradingtools/db/repositories/trades.py)
  má unikátní `id_string`, kladná množství nákupů a záporná množství prodejů.
- [InterestsRepository](../src/tradingtools/db/repositories/interests.py)
  již rozlišuje úrok z hotovosti a ze zapůjčení, s unikátním `id_string`.
- [DividendsRepository](../src/tradingtools/db/repositories/dividends.py)
  nemá brokerovo ID; používá `UNIQUE(timestamp, isin_id)`.
  To nestačí pro dvě různé výplaty stejného instrumentu ve stejném čase.
- Repository zápisy nyní samy volají `commit()`. Atomický zápis události,
  její externí identity a stavu synchronizace vyžaduje cílenou úpravu.
- Počty vložených řádků nelze stavět pouze na `lastrowid` po
  `INSERT OR IGNORE`; nová synchronizace musí rozlišovat vložení a duplicitu.
- [Poznámky k CSV](CSV_IMPORT_NOTES.md) popisují záměrně ignorované
  a nepodporované akce. CSV podporuje `Time` i `Time (UTC)`.

API data nebalit do uměle vytvořeného CSV DataFrame. Oddělit mapování API
od mapování CSV a sdílet ověřené převody, validaci a ukládání.
Nevytvářet obecný framework pro více brokerů.

## 5. Uživatelský průběh

1. Uživatel otevře nebo vytvoří databázi.
2. Zvolí `File > Read transactions from Trading212...`.
3. Při prvním použití zadá API Key, API Secret a vybere prostředí.
4. Aplikace ověří spojení a zobrazí identitu účtu k potvrzení vazby na DB.
5. Načte potřebné historie, odstraní duplicity a uloží ověřené události.
6. Obnoví filtry a pohledy stejným způsobem jako po CSV importu.
7. Zobrazí počty načtených, vložených, duplicitních, vynechaných
   a chybných záznamů po kategoriích.

Příkaz je bez databáze zakázaný. Během běhu zabránit druhé synchronizaci,
CSV importu i výměně/uvolnění databáze. Zobrazit průběh a umožnit zrušení,
včetně čekání na rate limit.

Síťovou práci provádět mimo GUI vlákno. GUI aktualizovat přes frontu
a `root.after()`. Existující SQLite spojení nepředávat do síťového vlákna;
validované dávky ukládat na vlákně vlastnícím DB v krátkých transakcích.
Při ukončení aplikace synchronizaci bezpečně zrušit.

## 6. Read-only a přihlašovací údaje

- Používat pouze `GET` na explicitně povolených čtecích endpointech.
- Vyžadovat jen `account`, `history:orders`, `history:dividends`
  a `history:transactions`; nezapínat obchodní oprávnění.
- Do klienta vůbec nepřidávat metody pro zápis na vzdálený účet.
- Pro první verzi doporučeno držet credentials pouze v paměti relace,
  s maskovaným vstupem pro Secret. Trvalé uložení až po odsouhlasení,
  výhradně přes systémové úložiště přihlašovacích údajů.
- Neukládat credentials do SQLite, běžného JSON, logů ani dokumentace.
- Používat ověřování TLS a konečné timeouty.
- `nextPagePath` přijímat pouze pro očekávaný endpoint a prostředí.
  Neposílat Authorization na jiný host ani přes neověřené přesměrování.
- Klíč s většími oprávněními zůstává rizikový i při GET-only aplikaci;
  uživatele instruovat k vytvoření samostatného read-only klíče.

## 7. Identita a migrace databáze

Navrhovaná logická struktura, finální DDL až po ověření API/CSV identity:

- Vazba DB na jedno prostředí a jeden Trading 212 účet; pro první verzi
  neumožnit směšování více účtů. Identitu ověřit před každým načtením.
- Evidence externích událostí s unikátním klíčem
  `(provider, environment, account_id, stream, external_id)`.
  Pro obchody použít `fill.id`, pro dividendy/pohyby `reference`.
- Vazba externí události na místní záznam a původní typ události.
- Stav synchronizace zvlášť pro obchody, dividendy a peněžní pohyby.
- Upravit dividendovou unikátnost tak, aby různé externí výplaty mohly
  existovat ve stejném čase pro stejný instrument; zachovat ochranu CSV
  importu proti opakovanému načtení.

Použít existující mechanismus verzování schématu. Migrace musí být
transakční, zachovat stávající data i párování a být bezpečná při opakovaném
otevření DB. Před změnou schématu nabídnout zálohu.

Při přechodu z CSV ověřit, zda CSV `ID` odpovídá `fill.id`, `order.id`
nebo jiné identitě. Nelze to předpokládat ani vyřešit jen prefixem ID.
U dividend CSV import nyní ID neukládá; jednoznačné historické shody
ověřit podle dostupných údajů. Nejednoznačné shody neukládat jako nové
ani je tiše neslučovat; zobrazit konflikt k vyřešení.

## 8. Inkrementální synchronizace

1. Ověřit účet a načíst stav jednotlivých historií.
2. Při první synchronizaci prázdné DB načíst celou dostupnou historii.
3. U DB s CSV použít nejnovější záznam příslušné kategorie jako orientační
   hranici, nikoli jako důkaz úplnosti. Úroky posuzovat podle obou typů;
   nejnovější hotovostní úrok nesmí vynechat starší lending interest.
4. Pro další běhy použít poslední úspěšně dokončenou hranici s překryvem.
   Výchozí návrh překryvu je 7 dní; délka není zárukou proti pozdějším opravám.
5. Stránkovat pomocí celého `nextPagePath`, filtrovat lokálně a deduplikovat
   pomocí externích identit. Časy na hranici zahrnout, nevyužívat pouze `>`.
6. Časové údaje normalizovat jako timezone-aware UTC. Zachovat přesnost
   zdrojového času pro identitu/reconciliation; zkrácení na DB sekundy
   nesmí být jediným deduplikačním klíčem.
7. Ukončit načítání podle času pouze při ověřeném pořadí konkrétní historie.
   Jinak projít všechny stránky. Detekovat opakující se stránkovací cestu.
8. Ukládat záznam a jeho identitu atomicky. Hranici historie posunout
   až po úplném úspěchu dané historie, nikoli po posledním vloženém řádku.
9. Při chybě/zrušení již potvrzené dávky zůstanou; hranice se neposune.
   Další spuštění bezpečně zopakuje načítání bez duplicit.

Nepodporované události mají explicitní výsledek a upozornění. Nevyřešené
chyby mapování nebo identity blokují posun hranice dotčené historie.
Historie mohou uspět nezávisle; celkový dialog musí přiznat částečný výsledek.

Překryv nezachytí libovolně starou dodatečnou událost nebo opravu.
Zajistit možnost explicitního opětovného načtení celé historie se stejnou
deduplikací. Existující událost se změněným obsahem hlásit jako konflikt;
nepřepisovat automaticky obchod, který už může být spárovaný.

## 9. Mapování částek a daňová správnost

- Obchody mapovat podle `order.side` a konkrétního `fill`, nikoli celkového
  množství objednávky. Znaménka sladit s existující DB.
- ISIN brát z instrumentu; API ticker nepovažovat automaticky za CSV ticker.
  Při existujícím ISIN nepřepisovat bezdůvodně zobrazovací údaje.
- Ověřit znaménka a význam `walletImpact.netValue`, jeho měnu, `fxRate`
  a položky `taxes` proti odpovídajícím CSV událostem.
- Zachovat oddělení stamp duty, conversion fee a French transaction tax.
  Ostatní poplatky nesmí zmizet ani být započítány dvakrát; není-li pro ně
  správné uložení, označit událost jako nepodporovanou.
- Zachovat výběr denních ČNB / ročních GFŘ kurzů v databázi. Brokerův
  FX kurz nenahrazuje kurz používaný pro české daňové výpočty.
- Chybějící roční kurz je explicitní chyba, nikoli nulová částka.
- Dividendy: před implementací ověřit čistou/hrubou částku, měnové převody,
  zaokrouhlení a dostupnost skutečně sražené daně.
  Rozdíl částek v různých měnách není automaticky sražená daň.
- Neodvozovat skutečnou daň pouze z konfigurované sazby a nevkládat nulu
  jako náhradu chybějícího údaje. Pokud nelze sestavit správný stávající
  dividendový záznam, výslovně ponechat CSV jako zdroj dividend.
- Výnos ze zapůjčení ukládat jako úrok, nikoli dividendu. Tento peněžní
  endpoint neposkytuje vazbu na konkrétní půjčený instrument.

## 10. Chyby a provozní chování

- `401`: vysvětlit neplatné credentials; nezkoušet je opakovaně bez změny.
- `403`: uvést chybějící oprávnění příslušné historie.
- `429`: čekat podle rate-limit hlaviček; čekání musí jít zrušit.
- Timeouty a přechodné serverové chyby: omezené opakování s prodlevou.
- Nevalidní JSON, chybějící identita či povinná pole: konkrétní chyba,
  žádné success-shaped prázdné výsledky.
- Logovat technický důvod bez credentials a celých účetních payloadů.
- Výsledkové počty vycházejí ze skutečného výsledku zápisu, ne z počtu
  přijatých položek nebo pouhé přítomnosti ID.

## 11. Kroky implementace

1. **Ověřit datovou kompatibilitu.** Na lokálních vzorcích/demo účtu
   porovnat API s CSV: ID, časy, částečná provedení, dividendy, úroky,
   měny a poplatky. Neodesílat skutečná uživatelská data mimo aplikaci.
2. **Uzavřít rozsah a blokující rozhodnutí.** Zejména dividendové daně,
   CSV/API identita a způsob hlášení nepodporovaných událostí.
3. **Implementovat migraci a identitu.** Doplnit stav synchronizace
   a cílené transakční zápisy bez změny existujících výpočtů.
4. **Přidat read-only API klienta.** Malý modul pod `src/tradingtools`,
   autentizace, povolené GET endpointy, stránkování, timeouty a limity.
   HTTP knihovnu vybrat až při implementaci; závislosti zapsat do
   [pyproject.toml](../pyproject.toml), jen pokud jsou potřebné.
5. **Přidat mapování a synchronizační službu.** Oddělit síť, interpretaci
   událostí a DB zápis; sdílet existující finanční pravidla.
6. **Zapojit GUI.** Dialog credentials, nový příkaz, neblokující průběh,
   zrušení, stavy menu a konečný přehled.
7. **Ověřit regresi a popsat použití.** Aktualizovat
   [README](../README.md) a [CSV poznámky](CSV_IMPORT_NOTES.md),
   včetně read-only klíče a omezení proti CSV.

Každý krok začít až po splnění jeho skutečných předpokladů.
Tento dokument není pokyn k zahájení implementace.

## 12. Testy a akceptační kritéria

Automatické testy používat s fiktivními HTTP odpověďmi a lokální testovací DB;
nevyžadovat reálný účet, credentials ani síť.

- První import a opakovaný import: druhý běh vloží přesně 0 duplicit.
- Dvě různé události stejného času, dvě dividendy stejného instrumentu
  a několik provedení jedné objednávky zůstanou samostatné.
- CSV -> API i API -> CSV nevytvoří duplicity při ověřené identitě;
  nejednoznačná identita skončí viditelným konfliktem.
- Oddělené hranice neztratí starší lending interest ani dividendu
  kvůli novějším obchodům/hotovostním úrokům.
- Ověřit UTC offsety, hraniční časy a více stránek.
- `429`, timeout, zrušení a chyba DB nevedou k předčasnému posunu hranice.
  Opakování po částečném běhu nenásobí data.
- Účet/prostředí neodpovídající DB se odmítne před zápisem.
- Jiný host v pagination/redirect nedostane credentials.
- HTTP test prokáže, že klient používá jen povolené GET požadavky.
- Ověřit finanční hodnoty proti ručně spočítaným fixture očekáváním,
  v obou režimech kurzů; chybějící daň/kurz se nesmí tvářit jako nula.
- Migrace zachová existující záznamy, vazby párování a CSV deduplikaci.
- GUI zůstává ovladatelné, nedovolí souběžné importy a správně hlásí
  prázdný, úplný, částečný i chybový výsledek.

Nejdříve spustit cílené nové testy a přímo dotčené regresní testy.
Před dokončením integrace spustit existující sadu:

```powershell
python -m unittest discover -s tests -v
```

Ruční ověření provést nejdříve v demo prostředí; následné lokální srovnání
s CSV z reálného účtu jen se souhlasem uživatele a read-only klíčem.
Ověřit také zabalení případných nových závislostí do Windows executable.

## 13. Rozhodnutí před zahájením

- Potvrdit první rozsah: obchody, dividendy, lending interest a cash interest.
- Potvrdit dočasné vynechání samostatných poplatků a korporátních událostí
  s viditelným upozorněním na neúplnost.
- Rozhodnout o dividendách, pokud API nedodá dost údajů pro současné
  daňové výpočty: blokovat jejich API import a ponechat CSV, nebo zvlášť
  odsouhlasit rozšíření modelu pro neúplná data.
- Potvrdit jeden účet na DB a credentials pouze pro aktuální relaci.
- Po ověření pořadí historie upřesnit překryv, první import z existující
  CSV databáze a UI pro úplné opětovné načtení.

## 14. Oficiální zdroje

Ověřeno podle dokumentace dostupné 2026-11-15:

- [Přehled API, autentizace, limity a stránkování](https://docs.trading212.com/api)
- [Přehled a identita účtu](https://docs.trading212.com/api/accounts/getaccountsummary.md)
- [Historie obchodů](https://docs.trading212.com/api/historical-events/orders_1.md)
- [Dividendy](https://docs.trading212.com/api/historical-events/dividends.md)
- [Peněžní pohyby a úroky](https://docs.trading212.com/api/historical-events/transactions.md)
- [Vytvoření klíče a read-only oprávnění](https://helpcentre.trading212.com/hc/en-us/articles/14584770928157-Trading-212-API-key)
