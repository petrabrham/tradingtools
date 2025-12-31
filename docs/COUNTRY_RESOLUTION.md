# Country of Origin Resolution

## The Problem

ISIN codes contain a country code in the first 2 characters, but this represents the **country of registration/listing**, not the **company's country of origin**.

### Example: BYD Company
- **ISIN**: US05606L1008 (starts with "US")
- **Actual Origin**: China (CN)
- **Why US?**: It's an American Depositary Receipt (ADR) listed in the United States

This causes issues when trying to apply correct withholding tax rates based on the company's actual country of origin.

## The Solution: Three-Tier Resolution

The `CountryResolver` class uses a three-tier approach to determine country of origin:

```
1. Manual Overrides (highest priority)
   ↓ (if not found)
2. ISIN Country Code (automatic)
   ↓ (if invalid/missing)
3. "XX" Unknown (fallback)
```

### 1. Manual Overrides (Most Reliable)

Create explicit mappings in `config/country_overrides.json`:

```json
{
  "overrides": {
    "US05606L1008": {
      "country_code": "CN",
      "name": "BYD Co Ltd",
      "note": "Chinese company traded as ADR in US"
    }
  }
}
```

### 2. ISIN Extraction (Automatic Fallback)

For securities without overrides, automatically extract country from ISIN:
- `US0231351067` → `US` (Amazon - US company, US registration)
- `GB0002374006` → `GB` (Diageo - UK company, UK registration)

### 3. Unknown (Last Resort)

If ISIN is invalid or empty, defaults to `XX` (unknown).

## Usage in Code

```python
from config.country_resolver import CountryResolver

# Initialize resolver
resolver = CountryResolver()

# Get country with source information
country_code, source = resolver.get_country("US05606L1008")
# Returns: ("CN", "override")

country_code, source = resolver.get_country("US0231351067")
# Returns: ("US", "isin")

# Check if override exists
if resolver.has_override("US05606L1008"):
    print("Manual override active")

# Add new override programmatically
resolver.add_override(
    isin="US9311421039",
    country_code="US",
    name="Walmart Inc",
    note="US company",
    save=True  # Saves to JSON immediately
)

# Remove override
resolver.remove_override("US9311421039", save=True)

# Get all overrides
all_overrides = resolver.get_all_overrides()
```

## Adding New Overrides

### Method 1: Edit JSON Directly

Edit `config/country_overrides.json`:

```json
{
  "overrides": {
    "US05606L1008": {
      "country_code": "CN",
      "name": "BYD Co Ltd",
      "note": "Chinese company traded as ADR in US"
    },
    "US01609W1027": {
      "country_code": "CN",
      "name": "Alibaba Group",
      "note": "Chinese company ADR"
    }
  }
}
```

### Method 2: Use Python Code

```python
resolver = CountryResolver()
resolver.add_override("US01609W1027", "CN", 
                     name="Alibaba Group", 
                     note="Chinese company ADR")
```

### Method 3: (Future) GUI Dialog

A future enhancement could add a menu option to manage overrides through the UI.

## Common Cases Requiring Overrides

### ADRs (American Depositary Receipts)
Chinese companies with US ISINs:
- Alibaba (US01609W1027) → CN
- BYD (US05606L1008) → CN
- Baidu (US0567521085) → CN
- NIO (US62914V1061) → CN

### Cross-Listings
Companies listed on multiple exchanges:
- Check which ISIN is used in your data
- Override if using secondary listing ISIN

### Holding Companies
SPACs, shell companies may need country override based on actual operations.

## Integration with Tax Rates

The country code from `CountryResolver` is used to look up withholding tax rates:

```python
# In update_dividends_view():
country_code, source = self.country_resolver.get_country(isin)

# Use country_code to get tax rate
tax_rate = self.tax_rates_loader.get_rate(country_code)

# Calculate taxes
gross = self.tax_rates_loader.calculate_gross_from_net(net, country_code)
tax = self.tax_rates_loader.calculate_tax_from_net(net, country_code)
```

## Benefits

✅ **Accurate**: Manual overrides ensure correct country assignment  
✅ **Flexible**: Easy to add new overrides via JSON  
✅ **Automatic**: Falls back to ISIN for standard cases  
✅ **Transparent**: Source tracking shows where country came from  
✅ **Maintainable**: Overrides stored separately from code  
✅ **Programmatic**: Can add/remove overrides via API

## Testing

Run the test script:

```bash
python test_country_resolver.py
```

Expected output shows:
- BYD correctly resolves to CN via override
- Other securities fall back to ISIN extraction
- Source tracking (override vs. isin vs. unknown)

## Future Enhancements

- [ ] GUI dialog to manage overrides
- [ ] Bulk import from CSV
- [ ] Auto-suggest overrides based on company name patterns
- [ ] Integration with financial data APIs
- [ ] Visual indicator in UI showing override vs. auto-detected
- [ ] Export override list for sharing/backup
- [ ] Validation warnings for suspicious country assignments
