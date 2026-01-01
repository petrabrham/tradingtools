# Annual Exchange Rates Feature

## Overview
For databases configured to use annual GFŘ rates, exchange rates must be imported from text files before importing transactions. This ensures data consistency and compliance with Czech tax law.

## Key Concepts

### Exchange Rate Validation
When a database is configured for annual rates:
- **All** exchange rates must exist in the `annual_rates` table
- Attempting to import a transaction will **fail** if the required rate is missing
- Error message: `"Annual exchange rate for {currency} in year {year} not found in database"`

This prevents:
- Inconsistent data (mixing database rates with calculated rates)
- Importing transactions without proper exchange rate documentation
- Ambiguity about which rates were used

### Annual Rates Table Schema
```sql
CREATE TABLE annual_rates (
    year INTEGER NOT NULL,
    currency TEXT NOT NULL,
    amount INTEGER NOT NULL,
    rate REAL NOT NULL,
    country TEXT,
    PRIMARY KEY (year, currency)
)
```

**Fields:**
- `year`: Calendar year (e.g., 2024)
- `currency`: Three-letter code (USD, EUR, JPY, etc.)
- `amount`: Number of currency units (1 for most, 100 for JPY/PHP, 1000 for IDR)
- `rate`: Exchange rate in CZK for the specified amount
- `country`: Optional country name for reference

**Example records:**
```
year=2024, currency='USD', amount=1, rate=23.28  → 1 USD = 23.28 CZK
year=2024, currency='JPY', amount=100, rate=15.35  → 100 JPY = 15.35 CZK
year=2024, currency='EUR', amount=1, rate=25.16  → 1 EUR = 25.16 CZK
```

## Importing Annual Rates

### File Format
Text file with one currency per line:

```
Country name amount CURRENCY rate
```

**Examples:**
```
Austrálie dolar 1 AUD 15,31
Japonsko jen 100 JPY 15,35
EMU euro 1 EUR 25,16
USA dolar 1 USD 23,28
```

**Format notes:**
- Both `.` and `,` are accepted as decimal separators
- Country name can contain spaces and special characters
- Amount is typically 1, but can be 100 (JPY, PHP) or 1000 (IDR)
- Currency code must be 3 letters (ISO 4217 standard)

### Using the UI

1. **Create or open a database** configured for annual rates
2. **File → Import Annual Exchange Rates...**
3. **Select year** (e.g., 2024)
4. **Browse** to select the rates file
5. **Click Import**

The import dialog shows:
- Years already imported (in blue)
- File selection
- Import/Cancel buttons

### Import Results
After import, you'll see:
- Number of rates imported
- Number of lines skipped
- List of any errors encountered

**Example:**
```
Import completed for year 2024:

Imported: 31 rates
Skipped: 0 lines
```

### Programmatic Import
```python
# Import rates for 2024
result = db.import_annual_rates_from_file('rates_2024.txt', 2024)

print(f"Imported: {result['imported']}")
print(f"Skipped: {result['skipped']}")
if result['errors']:
    for error in result['errors']:
        print(f"Error: {error}")
```

## Working with Annual Rates

### Querying Rates

**Get a specific rate:**
```python
# Get USD rate for 2024
rate = db.get_annual_rate_from_db('USD', 2024)
# Returns: 23.28 (CZK per 1 USD)
```

**Get all rates for a year:**
```python
rates = db.get_all_annual_rates_for_year(2024)
# Returns: [(currency, amount, rate, country), ...]
for currency, amount, rate, country in rates:
    print(f"{currency}: {amount} = {rate} CZK ({country})")
```

**Get available years:**
```python
years = db.get_available_annual_rate_years()
# Returns: [2023, 2024, 2025]
```

## Transaction Import Workflow

### Correct Order
1. **Create database** and select "Annual GFŘ Rates" mode
2. **Import annual rates** for required years
3. **Import CSV transactions**

### What Happens During CSV Import
For each transaction:
1. Extract transaction date (e.g., 2024-03-15)
2. Determine year (2024)
3. Get currency (e.g., USD)
4. Look up rate in database: `SELECT rate, amount FROM annual_rates WHERE currency='USD' AND year=2024`
5. If found: Calculate CZK amount
6. If **not found**: **Reject transaction** with error

### Error Example
```
ValueError: Annual exchange rate for CNY in year 2023 not found in database. 
Please import exchange rates for year 2023 before importing transactions.
```

**Solution:** Import annual rates for 2023 first.

## Menu Option Behavior

### When Enabled
The "Import Annual Exchange Rates..." menu option is enabled when:
- ✅ Database is open
- ✅ Database uses annual exchange rate mode

### When Disabled
The option is disabled when:
- ❌ No database is open
- ❌ Database uses daily CNB rates

Attempting to import rates into a daily-rates database shows:
```
Warning: This database uses daily CNB rates.

Annual exchange rates can only be imported into databases
configured for annual GFŘ rates.
```

## Sample Data

A sample rates file is provided: `sample_annual_rates_2024.txt`

This file contains 31 currencies with realistic 2024 rates:
- Major currencies: USD, EUR, GBP, JPY, CHF
- Regional: CNY, HKD, SGD, AUD, NZD
- European: DKK, SEK, NOK, PLN, HUF, RON, BGN
- Emerging markets: BRL, MXN, TRY, ZAR, INR, IDR, PHP
- Special: XDR (IMF Special Drawing Rights)

## Technical Details

### Database Method: `get_exchange_rate(currency, dt)`

**Daily mode:**
```python
# Fetches from CNB API
return self._rates.daily_rate(currency, dt)
```

**Annual mode:**
```python
# Queries database
year = dt.year
rate = self.get_annual_rate_from_db(currency, year)
if rate is None:
    raise ValueError(f"Annual exchange rate for {currency} in year {year} not found")
return rate
```

### Rate Calculation
The database stores rates with their amount multiplier:

**Storage:**
```
100 JPY = 15.35 CZK  (stored as: amount=100, rate=15.35)
```

**Retrieval:**
```python
rate, amount = (15.35, 100)
return rate / amount  # Returns 0.1535 (CZK per 1 JPY)
```

This allows correct handling of currencies quoted in multiples:
- Most currencies: amount = 1
- Japanese Yen (JPY), Philippine Peso (PHP): amount = 100
- Indonesian Rupiah (IDR): amount = 1000

## Error Handling

### Import Errors
The import process is tolerant:
- Empty lines are skipped
- Malformed lines are logged and skipped
- Parse errors don't stop the import

Each error is logged with:
- Line number
- Error type
- Original line content

### Transaction Import Errors
Transaction imports are strict:
- **Missing rate** → Transaction rejected
- **Wrong year** → Transaction rejected
- **Invalid currency** → Transaction rejected

This ensures database integrity.

## Best Practices

1. **Import rates first**: Always import annual rates before transactions
2. **One file per year**: Keep separate rate files for each year
3. **Backup**: Keep original rate files for audit purposes
4. **Verify**: Check import results for errors
5. **Update yearly**: Import new rates at year start

## Comparison with Daily Rates

| Feature | Daily CNB | Annual GFŘ |
|---------|-----------|------------|
| Rate source | CNB API | Database table |
| Rate precision | Daily specific | Yearly average |
| Import required | No | Yes |
| Validation | API error handling | Database lookup |
| Offline usage | Requires API | Fully offline |
| Audit trail | API logs | Database records |

## Legal Compliance

Both methods comply with Czech tax law (§ 38 Income Tax Act):
- **Daily CNB**: Uses actual rate for transaction date
- **Annual GFŘ**: Uses unified rate published by GFŘ

Taxpayers must **consistently use one method** throughout the tax year.

## Future Enhancements

Potential improvements:
- Auto-download rates from GFŘ website
- Bulk import for multiple years
- Rate comparison tool (database vs. CNB API)
- Export rates to CSV for verification
- Rate history visualization
- Missing rate detection before CSV import
