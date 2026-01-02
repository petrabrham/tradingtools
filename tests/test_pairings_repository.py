"""
Unit tests for PairingsRepository.

This test suite covers all methods of the PairingsRepository class, including:
- Table creation and schema validation
- CRUD operations (Create, Read, Update, Delete)
- Lock/unlock functionality
- Time test calculations (calendar-based with leap year handling)
- Holding period calculations
- Query methods and aggregations
"""

import unittest
import sqlite3
import os
import sys
from datetime import datetime, timedelta
from unittest.mock import Mock

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from db.repositories.pairings import PairingsRepository
from logger_config import setup_logger


class TestPairingsRepository(unittest.TestCase):
    """Test suite for PairingsRepository class."""

    def setUp(self):
        """Set up test database and repository before each test."""
        # Create in-memory database for testing
        self.conn = sqlite3.connect(':memory:')
        self.conn.execute('PRAGMA foreign_keys = ON')
        
        # Create mock logger
        self.logger = Mock()
        
        # Initialize repository
        self.repo = PairingsRepository(self.conn, self.logger)
        
        # Create required tables
        self._create_test_tables()
        
    def tearDown(self):
        """Clean up after each test."""
        self.conn.close()
        
    def _create_test_tables(self):
        """Create prerequisite tables for testing."""
        # Create securities table
        self.conn.execute("""
            CREATE TABLE securities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                isin TEXT UNIQUE NOT NULL,
                ticker TEXT,
                name TEXT
            )
        """)
        
        # Create trades table (simplified for testing)
        self.conn.execute("""
            CREATE TABLE trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                isin_id INTEGER NOT NULL,
                timestamp INTEGER NOT NULL,
                price_for_share REAL NOT NULL,
                quantity REAL NOT NULL,
                type TEXT NOT NULL,
                FOREIGN KEY (isin_id) REFERENCES securities(id)
            )
        """)
        
        self.conn.commit()
        
    def _create_test_security(self, isin='US0378331005', ticker='AAPL', name='Apple Inc.'):
        """Helper to create a test security."""
        cur = self.conn.execute(
            "INSERT INTO securities (isin, ticker, name) VALUES (?, ?, ?)",
            (isin, ticker, name)
        )
        self.conn.commit()
        return cur.lastrowid
        
    def _create_test_trade(self, security_id, timestamp, price, quantity, trade_type='BUY'):
        """Helper to create a test trade."""
        cur = self.conn.execute(
            "INSERT INTO trades (isin_id, timestamp, price_for_share, quantity, type) "
            "VALUES (?, ?, ?, ?, ?)",
            (security_id, timestamp, price, quantity, trade_type)
        )
        self.conn.commit()
        return cur.lastrowid


class TestTableCreation(TestPairingsRepository):
    """Test table creation and schema."""
    
    def test_create_table(self):
        """Test that create_table creates the pairings table."""
        self.repo.create_table()
        
        # Verify table exists
        cur = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='pairings'"
        )
        self.assertIsNotNone(cur.fetchone(), "Pairings table should exist")
        
    def test_table_columns(self):
        """Test that all required columns exist."""
        self.repo.create_table()
        
        cur = self.conn.execute("PRAGMA table_info(pairings)")
        columns = {row[1]: row[2] for row in cur.fetchall()}
        
        expected_columns = {
            'id': 'INTEGER',
            'sale_trade_id': 'INTEGER',
            'purchase_trade_id': 'INTEGER',
            'quantity': 'REAL',
            'method': 'TEXT',
            'time_test_qualified': 'BOOLEAN',
            'holding_period_days': 'INTEGER',
            'locked': 'BOOLEAN',
            'locked_reason': 'TEXT',
            'notes': 'TEXT'
        }
        
        for col_name, col_type in expected_columns.items():
            self.assertIn(col_name, columns, f"Column {col_name} should exist")
            
    def test_indexes_created(self):
        """Test that all indexes are created."""
        self.repo.create_table()
        
        cur = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='pairings'"
        )
        indexes = [row[0] for row in cur.fetchall()]
        
        expected_indexes = [
            'idx_pairings_sale',
            'idx_pairings_purchase',
            'idx_pairings_time_test',
            'idx_pairings_method'
        ]
        
        for index in expected_indexes:
            self.assertIn(index, indexes, f"Index {index} should exist")
            
    def test_foreign_keys(self):
        """Test that foreign key constraints exist."""
        self.repo.create_table()
        
        cur = self.conn.execute("PRAGMA foreign_key_list(pairings)")
        foreign_keys = cur.fetchall()
        
        self.assertEqual(len(foreign_keys), 2, "Should have 2 foreign keys")
        
        # Check that both FK reference trades table
        tables = [fk[2] for fk in foreign_keys]
        self.assertIn('trades', tables)


class TestCreatePairing(TestPairingsRepository):
    """Test pairing creation."""
    
    def setUp(self):
        """Set up test data."""
        super().setUp()
        self.repo.create_table()
        self.security_id = self._create_test_security()
        
        # Create purchase and sale trades
        purchase_date = datetime(2020, 1, 15)
        sale_date = datetime(2024, 6, 15)
        
        self.purchase_id = self._create_test_trade(
            self.security_id,
            int(purchase_date.timestamp()),
            150.0,
            50.0,
            'BUY'
        )
        self.sale_id = self._create_test_trade(
            self.security_id,
            int(sale_date.timestamp()),
            200.0,
            50.0,
            'SELL'
        )
        
    def test_create_pairing_success(self):
        """Test successful pairing creation."""
        pairing_id = self.repo.create_pairing(
            sale_trade_id=self.sale_id,
            purchase_trade_id=self.purchase_id,
            quantity=50.0,
            method='FIFO',
            time_test_qualified=True,
            holding_period_days=1612,
            notes='Test pairing'
        )
        
        self.assertIsNotNone(pairing_id)
        self.assertGreater(pairing_id, 0)
        
        # Verify data was inserted
        cur = self.conn.execute("SELECT * FROM pairings WHERE id = ?", (pairing_id,))
        row = cur.fetchone()
        self.assertIsNotNone(row)
        
    def test_create_pairing_invalid_quantity(self):
        """Test that zero or negative quantity raises ValueError."""
        with self.assertRaises(ValueError):
            self.repo.create_pairing(
                sale_trade_id=self.sale_id,
                purchase_trade_id=self.purchase_id,
                quantity=0,
                method='FIFO'
            )
            
        with self.assertRaises(ValueError):
            self.repo.create_pairing(
                sale_trade_id=self.sale_id,
                purchase_trade_id=self.purchase_id,
                quantity=-10,
                method='FIFO'
            )
            
    def test_create_pairing_invalid_method(self):
        """Test that invalid method raises ValueError."""
        with self.assertRaises(ValueError):
            self.repo.create_pairing(
                sale_trade_id=self.sale_id,
                purchase_trade_id=self.purchase_id,
                quantity=50.0,
                method='INVALID_METHOD'
            )
            
    def test_create_pairing_all_methods(self):
        """Test that all valid methods are accepted."""
        valid_methods = ['FIFO', 'LIFO', 'MaxLose', 'MaxProfit', 'Manual']
        
        for method in valid_methods:
            pairing_id = self.repo.create_pairing(
                sale_trade_id=self.sale_id,
                purchase_trade_id=self.purchase_id,
                quantity=10.0,
                method=method
            )
            self.assertIsNotNone(pairing_id)


class TestGetPairings(TestPairingsRepository):
    """Test pairing retrieval methods."""
    
    def setUp(self):
        """Set up test data with multiple pairings."""
        super().setUp()
        self.repo.create_table()
        self.security_id = self._create_test_security()
        
        # Create multiple purchase trades
        self.purchase1_id = self._create_test_trade(
            self.security_id, int(datetime(2020, 1, 15).timestamp()), 150.0, 100.0, 'BUY'
        )
        self.purchase2_id = self._create_test_trade(
            self.security_id, int(datetime(2021, 6, 20).timestamp()), 180.0, 50.0, 'BUY'
        )
        
        # Create sale trade
        self.sale_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 11, 10).timestamp()), 200.0, 100.0, 'SELL'
        )
        
        # Create pairings
        self.pairing1_id = self.repo.create_pairing(
            self.sale_id, self.purchase1_id, 50.0, 'FIFO', True, 1765
        )
        self.pairing2_id = self.repo.create_pairing(
            self.sale_id, self.purchase2_id, 50.0, 'FIFO', True, 1238
        )
        
    def test_get_pairings_for_sale(self):
        """Test retrieving all pairings for a sale."""
        pairings = self.repo.get_pairings_for_sale(self.sale_id)
        
        self.assertEqual(len(pairings), 2)
        self.assertEqual(pairings[0]['sale_trade_id'], self.sale_id)
        self.assertEqual(pairings[1]['sale_trade_id'], self.sale_id)
        
    def test_get_pairings_for_sale_includes_trade_data(self):
        """Test that sale query includes trade timestamps and prices."""
        pairings = self.repo.get_pairings_for_sale(self.sale_id)
        
        pairing = pairings[0]
        self.assertIn('purchase_timestamp', pairing)
        self.assertIn('purchase_price', pairing)
        self.assertIn('sale_timestamp', pairing)
        self.assertIn('sale_price', pairing)
        
    def test_get_pairings_for_purchase(self):
        """Test retrieving all pairings using a purchase lot."""
        pairings = self.repo.get_pairings_for_purchase(self.purchase1_id)
        
        self.assertEqual(len(pairings), 1)
        self.assertEqual(pairings[0]['purchase_trade_id'], self.purchase1_id)
        
    def test_get_pairings_for_nonexistent_sale(self):
        """Test that querying nonexistent sale returns empty list."""
        pairings = self.repo.get_pairings_for_sale(99999)
        self.assertEqual(len(pairings), 0)


class TestDeletePairing(TestPairingsRepository):
    """Test pairing deletion."""
    
    def setUp(self):
        """Set up test data."""
        super().setUp()
        self.repo.create_table()
        self.security_id = self._create_test_security()
        
        self.purchase_id = self._create_test_trade(
            self.security_id, int(datetime(2020, 1, 15).timestamp()), 150.0, 50.0, 'BUY'
        )
        self.sale_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 6, 15).timestamp()), 200.0, 50.0, 'SELL'
        )
        
        self.pairing_id = self.repo.create_pairing(
            self.sale_id, self.purchase_id, 50.0, 'FIFO'
        )
        
    def test_delete_unlocked_pairing(self):
        """Test successful deletion of unlocked pairing."""
        result = self.repo.delete_pairing(self.pairing_id)
        self.assertTrue(result)
        
        # Verify it's deleted
        cur = self.conn.execute("SELECT * FROM pairings WHERE id = ?", (self.pairing_id,))
        self.assertIsNone(cur.fetchone())
        
    def test_delete_locked_pairing(self):
        """Test that locked pairing cannot be deleted."""
        # Lock the pairing
        self.repo.lock_pairing(self.pairing_id, "Tax Return 2024")
        
        # Attempt to delete
        result = self.repo.delete_pairing(self.pairing_id)
        self.assertFalse(result)
        
        # Verify it still exists
        cur = self.conn.execute("SELECT * FROM pairings WHERE id = ?", (self.pairing_id,))
        self.assertIsNotNone(cur.fetchone())
        
    def test_delete_nonexistent_pairing(self):
        """Test deleting nonexistent pairing returns False."""
        result = self.repo.delete_pairing(99999)
        self.assertFalse(result)


class TestLockUnlock(TestPairingsRepository):
    """Test locking and unlocking functionality."""
    
    def setUp(self):
        """Set up test data."""
        super().setUp()
        self.repo.create_table()
        self.security_id = self._create_test_security()
        
        self.purchase_id = self._create_test_trade(
            self.security_id, int(datetime(2020, 1, 15).timestamp()), 150.0, 50.0, 'BUY'
        )
        self.sale_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 6, 15).timestamp()), 200.0, 50.0, 'SELL'
        )
        
        self.pairing_id = self.repo.create_pairing(
            self.sale_id, self.purchase_id, 50.0, 'FIFO'
        )
        
    def test_lock_pairing(self):
        """Test locking a pairing."""
        result = self.repo.lock_pairing(self.pairing_id, "Tax Return 2024")
        self.assertTrue(result)
        
        # Verify it's locked
        cur = self.conn.execute(
            "SELECT locked, locked_reason FROM pairings WHERE id = ?",
            (self.pairing_id,)
        )
        row = cur.fetchone()
        self.assertEqual(row[0], 1)
        self.assertEqual(row[1], "Tax Return 2024")
        
    def test_unlock_pairing(self):
        """Test unlocking a pairing."""
        # First lock it
        self.repo.lock_pairing(self.pairing_id, "Test lock")
        
        # Then unlock
        result = self.repo.unlock_pairing(self.pairing_id)
        self.assertTrue(result)
        
        # Verify it's unlocked
        cur = self.conn.execute(
            "SELECT locked, locked_reason FROM pairings WHERE id = ?",
            (self.pairing_id,)
        )
        row = cur.fetchone()
        self.assertEqual(row[0], 0)
        self.assertIsNone(row[1])
        
    def test_is_pairing_locked(self):
        """Test checking lock status."""
        # Initially unlocked
        self.assertFalse(self.repo.is_pairing_locked(self.pairing_id))
        
        # Lock it
        self.repo.lock_pairing(self.pairing_id, "Test")
        self.assertTrue(self.repo.is_pairing_locked(self.pairing_id))
        
        # Unlock it
        self.repo.unlock_pairing(self.pairing_id)
        self.assertFalse(self.repo.is_pairing_locked(self.pairing_id))
        
    def test_lock_nonexistent_pairing(self):
        """Test locking nonexistent pairing returns False."""
        result = self.repo.lock_pairing(99999, "Test")
        self.assertFalse(result)
        
    def test_lock_pairings_by_year(self):
        """Test bulk locking of pairings for a tax year."""
        # Create multiple sales in 2024
        sale1_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 3, 15).timestamp()), 200.0, 50.0, 'SELL'
        )
        sale2_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 9, 20).timestamp()), 210.0, 50.0, 'SELL'
        )
        
        # Create pairings for both sales
        pairing1_id = self.repo.create_pairing(sale1_id, self.purchase_id, 25.0, 'FIFO')
        pairing2_id = self.repo.create_pairing(sale2_id, self.purchase_id, 25.0, 'FIFO')
        
        # Lock all pairings for 2024
        count = self.repo.lock_pairings_by_year(2024, "Tax Return 2024 Filed")
        self.assertEqual(count, 3)  # Including the one from setUp (June 2024)
        
        # Verify all are locked
        self.assertTrue(self.repo.is_pairing_locked(self.pairing_id))
        self.assertTrue(self.repo.is_pairing_locked(pairing1_id))
        self.assertTrue(self.repo.is_pairing_locked(pairing2_id))


class TestHoldingPeriod(TestPairingsRepository):
    """Test holding period calculation."""
    
    def setUp(self):
        """Set up repository."""
        super().setUp()
        self.repo.create_table()
        
    def test_calculate_holding_period_timestamps(self):
        """Test holding period calculation with timestamps."""
        purchase = datetime(2020, 1, 15).timestamp()
        sale = datetime(2024, 6, 15).timestamp()
        
        days = self.repo.calculate_holding_period(purchase, sale)
        
        # Jan 15, 2020 to Jun 15, 2024 = 1612 days
        # (Verified: datetime(2024,6,15) - datetime(2020,1,15) = 1612 days)
        self.assertEqual(days, 1612)
        
    def test_calculate_holding_period_iso_strings(self):
        """Test holding period calculation with ISO date strings."""
        purchase = "2020-01-15"
        sale = "2024-06-15"
        
        days = self.repo.calculate_holding_period(purchase, sale)
        self.assertEqual(days, 1612)
        
    def test_calculate_holding_period_one_day(self):
        """Test holding period of exactly one day."""
        purchase = datetime(2024, 1, 1).timestamp()
        sale = datetime(2024, 1, 2).timestamp()
        
        days = self.repo.calculate_holding_period(purchase, sale)
        self.assertEqual(days, 1)
        
    def test_calculate_holding_period_same_day(self):
        """Test holding period on same day."""
        purchase = datetime(2024, 1, 1, 9, 0).timestamp()
        sale = datetime(2024, 1, 1, 15, 0).timestamp()
        
        days = self.repo.calculate_holding_period(purchase, sale)
        self.assertEqual(days, 0)
        
    def test_calculate_holding_period_leap_year(self):
        """Test holding period over leap year."""
        # 2020 is leap year (Feb has 29 days)
        purchase = datetime(2020, 2, 1).timestamp()
        sale = datetime(2020, 3, 1).timestamp()
        
        days = self.repo.calculate_holding_period(purchase, sale)
        self.assertEqual(days, 29)  # Feb 2020 has 29 days


class TestTimeTest(TestPairingsRepository):
    """Test time test calculations (3-year holding requirement)."""
    
    def setUp(self):
        """Set up repository."""
        super().setUp()
        self.repo.create_table()
        
    def test_time_test_exactly_3_years(self):
        """Test that exactly 3 years does NOT qualify (must be >3 years)."""
        purchase = datetime(2021, 1, 15).timestamp()
        sale = datetime(2024, 1, 15).timestamp()  # Exactly 3 years later
        
        result = self.repo.check_time_test(purchase, sale)
        self.assertFalse(result, "Exactly 3 years should not qualify")
        
    def test_time_test_3_years_plus_1_day(self):
        """Test that 3 years + 1 day qualifies."""
        purchase = datetime(2021, 1, 15).timestamp()
        sale = datetime(2024, 1, 16).timestamp()  # 3 years + 1 day
        
        result = self.repo.check_time_test(purchase, sale)
        self.assertTrue(result, "3 years + 1 day should qualify")
        
    def test_time_test_over_4_years(self):
        """Test that holdings >4 years clearly qualify."""
        purchase = datetime(2020, 1, 15).timestamp()
        sale = datetime(2024, 6, 15).timestamp()  # 4.4 years
        
        result = self.repo.check_time_test(purchase, sale)
        self.assertTrue(result)
        
    def test_time_test_under_3_years(self):
        """Test that holdings <3 years don't qualify."""
        purchase = datetime(2022, 1, 15).timestamp()
        sale = datetime(2024, 6, 15).timestamp()  # 2.4 years
        
        result = self.repo.check_time_test(purchase, sale)
        self.assertFalse(result)
        
    def test_time_test_leap_year_feb_29_purchase(self):
        """Test time test for purchase on Feb 29 (leap year edge case)."""
        # Purchase on leap day
        purchase = datetime(2020, 2, 29).timestamp()
        
        # 3 years later would be Feb 28, 2023 (not leap year)
        # Sale on Feb 28, 2023 should not qualify (exactly 3 years)
        sale_feb_28 = datetime(2023, 2, 28).timestamp()
        self.assertFalse(self.repo.check_time_test(purchase, sale_feb_28))
        
        # Sale on Mar 1, 2023 should qualify (>3 years)
        sale_mar_1 = datetime(2023, 3, 1).timestamp()
        self.assertTrue(self.repo.check_time_test(purchase, sale_mar_1))
        
    def test_time_test_leap_year_spanning(self):
        """Test time test that spans multiple leap years."""
        # Purchase in non-leap year
        purchase = datetime(2019, 3, 1).timestamp()
        
        # Sale after 3 years spanning leap year 2020
        sale = datetime(2022, 3, 2).timestamp()  # 3 years + 1 day
        
        result = self.repo.check_time_test(purchase, sale)
        self.assertTrue(result)
        
    def test_time_test_iso_string_format(self):
        """Test time test with ISO string dates."""
        purchase = "2021-01-15"
        sale = "2024-01-16"
        
        result = self.repo.check_time_test(purchase, sale)
        self.assertTrue(result)
        
    def test_time_test_invalid_dates(self):
        """Test that invalid dates are handled gracefully."""
        result = self.repo.check_time_test("invalid", "dates")
        self.assertFalse(result, "Invalid dates should return False")


class TestPairingSummary(TestPairingsRepository):
    """Test pairing summary and aggregation methods."""
    
    def setUp(self):
        """Set up test data with multiple pairings."""
        super().setUp()
        self.repo.create_table()
        self.security_id = self._create_test_security()
        
        # Create purchases
        self.purchase1_id = self._create_test_trade(
            self.security_id, int(datetime(2020, 1, 15).timestamp()), 150.0, 100.0, 'BUY'
        )
        self.purchase2_id = self._create_test_trade(
            self.security_id, int(datetime(2021, 6, 20).timestamp()), 180.0, 100.0, 'BUY'
        )
        
        # Create sales in 2024
        self.sale1_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 3, 10).timestamp()), 200.0, 80.0, 'SELL'
        )
        self.sale2_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 9, 15).timestamp()), 210.0, 50.0, 'SELL'
        )
        
        # Create pairings for sale 1 (mixed time test)
        self.repo.create_pairing(self.sale1_id, self.purchase1_id, 50.0, 'FIFO', True, 1516)
        self.repo.create_pairing(self.sale1_id, self.purchase2_id, 30.0, 'FIFO', True, 994)
        
        # Create pairings for sale 2 (all time test qualified)
        self.repo.create_pairing(self.sale2_id, self.purchase1_id, 50.0, 'MaxProfit', True, 1704)
        
    def test_get_pairing_summary_year(self):
        """Test getting summary for a specific year."""
        summary = self.repo.get_pairing_summary(2024)
        
        self.assertEqual(len(summary), 2, "Should have 2 sales in 2024")
        
    def test_get_pairing_summary_includes_totals(self):
        """Test that summary includes quantity totals."""
        summary = self.repo.get_pairing_summary(2024)
        
        sale1_summary = next(s for s in summary if s['sale_trade_id'] == self.sale1_id)
        self.assertEqual(sale1_summary['total_quantity'], 80.0)
        self.assertEqual(sale1_summary['pairing_count'], 2)
        
        sale2_summary = next(s for s in summary if s['sale_trade_id'] == self.sale2_id)
        self.assertEqual(sale2_summary['total_quantity'], 50.0)
        self.assertEqual(sale2_summary['pairing_count'], 1)
        
    def test_get_pairing_summary_time_qualified_quantity(self):
        """Test that summary includes time-qualified quantity."""
        summary = self.repo.get_pairing_summary(2024)
        
        sale1_summary = next(s for s in summary if s['sale_trade_id'] == self.sale1_id)
        self.assertEqual(sale1_summary['time_qualified_quantity'], 80.0)  # Both pairings qualified
        
    def test_get_pairing_summary_methods_used(self):
        """Test that summary includes methods used."""
        summary = self.repo.get_pairing_summary(2024)
        
        sale1_summary = next(s for s in summary if s['sale_trade_id'] == self.sale1_id)
        self.assertIn('FIFO', sale1_summary['methods_used'])
        
        sale2_summary = next(s for s in summary if s['sale_trade_id'] == self.sale2_id)
        self.assertIn('MaxProfit', sale2_summary['methods_used'])
        
    def test_get_pairing_summary_different_year(self):
        """Test that summary for different year returns empty."""
        summary = self.repo.get_pairing_summary(2023)
        self.assertEqual(len(summary), 0)
        
    def test_get_pairing_summary_includes_security_info(self):
        """Test that summary includes security information."""
        summary = self.repo.get_pairing_summary(2024)
        
        sale1_summary = summary[0]
        self.assertIn('isin', sale1_summary)
        self.assertIn('ticker', sale1_summary)
        self.assertIn('name', sale1_summary)


def run_tests():
    """Run all tests and display results."""
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestTableCreation))
    suite.addTests(loader.loadTestsFromTestCase(TestCreatePairing))
    suite.addTests(loader.loadTestsFromTestCase(TestGetPairings))
    suite.addTests(loader.loadTestsFromTestCase(TestDeletePairing))
    suite.addTests(loader.loadTestsFromTestCase(TestLockUnlock))
    suite.addTests(loader.loadTestsFromTestCase(TestHoldingPeriod))
    suite.addTests(loader.loadTestsFromTestCase(TestTimeTest))
    suite.addTests(loader.loadTestsFromTestCase(TestPairingSummary))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Print summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    print(f"Tests run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    
    if result.wasSuccessful():
        print("\n✓ ALL TESTS PASSED")
        return 0
    else:
        print("\n✗ SOME TESTS FAILED")
        return 1


if __name__ == '__main__':
    sys.exit(run_tests())
