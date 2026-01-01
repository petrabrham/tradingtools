# Exchange Rate Mode Configuration

## Overview
The exchange rate calculation method is now a **permanent database setting** that is configured once during database creation and cannot be changed afterward. This ensures data consistency throughout the database's lifetime.

## Rationale
Previously, the exchange rate mode could be changed at runtime via a menu option. This created a risk of data inconsistency:
- Some CSV imports might use daily CNB rates
- Other imports might use annual GFŘ rates
- No way to determine which method was used for existing data

By storing the exchange rate mode as a database setting, we ensure:
1. **Data Consistency**: All records use the same rate calculation method
2. **Auditability**: The mode is stored in the database and can be verified
3. **Compliance**: Aligns with Czech tax law requirement for consistent methodology

## Two Modes Available

### Daily CNB Rates
- **Source**: Czech National Bank (ČNB) daily exchange rates
- **Method**: Uses the exact exchange rate for each transaction date
- **Precision**: Most accurate for specific dates
- **API**: `cnb_rate.daily_rate(currency, date)`

### Annual GFŘ Rates (jednotný kurz)
- **Source**: General Financial Directorate (GFŘ) unified annual rates
- **Method**: Arithmetic mean of all daily CNB rates for the calendar year
- **Precision**: Single rate for entire year, simpler calculations
- **API**: `cnb_rate.annual_rate(currency, year)`

Both methods are **compliant with Czech tax law** (§ 38 Income Tax Act).

## Implementation Details

### Database Schema
A new `settings` table stores configuration:
```sql
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT
)
```

The exchange rate mode is stored as:
```sql
INSERT INTO settings VALUES (
    'exchange_rate_mode',
    'daily',  -- or 'annual'
    'Exchange rate calculation method: daily for CNB daily rates, annual for GFŘ annual rates'
)
```

### User Experience

#### Creating New Database
When creating a new database, user sees a dialog:
- **Title**: "Choose Exchange Rate Calculation Method"
- **Warning**: "This setting is permanent and cannot be changed after database creation."
- **Options**:
  - Daily CNB Rates (green button)
  - Annual GFŘ Rates (blue button)
- User must choose before proceeding with database creation

#### Opening Existing Database
- Exchange rate mode is automatically loaded from database settings
- Mode is displayed in Options menu as read-only: "Exchange rate mode: Daily CNB (immutable)"
- No option to change it

### Code Changes

#### DatabaseManager (`dbmanager.py`)
1. **New Methods**:
   - `create_settings_table()`: Creates settings table
   - `get_setting(key, default)`: Retrieves setting value
   - `set_setting(key, value, description)`: Stores setting value

2. **Modified Methods**:
   - `create_database()`: Creates settings table and stores exchange_rate_mode
   - `open_database()`: Loads exchange_rate_mode and sets `use_annual_rates` flag

#### Application UI (`app.py`)
1. **Removed**:
   - `use_annual_exchange_rates` BooleanVar (runtime toggle)
   - `on_exchange_rate_method_changed()` handler
   - Checkbutton for exchange rate mode in Options menu

2. **Added**:
   - Dialog in `create_database()` to prompt for exchange rate mode
   - `update_exchange_rate_display()`: Updates menu to show current mode
   - Read-only menu item showing exchange rate mode

3. **Modified**:
   - `create_database()`: Shows dialog and sets mode before database creation
   - `open_database()`: Calls `update_exchange_rate_display()` after loading database

## Testing Recommendations

### Test Case 1: New Database with Daily Rates
1. File → New Database
2. Choose "Daily CNB Rates"
3. Save database as `test_daily.db`
4. Verify Options menu shows "Exchange rate mode: Daily CNB (immutable)"
5. Import CSV with transactions
6. Verify amounts use daily rates

### Test Case 2: New Database with Annual Rates
1. File → New Database
2. Choose "Annual GFŘ Rates"
3. Save database as `test_annual.db`
4. Verify Options menu shows "Exchange rate mode: Annual GFŘ (immutable)"
5. Import CSV with transactions
6. Verify amounts use annual rates (same rate for all transactions in same year)

### Test Case 3: Opening Existing Database
1. Open database created in Test Case 1 or 2
2. Verify Options menu displays correct mode
3. Mode should be immutable (menu item disabled)

### Test Case 4: Legacy Database
1. Open database created before this feature
2. Should default to "Daily CNB" mode (backward compatibility)
3. Verify no errors occur

## Migration for Existing Databases
Existing databases without a `settings` table will:
1. Default to "daily" mode when opened
2. Settings table can be added retroactively if needed
3. Users should verify which mode matches their existing data

## Future Enhancements
- Database info dialog showing exchange rate mode and other metadata
- Migration tool to recalculate existing data if user wants to change mode (create new database)
- Export feature that documents exchange rate mode in report header
