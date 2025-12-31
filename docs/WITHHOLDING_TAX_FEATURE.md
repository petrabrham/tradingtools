# Withholding Tax Calculation Feature

## Overview

The TradingTools application now supports two methods for calculating dividend withholding taxes:

1. **JSON Config Method (Default)** - Calculates taxes from treaty rates
2. **CSV Method** - Uses taxes as imported from the original CSV file

## Why Two Methods?

The original CSV files from brokers often contain rounding errors in the withholding tax and gross dividend amounts. The only precise value is the **net dividend** (the amount actually received).

### The Problem

When a broker calculates dividends, they may round intermediate values, leading to small discrepancies:
- Net dividend (precise): 1000.00 CZK
- Gross dividend (rounded): 1176.00 CZK (instead of 1176.47)
- Withholding tax (rounded): 176.00 CZK (instead of 176.47)

### The Solution

The JSON config method uses official withholding tax rates from Czech Double Taxation Treaties (DTT) to recalculate accurate values from the precise net amount:

```
gross = net / (1 - rate)
tax = net * rate / (1 - rate)
```

For example, with US dividends (15% withholding):
- Net: 1000.00 CZK (precise from CSV)
- Gross: 1176.47 CZK (calculated: 1000 / 0.85)
- Tax: 176.47 CZK (calculated: 1000 * 0.15 / 0.85)

## How to Use

1. **Select Calculation Method**
   - Go to **Options** menu
   - Check/uncheck **"Calculate taxes from JSON config"**
   - Default: **Checked** (uses JSON rates)

2. **View Updates**
   - Dividend view automatically refreshes when you change the method
   - All values (detail rows, summaries, country totals) update instantly

## Tax Rates Configuration

Tax rates are stored in `config/withholding_tax_rates.json`:

- 36+ countries with ISO 3166-1 alpha-2 codes
- Rates based on Czech DTT agreements
- Includes validity periods and notes
- Verified effective dates for major countries (US: 1993-01-01, GB: 1992-01-01)

### Adding/Updating Rates

Edit `config/withholding_tax_rates.json`:

```json
{
  "country_code": "US",
  "country_name": "United States",
  "rate": 15.000,
  "valid_from": "1993-01-01",
  "valid_to": null
}
```

The application automatically loads rates on startup.

## Technical Details

### Country Detection

Country codes are extracted from ISIN codes (first 2 characters):
- US1234567890 → US (United States)
- GB0987654321 → GB (United Kingdom)
- DE1122334455 → DE (Germany)

### Calculation Logic

**JSON Mode:**
```python
# Start with net (precise value from CSV)
net_czk = 1000.00

# Get rate for country (e.g., US = 0.15)
rate = tax_rates_loader.get_rate(country_code)

# Calculate gross and tax
gross_czk = net_czk / (1.0 - rate)  # 1176.47
tax_czk = net_czk * rate / (1.0 - rate)  # 176.47
```

**CSV Mode:**
```python
# Use values as imported (may have rounding errors)
gross_czk = record[6]  # From database
tax_czk = record[8]    # From database
net_czk = record[7]    # From database
```

### Affected Views

All dividend displays use the selected calculation method:
- Detail rows (individual dividend payments)
- Parent rows (grouped by security)
- Country summary table
- Total summary panel

## Testing

Run the test script to verify calculations:

```bash
python test_tax_loader.py
```

Expected output:
```
Loaded 36 country rates

Sample rates:
  US: 15.00%
  GB: 0.00%
  DE: 26.38%
  ...

Example calculation for US (15% withholding):
  Net dividend: 1000.00 CZK
  Gross dividend: 1176.47 CZK
  Withholding tax: 176.47 CZK
  Verification: 1176.47 - 176.47 = 1000.00 (should equal 1000.00)
```

## Benefits

✅ **Accuracy**: Eliminates rounding errors from broker CSV files  
✅ **Transparency**: Users can choose between calculated vs. imported values  
✅ **Flexibility**: Easy to update tax rates without database changes  
✅ **Auditability**: Can compare both methods to identify discrepancies  
✅ **Compliance**: Uses official DTT rates for tax reporting

## Future Enhancements

- [ ] Add date-based rate selection (use historical rates for old dividends)
- [ ] Visual indicator showing which calculation method is active
- [ ] Export both CSV and JSON calculations for comparison
- [ ] Warning when JSON rate not found (fallback to CSV)
- [ ] Support for ownership-percentage-based rates (some DTTs have tiered rates)
