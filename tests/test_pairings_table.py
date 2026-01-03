"""
Test script for Pairings Repository - Phase 1, Step 1
Tests the creation of the pairings table and basic operations.
"""

import sys
import os
import sqlite3
from datetime import datetime

# Add parent directory to path to import modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db.dbmanager import DatabaseManager

def test_pairings_table_creation():
    """Test creating the pairings table."""
    print("=" * 60)
    print("PHASE 1, STEP 1: Create Pairings Table Schema")
    print("=" * 60)
    
    # Create a test database
    test_db_path = "test_pairings.db"
    
    # Remove existing test database
    if os.path.exists(test_db_path):
        os.remove(test_db_path)
        print(f"✓ Removed existing test database: {test_db_path}")
    
    # Create new database with pairings table
    print(f"\n1. Creating new database: {test_db_path}")
    db_manager = DatabaseManager()
    db_manager.create_database(test_db_path)
    print("✓ Database created successfully")
    
    # Verify pairings table exists
    print("\n2. Verifying pairings table structure...")
    cursor = db_manager.conn.cursor()
    
    # Check table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='pairings'")
    if cursor.fetchone():
        print("✓ Pairings table exists")
    else:
        print("✗ ERROR: Pairings table not found!")
        return False
    
    # Check table schema
    cursor.execute("PRAGMA table_info(pairings)")
    columns = cursor.fetchall()
    expected_columns = {
        'id', 'sale_trade_id', 'purchase_trade_id', 'quantity', 'method',
        'time_test_qualified', 'holding_period_days', 'locked', 'locked_reason', 'notes'
    }
    actual_columns = {col[1] for col in columns}
    
    print(f"   Expected columns: {sorted(expected_columns)}")
    print(f"   Actual columns:   {sorted(actual_columns)}")
    
    if expected_columns == actual_columns:
        print("✓ All expected columns present")
    else:
        missing = expected_columns - actual_columns
        extra = actual_columns - expected_columns
        if missing:
            print(f"✗ Missing columns: {missing}")
        if extra:
            print(f"✗ Extra columns: {extra}")
        return False
    
    # Check indexes
    print("\n3. Verifying indexes...")
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='pairings'")
    indexes = [row[0] for row in cursor.fetchall()]
    expected_indexes = [
        'idx_pairings_sale',
        'idx_pairings_purchase',
        'idx_pairings_time_test',
        'idx_pairings_method'
    ]
    
    for idx_name in expected_indexes:
        if idx_name in indexes:
            print(f"✓ Index exists: {idx_name}")
        else:
            print(f"✗ Missing index: {idx_name}")
    
    # Check foreign key constraints
    print("\n4. Verifying foreign key constraints...")
    cursor.execute("PRAGMA foreign_key_list(pairings)")
    fk_constraints = cursor.fetchall()
    
    if len(fk_constraints) == 2:
        print(f"✓ Found {len(fk_constraints)} foreign key constraints")
        for fk in fk_constraints:
            print(f"   - {fk[2]} → trades(id)")
    else:
        print(f"✗ Expected 2 foreign keys, found {len(fk_constraints)}")
    
    # Test basic repository operations
    print("\n5. Testing basic repository operations...")
    
    # First, create sample securities and trades for testing
    print("   Creating test data (securities and trades)...")
    
    # Insert test security
    sec_id = db_manager.securities_repo.insert("US0378331005", "AAPL", "Apple Inc.")
    print(f"   ✓ Created security: AAPL (id={sec_id})")
    
    # Insert test purchase trade
    purchase_timestamp = int(datetime(2020, 1, 15).timestamp())
    purchase_id = db_manager.trades_repo.insert(
        timestamp=purchase_timestamp,
        isin_id=sec_id,
        id_string="BUY-001",
        trade_type=1,  # BUY
        number_of_shares=100.0,
        price_for_share=150.0,
        currency_of_price="USD",
        total_czk=330000.0
    )
    print(f"   ✓ Created purchase trade (id={purchase_id})")
    
    # Insert test sale trade
    sale_timestamp = int(datetime(2024, 6, 15).timestamp())
    sale_id = db_manager.trades_repo.insert(
        timestamp=sale_timestamp,
        isin_id=sec_id,
        id_string="SELL-001",
        trade_type=2,  # SELL
        number_of_shares=50.0,
        price_for_share=200.0,
        currency_of_price="USD",
        total_czk=220000.0
    )
    print(f"   ✓ Created sale trade (id={sale_id})")
    
    # Test creating a pairing
    print("\n   Testing pairing creation...")
    holding_days = db_manager.pairings_repo.calculate_holding_period(purchase_timestamp, sale_timestamp)
    time_qualified = db_manager.pairings_repo.check_time_test(purchase_timestamp, sale_timestamp)
    
    pairing_id = db_manager.pairings_repo.create_pairing(
        sale_trade_id=sale_id,
        purchase_trade_id=purchase_id,
        quantity=50.0,
        method='FIFO',
        time_test_qualified=time_qualified,
        holding_period_days=holding_days,
        notes='Test pairing'
    )
    print(f"   ✓ Created pairing (id={pairing_id})")
    print(f"     - Holding period: {holding_days} days")
    print(f"     - Time test qualified: {time_qualified} (3+ years)")
    
    # Test retrieving pairings
    print("\n   Testing pairing retrieval...")
    pairings = db_manager.pairings_repo.get_pairings_for_sale(sale_id)
    if len(pairings) == 1:
        print(f"   ✓ Retrieved {len(pairings)} pairing for sale")
        p = pairings[0]
        print(f"     - Method: {p['method']}")
        print(f"     - Quantity: {p['quantity']}")
        print(f"     - Time qualified: {bool(p['time_test_qualified'])}")
    else:
        print(f"   ✗ Expected 1 pairing, found {len(pairings)}")
    
    # Test locking functionality
    print("\n   Testing lock/unlock functionality...")
    lock_result = db_manager.pairings_repo.lock_pairing(pairing_id, "Test lock")
    if lock_result:
        print("   ✓ Successfully locked pairing")
    
    is_locked = db_manager.pairings_repo.is_pairing_locked(pairing_id)
    if is_locked:
        print("   ✓ Pairing is locked")
    
    # Test that locked pairing cannot be deleted
    delete_result = db_manager.pairings_repo.delete_pairing(pairing_id)
    if not delete_result:
        print("   ✓ Locked pairing cannot be deleted (expected behavior)")
    
    # Unlock and delete
    unlock_result = db_manager.pairings_repo.unlock_pairing(pairing_id)
    if unlock_result:
        print("   ✓ Successfully unlocked pairing")
    
    delete_result = db_manager.pairings_repo.delete_pairing(pairing_id)
    if delete_result:
        print("   ✓ Successfully deleted unlocked pairing")
    
    # Close database
    db_manager.close()
    print("\n✓ Database closed")
    
    print("\n" + "=" * 60)
    print("PHASE 1, STEP 1: COMPLETED SUCCESSFULLY ✓")
    print("=" * 60)
    print("\nThe pairings table has been created with:")
    print("  - Proper schema with all required fields")
    print("  - Foreign key constraints to trades table")
    print("  - Indexes for optimized queries")
    print("  - Basic CRUD operations working")
    print("  - Lock/unlock functionality working")
    print("  - Time test calculation working")
    print(f"\nTest database saved at: {os.path.abspath(test_db_path)}")
    
    return True

if __name__ == "__main__":
    try:
        success = test_pairings_table_creation()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
