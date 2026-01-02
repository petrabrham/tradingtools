"""Test script for tax rates loader"""
from config.tax_rates_loader import TaxRatesLoader

# Initialize loader
loader = TaxRatesLoader()

print(f"Loaded {len(loader.rates_by_country)} country rates")
print("\nSample rates:")
for code in ['US', 'GB', 'DE', 'FR', 'CZ', 'JP', 'CN']:
    rate = loader.get_rate(code)
    if rate is not None:
        print(f"  {code}: {rate*100:.2f}%")
    else:
        print(f"  {code}: Not found")

print("\nExample calculation for US (15% withholding):")
net = 1000.0
gross = loader.calculate_gross_from_net(net, 'US')
tax = loader.calculate_tax_from_net(net, 'US')
print(f"  Net dividend: {net:.2f} CZK")
print(f"  Gross dividend: {gross:.2f} CZK")
print(f"  Withholding tax: {tax:.2f} CZK")
print(f"  Verification: {gross:.2f} - {tax:.2f} = {gross - tax:.2f} (should equal {net:.2f})")
