"""Test script for annual exchange rates feature"""
from cnb_rate import cnb_rate
import datetime

print("Annual Exchange Rates Test")
print("=" * 60)

# Initialize rate fetcher
rates = cnb_rate()

print("\n1. Comparison: Daily vs Annual Rates")
print("-" * 60)

test_date = datetime.date(2024, 6, 15)
test_year = 2024
test_currencies = ['EUR', 'USD', 'GBP']

print(f"Date for daily rate: {test_date.strftime('%Y-%m-%d')}")
print(f"Year for annual rate: {test_year}\n")

for currency in test_currencies:
    try:
        daily = rates.daily_rate(currency, test_date)
        print(f"{currency} daily rate ({test_date}): {daily:.4f} CZK")
    except Exception as e:
        print(f"{currency} daily rate: Error - {e}")

print()

for currency in test_currencies:
    try:
        annual = rates.annual_rate(currency, test_year)
        print(f"{currency} annual rate ({test_year}): {annual:.4f} CZK")
    except Exception as e:
        print(f"{currency} annual rate: Error - {e}")

print("\n2. Tax Calculation Example")
print("-" * 60)

# Example: Dividend income in USD
dividend_usd = 1000.00
test_date = datetime.date(2024, 7, 15)
test_year = 2024

print(f"Dividend income: ${dividend_usd:.2f} USD")
print(f"Transaction date: {test_date}")
print()

try:
    # Method 1: Daily CNB rate
    daily_rate_usd = rates.daily_rate('USD', test_date)
    dividend_czk_daily = dividend_usd * daily_rate_usd
    print(f"Method 1 - Daily CNB rate:")
    print(f"  Rate: {daily_rate_usd:.4f} CZK/USD")
    print(f"  Dividend in CZK: {dividend_czk_daily:.2f} CZK")
    print()
    
    # Method 2: Annual GFŘ rate
    annual_rate_usd = rates.annual_rate('USD', test_year)
    dividend_czk_annual = dividend_usd * annual_rate_usd
    print(f"Method 2 - Annual GFŘ rate (jednotný kurz):")
    print(f"  Rate: {annual_rate_usd:.4f} CZK/USD")
    print(f"  Dividend in CZK: {dividend_czk_annual:.2f} CZK")
    print()
    
    # Difference
    difference = dividend_czk_daily - dividend_czk_annual
    print(f"Difference: {difference:.2f} CZK ({abs(difference/dividend_czk_annual*100):.2f}%)")
    
except Exception as e:
    print(f"Error: {e}")

print("\n3. Legal Background")
print("-" * 60)
print("According to Czech tax law, taxpayers can choose:")
print("  1. Daily CNB rates - Precise daily exchange rates")
print("  2. Annual GFŘ rates - Unified yearly rate (jednotný kurz)")
print()
print("The annual rate is published by:")
print("  General Financial Directorate (Generální finanční ředitelství)")
print("  https://www.financnisprava.cz")
print()
print("Note: This implementation calculates annual rates as the")
print("arithmetic mean of CNB daily rates for the calendar year.")

print("\n" + "=" * 60)
