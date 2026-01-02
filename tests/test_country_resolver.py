"""Test script for country resolver"""
from config.country_resolver import CountryResolver

# Initialize resolver
resolver = CountryResolver()

print("Country Resolver Test\n" + "="*50)

# Test cases
test_isins = [
    ("US05606L1008", "BYD (should be CN via override)"),
    ("US0231351067", "Amazon (should be US from ISIN)"),
    ("GB0002374006", "Diageo (should be GB from ISIN)"),
    ("DE0005140008", "Deutsche Bank (should be DE from ISIN)"),
    ("INVALID", "Invalid ISIN"),
    ("", "Empty ISIN"),
]

print("\n1. Country Detection Tests:")
print("-" * 50)
for isin, description in test_isins:
    country, source = resolver.get_country(isin)
    has_override = resolver.has_override(isin)
    print(f"  {isin:15s} → {country} ({source:8s}) {description}")
    if has_override:
        print(f"                    ✓ Manual override active")

print("\n2. All Loaded Overrides:")
print("-" * 50)
overrides = resolver.get_all_overrides()
if overrides:
    for isin, country in overrides.items():
        print(f"  {isin} → {country}")
else:
    print("  No overrides loaded")

print("\n3. Adding New Override (test):")
print("-" * 50)
test_isin = "US0378331005"  # Apple
print(f"  Before: {resolver.get_country(test_isin)}")
resolver.add_override(test_isin, "US", name="Apple Inc", note="Test override", save=False)
print(f"  After:  {resolver.get_country(test_isin)}")
print("  (not saved to file - save=False)")

print("\n4. Example: Add BYD Override to File:")
print("-" * 50)
print("  To add a new override permanently:")
print("  resolver.add_override('US05606L1008', 'CN', name='BYD Co Ltd', note='Chinese company ADR')")
print("\n  Or edit config/country_overrides.json directly:")
print('  "US05606L1008": {')
print('    "country_code": "CN",')
print('    "name": "BYD Co Ltd",')
print('    "note": "Chinese company traded as ADR in US"')
print('  }')

print("\n" + "="*50)
