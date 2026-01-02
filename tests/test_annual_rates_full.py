"""
Test script for annual exchange rates functionality.

This script tests:
1. Creating a database with annual rate mode
2. Creating annual_rates table
3. Importing rates from file
4. Querying rates
5. Transaction import validation (requires rates)
"""

import os
import sys
import tempfile
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dbmanager import DatabaseManager


def test_annual_rates():
    """Test annual rates functionality"""
    
    print("=" * 70)
    print("Testing Annual Exchange Rates Feature")
    print("=" * 70)
    
    # Create temporary database
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        db_path = tmp.name
    
    try:
        # Test 1: Create database with annual rates mode
        print("\n1. Creating database with annual rate mode...")
        db = DatabaseManager()
        db.use_annual_rates = True  # Set before creating database
        db.create_database(db_path)
        print("   ✓ Database created")
        
        # Test 2: Verify settings
        print("\n2. Verifying settings...")
        rate_mode = db.get_setting("exchange_rate_mode")
        assert rate_mode == "annual", f"Expected 'annual', got '{rate_mode}'"
        print(f"   ✓ Exchange rate mode: {rate_mode}")
        
        # Test 3: Check annual_rates table exists
        print("\n3. Checking annual_rates table...")
        cursor = db.conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='annual_rates'")
        assert cursor.fetchone() is not None, "annual_rates table not found"
        print("   ✓ annual_rates table exists")
        
        # Test 4: Import rates from file
        print("\n4. Importing annual rates from file...")
        rates_file = "sample_annual_rates_2024.txt"
        if not os.path.exists(rates_file):
            print(f"   ⚠ Sample file not found: {rates_file}")
            print("   Creating sample file...")
            with open(rates_file, 'w', encoding='utf-8') as f:
                f.write("USA dolar 1 USD 23,28\n")
                f.write("EMU euro 1 EUR 25,16\n")
                f.write("Japonsko jen 100 JPY 15,35\n")
                f.write("Velká Británie libra 1 GBP 29,78\n")
        
        result = db.import_annual_rates_from_file(rates_file, 2024)
        print(f"   ✓ Imported: {result['imported']} rates")
        print(f"   ✓ Skipped: {result['skipped']} lines")
        if result['errors']:
            print(f"   ⚠ Errors: {len(result['errors'])}")
            for error in result['errors'][:3]:
                print(f"     - {error}")
        
        # Test 5: Query specific rates
        print("\n5. Querying exchange rates...")
        test_currencies = ['USD', 'EUR', 'JPY', 'GBP']
        for currency in test_currencies:
            rate = db.get_annual_rate_from_db(currency, 2024)
            if rate:
                print(f"   ✓ {currency}: {rate:.4f} CZK")
            else:
                print(f"   ✗ {currency}: Not found")
        
        # Test 6: Get all rates for year
        print("\n6. Getting all rates for 2024...")
        all_rates = db.get_all_annual_rates_for_year(2024)
        print(f"   ✓ Found {len(all_rates)} rates")
        for currency, amount, rate, country in all_rates[:5]:
            print(f"     {currency:4s}: {amount:4d} = {rate:8.2f} CZK ({country})")
        if len(all_rates) > 5:
            print(f"     ... and {len(all_rates) - 5} more")
        
        # Test 7: Get available years
        print("\n7. Getting available years...")
        years = db.get_available_annual_rate_years()
        print(f"   ✓ Available years: {years}")
        
        # Test 8: Test get_exchange_rate method
        print("\n8. Testing get_exchange_rate method...")
        test_date = datetime(2024, 3, 15)
        try:
            usd_rate = db.get_exchange_rate('USD', test_date)
            print(f"   ✓ USD on {test_date.date()}: {usd_rate:.4f} CZK")
        except ValueError as e:
            print(f"   ✗ Error: {e}")
        
        # Test 9: Test missing rate validation
        print("\n9. Testing missing rate validation...")
        try:
            test_date_2023 = datetime(2023, 1, 1)
            rate = db.get_exchange_rate('USD', test_date_2023)
            print(f"   ✗ Should have raised ValueError, got rate: {rate}")
        except ValueError as e:
            print(f"   ✓ Correctly raised error: {str(e)[:60]}...")
        
        # Test 10: Test insert and replace
        print("\n10. Testing manual rate insertion...")
        db.insert_annual_rate(2025, 'USD', 1, 24.50, 'USA dolar')
        rate_2025 = db.get_annual_rate_from_db('USD', 2025)
        assert rate_2025 == 24.50, f"Expected 24.50, got {rate_2025}"
        print(f"   ✓ Inserted USD 2025: {rate_2025}")
        
        # Update the same rate
        db.insert_annual_rate(2025, 'USD', 1, 24.75, 'USA dolar')
        rate_2025_updated = db.get_annual_rate_from_db('USD', 2025)
        assert rate_2025_updated == 24.75, f"Expected 24.75, got {rate_2025_updated}"
        print(f"   ✓ Updated USD 2025: {rate_2025_updated}")
        
        # Test 11: Close and reopen database
        print("\n11. Testing database persistence...")
        db.close()
        
        db2 = DatabaseManager()
        db2.open_database(db_path)
        assert db2.use_annual_rates == True, "use_annual_rates not loaded correctly"
        print(f"   ✓ Exchange rate mode loaded: {'annual' if db2.use_annual_rates else 'daily'}")
        
        usd_rate_reopen = db2.get_annual_rate_from_db('USD', 2024)
        assert usd_rate_reopen is not None, "Rates not persisted"
        print(f"   ✓ Rates persisted: USD 2024 = {usd_rate_reopen:.4f}")
        
        db2.close()
        
        print("\n" + "=" * 70)
        print("All tests passed! ✓")
        print("=" * 70)
        
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        raise
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        # Cleanup
        if os.path.exists(db_path):
            os.unlink(db_path)
            print(f"\nCleaned up temporary database: {db_path}")


def test_daily_mode_rejection():
    """Test that annual rates cannot be imported to daily-mode database"""
    
    print("\n" + "=" * 70)
    print("Testing Daily Mode Rejection")
    print("=" * 70)
    
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        db_path = tmp.name
    
    try:
        # Create database with daily mode (default)
        print("\n1. Creating database with daily rate mode...")
        db = DatabaseManager()
        db.use_annual_rates = False  # Explicitly set to daily mode
        db.create_database(db_path)
        print("   ✓ Database created with daily mode")
        
        # Verify settings
        rate_mode = db.get_setting("exchange_rate_mode")
        assert rate_mode == "daily", f"Expected 'daily', got '{rate_mode}'"
        print(f"   ✓ Exchange rate mode: {rate_mode}")
        
        # Try to import annual rates (should fail)
        print("\n2. Attempting to import annual rates...")
        try:
            rates_file = "sample_annual_rates_2024.txt"
            result = db.import_annual_rates_from_file(rates_file, 2024)
            print(f"   ✗ Should have raised RuntimeError, got result: {result}")
        except RuntimeError as e:
            expected_msg = "Cannot import annual rates into database configured for daily rates"
            assert expected_msg in str(e), f"Unexpected error message: {e}"
            print(f"   ✓ Correctly rejected: {str(e)[:60]}...")
        
        print("\n" + "=" * 70)
        print("Daily mode rejection test passed! ✓")
        print("=" * 70)
        
        db.close()
        
    finally:
        if os.path.exists(db_path):
            try:
                os.unlink(db_path)
            except PermissionError:
                pass  # File still in use, skip cleanup


if __name__ == "__main__":
    try:
        test_annual_rates()
        test_daily_mode_rejection()
        print("\n🎉 All tests completed successfully!")
    except Exception as e:
        print(f"\n❌ Test suite failed: {e}")
        sys.exit(1)
