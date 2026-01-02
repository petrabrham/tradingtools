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
from db.repositories.trades import TradeType
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
        
        # Create trades table (simplified for testing, includes remaining_quantity)
        self.conn.execute("""
            CREATE TABLE trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                isin_id INTEGER NOT NULL,
                timestamp INTEGER NOT NULL,
                price_for_share REAL NOT NULL,
                number_of_shares REAL NOT NULL,
                remaining_quantity REAL NOT NULL,
                trade_type INTEGER NOT NULL,
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
        
    def _create_test_trade(self, security_id, timestamp, price, quantity, trade_type=TradeType.BUY):
        """Helper to create a test trade."""
        cur = self.conn.execute(
            "INSERT INTO trades (isin_id, timestamp, price_for_share, number_of_shares, remaining_quantity, trade_type) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (security_id, timestamp, price, quantity, quantity, int(trade_type))  # remaining_quantity = quantity initially
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
            TradeType.BUY
        )
        self.sale_id = self._create_test_trade(
            self.security_id,
            int(sale_date.timestamp()),
            200.0,
            50.0,
            TradeType.SELL
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
            self.security_id, int(datetime(2020, 1, 15).timestamp()), 150.0, 100.0, TradeType.BUY
        )
        self.purchase2_id = self._create_test_trade(
            self.security_id, int(datetime(2021, 6, 20).timestamp()), 180.0, 50.0, TradeType.BUY
        )
        
        # Create sale trade
        self.sale_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 11, 10).timestamp()), 200.0, 100.0, TradeType.SELL
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
            self.security_id, int(datetime(2020, 1, 15).timestamp()), 150.0, 50.0, TradeType.BUY
        )
        self.sale_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 6, 15).timestamp()), 200.0, 50.0, TradeType.SELL
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
            self.security_id, int(datetime(2020, 1, 15).timestamp()), 150.0, 50.0, TradeType.BUY
        )
        self.sale_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 6, 15).timestamp()), 200.0, 50.0, TradeType.SELL
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
            self.security_id, int(datetime(2024, 3, 15).timestamp()), 200.0, 50.0, TradeType.SELL
        )
        sale2_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 9, 20).timestamp()), 210.0, 50.0, TradeType.SELL
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
            self.security_id, int(datetime(2020, 1, 15).timestamp()), 150.0, 100.0, TradeType.BUY
        )
        self.purchase2_id = self._create_test_trade(
            self.security_id, int(datetime(2021, 6, 20).timestamp()), 180.0, 100.0, TradeType.BUY
        )
        
        # Create sales in 2024
        self.sale1_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 3, 10).timestamp()), 200.0, 80.0, TradeType.SELL
        )
        self.sale2_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 9, 15).timestamp()), 210.0, 50.0, TradeType.SELL
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


class TestLotAvailability(TestPairingsRepository):
    """Test lot availability calculation methods."""
    
    def setUp(self):
        """Set up test data with multiple purchases and partial pairings."""
        super().setUp()
        self.repo.create_table()
        self.security_id = self._create_test_security()
        
        # Create three purchase lots
        self.purchase1_id = self._create_test_trade(
            self.security_id, int(datetime(2020, 1, 15).timestamp()), 150.0, 100.0, TradeType.BUY
        )
        self.purchase2_id = self._create_test_trade(
            self.security_id, int(datetime(2021, 6, 20).timestamp()), 180.0, 50.0, TradeType.BUY
        )
        self.purchase3_id = self._create_test_trade(
            self.security_id, int(datetime(2023, 3, 10).timestamp()), 200.0, 75.0, TradeType.BUY
        )
        
        # Create a sale
        self.sale_timestamp = int(datetime(2024, 11, 10).timestamp())
        self.sale_id = self._create_test_trade(
            self.security_id, self.sale_timestamp, 220.0, 80.0, TradeType.SELL
        )
        
        # Create partial pairings
        # Purchase 1: 100 total, 60 paired, 40 available
        self.repo.create_pairing(self.sale_id, self.purchase1_id, 60.0, 'FIFO')
        
        # Purchase 2: 50 total, 50 paired (fully used), 0 available
        self.repo.create_pairing(self.sale_id, self.purchase2_id, 50.0, 'FIFO')
        
        # Purchase 3: 75 total, 0 paired, 75 available
        
    def test_get_available_lots_all_purchases(self):
        """Test that get_available_lots returns all purchases before sale."""
        lots = self.repo.get_available_lots(self.security_id, self.sale_timestamp)
        
        self.assertEqual(len(lots), 3, "Should return all 3 purchases")
        
    def test_get_available_lots_correct_quantities(self):
        """Test that available quantities are calculated correctly."""
        lots = self.repo.get_available_lots(self.security_id, self.sale_timestamp)
        
        # Find each lot by ID
        lot1 = next(l for l in lots if l['id'] == self.purchase1_id)
        lot2 = next(l for l in lots if l['id'] == self.purchase2_id)
        lot3 = next(l for l in lots if l['id'] == self.purchase3_id)
        
        # Verify quantities
        self.assertEqual(lot1['quantity'], 100.0)
        self.assertEqual(lot1['paired_quantity'], 60.0)
        self.assertEqual(lot1['available_quantity'], 40.0)
        
        self.assertEqual(lot2['quantity'], 50.0)
        self.assertEqual(lot2['paired_quantity'], 50.0)
        self.assertEqual(lot2['available_quantity'], 0.0)
        
        self.assertEqual(lot3['quantity'], 75.0)
        self.assertEqual(lot3['paired_quantity'], 0.0)
        self.assertEqual(lot3['available_quantity'], 75.0)
        
    def test_get_available_lots_includes_time_test(self):
        """Test that available lots include time test qualification."""
        lots = self.repo.get_available_lots(self.security_id, self.sale_timestamp)
        
        lot1 = next(l for l in lots if l['id'] == self.purchase1_id)
        lot2 = next(l for l in lots if l['id'] == self.purchase2_id)
        lot3 = next(l for l in lots if l['id'] == self.purchase3_id)
        
        # Lot 1 (2020-01-15) and Lot 2 (2021-06-20) are > 3 years before sale (2024-11-10)
        self.assertTrue(lot1['time_test_qualified'])
        self.assertTrue(lot2['time_test_qualified'])
        
        # Lot 3 (2023-03-10) is < 3 years before sale
        self.assertFalse(lot3['time_test_qualified'])
        
    def test_get_available_lots_includes_holding_period(self):
        """Test that available lots include holding period in days."""
        lots = self.repo.get_available_lots(self.security_id, self.sale_timestamp)
        
        for lot in lots:
            self.assertIn('holding_period_days', lot)
            self.assertGreater(lot['holding_period_days'], 0)
            
    def test_get_available_lots_excludes_future_purchases(self):
        """Test that purchases after the sale are excluded."""
        # Create a purchase after the sale
        future_purchase_id = self._create_test_trade(
            self.security_id, 
            int(datetime(2025, 1, 1).timestamp()), 
            250.0, 
            100.0, 
            TradeType.BUY
        )
        
        lots = self.repo.get_available_lots(self.security_id, self.sale_timestamp)
        
        # Should still have only 3 lots (not 4)
        self.assertEqual(len(lots), 3)
        
        # Verify future purchase is not in results
        future_lot_ids = [l['id'] for l in lots if l['id'] == future_purchase_id]
        self.assertEqual(len(future_lot_ids), 0, "Future purchases should be excluded")
        
    def test_get_available_lots_ordered_by_date(self):
        """Test that lots are returned in chronological order."""
        lots = self.repo.get_available_lots(self.security_id, self.sale_timestamp)
        
        # Verify order: purchase1 (2020) < purchase2 (2021) < purchase3 (2023)
        self.assertEqual(lots[0]['id'], self.purchase1_id)
        self.assertEqual(lots[1]['id'], self.purchase2_id)
        self.assertEqual(lots[2]['id'], self.purchase3_id)
        
    def test_calculate_available_quantity_for_purchase(self):
        """Test calculating available quantity for specific purchase."""
        # Lot 1: 40 available
        available1 = self.repo.calculate_available_quantity_for_purchase(self.purchase1_id)
        self.assertEqual(available1, 40.0)
        
        # Lot 2: 0 available (fully paired)
        available2 = self.repo.calculate_available_quantity_for_purchase(self.purchase2_id)
        self.assertEqual(available2, 0.0)
        
        # Lot 3: 75 available (never paired)
        available3 = self.repo.calculate_available_quantity_for_purchase(self.purchase3_id)
        self.assertEqual(available3, 75.0)
        
    def test_calculate_available_quantity_nonexistent_purchase(self):
        """Test calculating available quantity for nonexistent purchase."""
        available = self.repo.calculate_available_quantity_for_purchase(99999)
        self.assertEqual(available, 0.0)
        
    def test_validate_pairing_availability_success(self):
        """Test successful validation when sufficient quantity available."""
        # Lot 1 has 40 available, request 20
        is_valid, error = self.repo.validate_pairing_availability(self.purchase1_id, 20.0)
        self.assertTrue(is_valid)
        self.assertEqual(error, "")
        
    def test_validate_pairing_availability_exact_quantity(self):
        """Test validation when requesting exact available quantity."""
        # Lot 1 has exactly 40 available
        is_valid, error = self.repo.validate_pairing_availability(self.purchase1_id, 40.0)
        self.assertTrue(is_valid)
        
    def test_validate_pairing_availability_insufficient(self):
        """Test validation fails when requesting more than available."""
        # Lot 1 has 40 available, request 50
        is_valid, error = self.repo.validate_pairing_availability(self.purchase1_id, 50.0)
        self.assertFalse(is_valid)
        self.assertIn("Insufficient quantity", error)
        self.assertIn("40", error)
        self.assertIn("50", error)
        
    def test_validate_pairing_availability_fully_paired(self):
        """Test validation fails for fully paired lot."""
        # Lot 2 has 0 available
        is_valid, error = self.repo.validate_pairing_availability(self.purchase2_id, 10.0)
        self.assertFalse(is_valid)
        self.assertIn("fully paired", error.lower())
        
    def test_validate_pairing_availability_negative_quantity(self):
        """Test validation fails for negative quantity."""
        is_valid, error = self.repo.validate_pairing_availability(self.purchase1_id, -10.0)
        self.assertFalse(is_valid)
        self.assertIn("positive", error.lower())
        
    def test_validate_pairing_availability_zero_quantity(self):
        """Test validation fails for zero quantity."""
        is_valid, error = self.repo.validate_pairing_availability(self.purchase1_id, 0.0)
        self.assertFalse(is_valid)
        self.assertIn("positive", error.lower())
        
    def test_get_available_lots_multiple_sales(self):
        """Test that availability reflects pairings across multiple sales."""
        # Create a second sale
        sale2_id = self._create_test_trade(
            self.security_id,
            int(datetime(2024, 12, 15).timestamp()),
            230.0,
            30.0,
            TradeType.SELL
        )
        
        # Pair 20 more from purchase 1 with sale 2
        # Purchase 1 now has: 100 total, 60 + 20 = 80 paired, 20 available
        self.repo.create_pairing(sale2_id, self.purchase1_id, 20.0, 'FIFO')
        
        available = self.repo.calculate_available_quantity_for_purchase(self.purchase1_id)
        self.assertEqual(available, 20.0)


class TestMethodCombinations(TestPairingsRepository):
    """Test method combination derivation and TimeTest detection."""
    
    def setUp(self):
        """Set up test data with various pairing scenarios."""
        super().setUp()
        self.repo.create_table()
        self.security_id = self._create_test_security()
        
        # Create purchases with varying time test status
        self.old_purchase1_id = self._create_test_trade(
            self.security_id, int(datetime(2020, 1, 15).timestamp()), 150.0, 100.0, TradeType.BUY
        )
        self.old_purchase2_id = self._create_test_trade(
            self.security_id, int(datetime(2020, 6, 20).timestamp()), 180.0, 50.0, TradeType.BUY
        )
        self.new_purchase_id = self._create_test_trade(
            self.security_id, int(datetime(2023, 3, 10).timestamp()), 200.0, 75.0, TradeType.BUY
        )
        
        # Create sales
        self.sale1_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 11, 10).timestamp()), 220.0, 100.0, TradeType.SELL
        )
        self.sale2_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 11, 15).timestamp()), 225.0, 80.0, TradeType.SELL
        )
        self.sale3_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 11, 20).timestamp()), 230.0, 50.0, TradeType.SELL
        )
        
    def test_derive_method_combination_single_method_no_timetest(self):
        """Test deriving combination for single method without TimeTest."""
        # All pairings use FIFO, none are time-qualified
        self.repo.create_pairing(self.sale1_id, self.new_purchase_id, 75.0, 'FIFO', False)
        self.repo.create_pairing(self.sale1_id, self.old_purchase1_id, 25.0, 'FIFO', False)
        
        combination = self.repo.derive_method_combination(self.sale1_id)
        self.assertEqual(combination, 'FIFO')
        
    def test_derive_method_combination_all_time_qualified(self):
        """Test deriving combination when all lots are time-qualified."""
        # All pairings use MaxProfit and all are time-qualified
        self.repo.create_pairing(self.sale1_id, self.old_purchase1_id, 60.0, 'MaxProfit', True)
        self.repo.create_pairing(self.sale1_id, self.old_purchase2_id, 40.0, 'MaxProfit', True)
        
        combination = self.repo.derive_method_combination(self.sale1_id)
        self.assertEqual(combination, 'MaxProfit')
        
    def test_derive_method_combination_timetest_with_fallback(self):
        """Test deriving combination for TimeTest with fallback."""
        # MaxProfit on time-qualified, MaxLose on non-qualified
        self.repo.create_pairing(self.sale1_id, self.old_purchase1_id, 50.0, 'MaxProfit', True, 1760)
        self.repo.create_pairing(self.sale1_id, self.old_purchase2_id, 30.0, 'MaxProfit', True, 1604)
        self.repo.create_pairing(self.sale1_id, self.new_purchase_id, 20.0, 'MaxLose', False, 610)
        
        combination = self.repo.derive_method_combination(self.sale1_id)
        self.assertEqual(combination, 'MaxProfit+TT → MaxLose')
        
    def test_derive_method_combination_lifo_timetest_fifo(self):
        """Test LIFO+TT → FIFO combination."""
        # LIFO on time-qualified, FIFO on non-qualified
        self.repo.create_pairing(self.sale2_id, self.old_purchase2_id, 50.0, 'LIFO', True)
        self.repo.create_pairing(self.sale2_id, self.new_purchase_id, 30.0, 'FIFO', False)
        
        combination = self.repo.derive_method_combination(self.sale2_id)
        self.assertEqual(combination, 'LIFO+TT → FIFO')
        
    def test_derive_method_combination_mixed_methods(self):
        """Test deriving combination with mixed methods."""
        # Multiple methods on non-qualified (shouldn't happen in practice, but test it)
        self.repo.create_pairing(self.sale3_id, self.new_purchase_id, 25.0, 'FIFO', False)
        self.repo.create_pairing(self.sale3_id, self.new_purchase_id, 25.0, 'LIFO', False)
        
        combination = self.repo.derive_method_combination(self.sale3_id)
        self.assertIn('Mixed', combination)
        
    def test_derive_method_combination_no_pairings(self):
        """Test deriving combination for sale with no pairings."""
        # Create a sale but don't pair it
        empty_sale_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 12, 1).timestamp()), 240.0, 50.0, TradeType.SELL
        )
        
        combination = self.repo.derive_method_combination(empty_sale_id)
        self.assertEqual(combination, 'No pairings')
        
    def test_get_method_breakdown_timetest_scenario(self):
        """Test getting detailed method breakdown for TimeTest scenario."""
        # Create TimeTest scenario: MaxProfit(70) + MaxLose(30)
        self.repo.create_pairing(self.sale1_id, self.old_purchase1_id, 50.0, 'MaxProfit', True)
        self.repo.create_pairing(self.sale1_id, self.old_purchase2_id, 20.0, 'MaxProfit', True)
        self.repo.create_pairing(self.sale1_id, self.new_purchase_id, 30.0, 'MaxLose', False)
        
        breakdown = self.repo.get_method_breakdown(self.sale1_id)
        
        self.assertEqual(breakdown['combination'], 'MaxProfit+TT → MaxLose')
        self.assertEqual(breakdown['total_quantity'], 100.0)
        
        # Time-qualified breakdown
        self.assertEqual(breakdown['time_qualified']['quantity'], 70.0)
        self.assertEqual(breakdown['time_qualified']['methods']['MaxProfit'], 70.0)
        
        # Non-qualified breakdown
        self.assertEqual(breakdown['non_qualified']['quantity'], 30.0)
        self.assertEqual(breakdown['non_qualified']['methods']['MaxLose'], 30.0)
        
    def test_get_method_breakdown_single_method(self):
        """Test getting breakdown for single method (no TimeTest)."""
        # All FIFO, no time qualification
        self.repo.create_pairing(self.sale2_id, self.new_purchase_id, 50.0, 'FIFO', False)
        self.repo.create_pairing(self.sale2_id, self.old_purchase1_id, 30.0, 'FIFO', False)
        
        breakdown = self.repo.get_method_breakdown(self.sale2_id)
        
        self.assertEqual(breakdown['combination'], 'FIFO')
        self.assertEqual(breakdown['total_quantity'], 80.0)
        self.assertEqual(breakdown['time_qualified']['quantity'], 0.0)
        self.assertEqual(breakdown['non_qualified']['quantity'], 80.0)
        
    def test_is_timetest_applied_true(self):
        """Test TimeTest detection when TimeTest was applied."""
        # Mix of qualified and non-qualified
        self.repo.create_pairing(self.sale1_id, self.old_purchase1_id, 60.0, 'MaxProfit', True)
        self.repo.create_pairing(self.sale1_id, self.new_purchase_id, 40.0, 'MaxLose', False)
        
        result = self.repo.is_timetest_applied(self.sale1_id)
        self.assertTrue(result)
        
    def test_is_timetest_applied_false_all_qualified(self):
        """Test TimeTest detection when all lots are time-qualified."""
        # All qualified (implicit success, but not technically "applied")
        self.repo.create_pairing(self.sale2_id, self.old_purchase1_id, 50.0, 'MaxProfit', True)
        self.repo.create_pairing(self.sale2_id, self.old_purchase2_id, 30.0, 'MaxProfit', True)
        
        result = self.repo.is_timetest_applied(self.sale2_id)
        self.assertFalse(result, "All qualified means no fallback was needed")
        
    def test_is_timetest_applied_false_none_qualified(self):
        """Test TimeTest detection when no lots are time-qualified."""
        # None qualified
        self.repo.create_pairing(self.sale3_id, self.new_purchase_id, 50.0, 'FIFO', False)
        
        result = self.repo.is_timetest_applied(self.sale3_id)
        self.assertFalse(result, "No qualified lots means TimeTest wasn't applied")
        
    def test_is_timetest_applied_no_pairings(self):
        """Test TimeTest detection for sale with no pairings."""
        empty_sale_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 12, 1).timestamp()), 240.0, 50.0, TradeType.SELL
        )
        
        result = self.repo.is_timetest_applied(empty_sale_id)
        self.assertFalse(result)


class TestFIFOMethod(TestPairingsRepository):
    """Test FIFO (First-In-First-Out) pairing method."""
    
    def setUp(self):
        """Set up test data for FIFO testing."""
        super().setUp()
        self.repo.create_table()
        self.security_id = self._create_test_security()
        
        # Create purchases at different times and prices
        # Purchase 1: Oldest, cheapest
        self.purchase1_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 1, 15).timestamp()), 100.0, 50.0, TradeType.BUY
        )
        # Purchase 2: Middle
        self.purchase2_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 3, 20).timestamp()), 150.0, 40.0, TradeType.BUY
        )
        # Purchase 3: Newest, most expensive
        self.purchase3_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 6, 10).timestamp()), 200.0, 60.0, TradeType.BUY
        )
        
        # Create sale
        self.sale_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 11, 15).timestamp()), 180.0, 100.0, TradeType.SELL
        )
    
    def test_fifo_simple_full_match(self):
        """Test FIFO with exact match of oldest lot."""
        # Sell exactly the oldest purchase
        sale_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 11, 15).timestamp()), 180.0, 50.0, TradeType.SELL
        )
        
        result = self.repo.apply_fifo(sale_id)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['pairings_created'], 1)
        self.assertEqual(result['total_quantity_paired'], 50.0)
        self.assertIsNone(result['error'])
        
        # Verify pairing uses oldest lot
        pairings = self.repo.get_pairings_for_sale(sale_id)
        self.assertEqual(len(pairings), 1)
        self.assertEqual(pairings[0]['purchase_trade_id'], self.purchase1_id)
        self.assertEqual(pairings[0]['quantity'], 50.0)
        self.assertEqual(pairings[0]['method'], 'FIFO')
    
    def test_fifo_partial_lot_matching(self):
        """Test FIFO with partial use of lots."""
        # Sell 70 shares: should take 50 from purchase1, 20 from purchase2
        sale_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 11, 15).timestamp()), 180.0, 70.0, TradeType.SELL
        )
        
        result = self.repo.apply_fifo(sale_id)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['pairings_created'], 2)
        self.assertEqual(result['total_quantity_paired'], 70.0)
        
        # Verify pairings use oldest lots first
        pairings = self.repo.get_pairings_for_sale(sale_id)
        self.assertEqual(len(pairings), 2)
        
        # First pairing: all of purchase1
        self.assertEqual(pairings[0]['purchase_trade_id'], self.purchase1_id)
        self.assertEqual(pairings[0]['quantity'], 50.0)
        
        # Second pairing: partial purchase2
        self.assertEqual(pairings[1]['purchase_trade_id'], self.purchase2_id)
        self.assertEqual(pairings[1]['quantity'], 20.0)
    
    def test_fifo_multiple_purchases(self):
        """Test FIFO spanning all three purchases."""
        # Sell 120 shares: 50 from p1, 40 from p2, 30 from p3
        sale_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 11, 15).timestamp()), 180.0, 120.0, TradeType.SELL
        )
        
        result = self.repo.apply_fifo(sale_id)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['pairings_created'], 3)
        self.assertEqual(result['total_quantity_paired'], 120.0)
        
        pairings = self.repo.get_pairings_for_sale(sale_id)
        self.assertEqual(len(pairings), 3)
        
        # Verify order: oldest to newest
        self.assertEqual(pairings[0]['purchase_trade_id'], self.purchase1_id)
        self.assertEqual(pairings[0]['quantity'], 50.0)
        
        self.assertEqual(pairings[1]['purchase_trade_id'], self.purchase2_id)
        self.assertEqual(pairings[1]['quantity'], 40.0)
        
        self.assertEqual(pairings[2]['purchase_trade_id'], self.purchase3_id)
        self.assertEqual(pairings[2]['quantity'], 30.0)
    
    def test_fifo_insufficient_quantity(self):
        """Test FIFO when not enough shares available.
        
        The new algorithm creates partial pairings with all available lots (150 shares),
        then fails when trying to pair the remaining 50 shares.
        """
        # Try to sell 200 shares but only 150 available
        sale_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 11, 15).timestamp()), 180.0, 200.0, TradeType.SELL
        )
        
        result = self.repo.apply_fifo(sale_id)
        
        self.assertFalse(result['success'])
        # Should have paired all 3 available lots (150 shares total)
        self.assertEqual(result['pairings_created'], 3)
        self.assertEqual(result['total_quantity_paired'], 150.0)
        self.assertIn('Insufficient quantity', result['error'])
        self.assertIn('50.0', result['error'])  # Missing 50 shares
        
        # Verify partial pairings were created
        pairings = self.repo.get_pairings_for_sale(sale_id)
        self.assertEqual(len(pairings), 3)
        self.assertEqual(sum(p['quantity'] for p in pairings), 150.0)
    
    def test_fifo_with_existing_pairings(self):
        """Test FIFO when sale is already partially paired."""
        # Manually pair 30 shares from purchase1
        self.repo.create_pairing(self.sale_id, self.purchase1_id, 30.0, 'Manual')
        
        # Apply FIFO to remaining 70 shares
        result = self.repo.apply_fifo(self.sale_id)
        
        self.assertTrue(result['success'])
        # Should pair: 20 more from purchase1, 40 from purchase2, 10 from purchase3
        self.assertEqual(result['pairings_created'], 3)
        self.assertEqual(result['total_quantity_paired'], 70.0)
        
        # Total pairings: 1 manual + 3 FIFO = 4
        pairings = self.repo.get_pairings_for_sale(self.sale_id)
        self.assertEqual(len(pairings), 4)
        self.assertEqual(sum(p['quantity'] for p in pairings), 100.0)
    
    def test_fifo_already_fully_paired(self):
        """Test FIFO when sale is already fully paired."""
        # Pair all 100 shares
        self.repo.create_pairing(self.sale_id, self.purchase1_id, 50.0, 'Manual')
        self.repo.create_pairing(self.sale_id, self.purchase2_id, 40.0, 'Manual')
        self.repo.create_pairing(self.sale_id, self.purchase3_id, 10.0, 'Manual')
        
        result = self.repo.apply_fifo(self.sale_id)
        
        self.assertTrue(result['success'])  # Success, but nothing to do
        self.assertEqual(result['pairings_created'], 0)
        self.assertEqual(result['total_quantity_paired'], 0.0)
        self.assertIn('already fully paired', result['error'])
    
    def test_fifo_no_available_purchases(self):
        """Test FIFO when no purchases exist before sale."""
        # Create sale before any purchases
        early_sale_id = self._create_test_trade(
            self.security_id, int(datetime(2023, 1, 1).timestamp()), 180.0, 50.0, TradeType.SELL
        )
        
        result = self.repo.apply_fifo(early_sale_id)
        
        self.assertFalse(result['success'])
        self.assertEqual(result['pairings_created'], 0)
        self.assertIn('No available purchase lots', result['error'])
    
    def test_fifo_invalid_sale_id(self):
        """Test FIFO with non-existent sale ID."""
        with self.assertRaises(ValueError) as context:
            self.repo.apply_fifo(99999)
        
        self.assertIn('not found', str(context.exception))
    
    def test_fifo_buy_trade_error(self):
        """Test FIFO with a BUY trade (should fail)."""
        with self.assertRaises(ValueError) as context:
            self.repo.apply_fifo(self.purchase1_id)  # This is a BUY
        
        self.assertIn('not a SELL', str(context.exception))
    
    def test_fifo_holding_period_calculation(self):
        """Test that FIFO correctly calculates holding periods."""
        result = self.repo.apply_fifo(self.sale_id)
        
        self.assertTrue(result['success'])
        
        pairings = self.repo.get_pairings_for_sale(self.sale_id)
        
        # Each pairing should have holding_period_days calculated
        for p in pairings:
            self.assertIsNotNone(p['holding_period_days'])
            self.assertGreater(p['holding_period_days'], 0)
        
        # First pairing (oldest) should have longest holding period
        self.assertGreater(pairings[0]['holding_period_days'], 
                          pairings[1]['holding_period_days'])
    
    def test_fifo_time_test_qualification(self):
        """Test that FIFO correctly marks time test qualification."""
        # Create old purchase (> 3 years)
        old_purchase = self._create_test_trade(
            self.security_id, int(datetime(2020, 1, 1).timestamp()), 80.0, 30.0, TradeType.BUY
        )
        
        # Create sale
        sale_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 11, 15).timestamp()), 180.0, 30.0, TradeType.SELL
        )
        
        result = self.repo.apply_fifo(sale_id)
        
        self.assertTrue(result['success'])
        
        pairings = self.repo.get_pairings_for_sale(sale_id)
        self.assertEqual(len(pairings), 1)
        
        # Should be time test qualified (> 3 years)
        self.assertTrue(pairings[0]['time_test_qualified'])
        self.assertGreater(pairings[0]['holding_period_days'], 1095)


class TestRemainingQuantityTracking(TestPairingsRepository):
    """Test that remaining_quantity is properly maintained in trades table."""
    
    def setUp(self):
        """Set up test data."""
        super().setUp()
        self.repo.create_table()
        self.security_id = self._create_test_security()
        
        self.purchase_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 1, 15).timestamp()), 100.0, 50.0, TradeType.BUY
        )
        self.sale_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 11, 15).timestamp()), 180.0, 30.0, TradeType.SELL
        )
    
    def _get_remaining_quantity(self, trade_id):
        """Helper to get remaining_quantity for a trade."""
        cur = self.conn.execute("SELECT remaining_quantity FROM trades WHERE id = ?", (trade_id,))
        row = cur.fetchone()
        return row[0] if row else None
    
    def test_initial_remaining_quantity(self):
        """Test that remaining_quantity is initialized to number_of_shares."""
        purchase_remaining = self._get_remaining_quantity(self.purchase_id)
        sale_remaining = self._get_remaining_quantity(self.sale_id)
        
        self.assertEqual(purchase_remaining, 50.0)
        self.assertEqual(sale_remaining, 30.0)
    
    def test_create_pairing_decrements_remaining_quantity(self):
        """Test that creating a pairing decrements remaining_quantity for both trades."""
        # Pair 20 shares
        self.repo.create_pairing(self.sale_id, self.purchase_id, 20.0, 'FIFO')
        
        # Check remaining quantities
        purchase_remaining = self._get_remaining_quantity(self.purchase_id)
        sale_remaining = self._get_remaining_quantity(self.sale_id)
        
        self.assertEqual(purchase_remaining, 30.0)  # 50 - 20
        self.assertEqual(sale_remaining, 10.0)  # 30 - 20
    
    def test_delete_pairing_restores_remaining_quantity(self):
        """Test that deleting a pairing restores remaining_quantity."""
        # Create pairing
        pairing_id = self.repo.create_pairing(self.sale_id, self.purchase_id, 20.0, 'FIFO')
        
        # Verify decremented
        self.assertEqual(self._get_remaining_quantity(self.purchase_id), 30.0)
        self.assertEqual(self._get_remaining_quantity(self.sale_id), 10.0)
        
        # Delete pairing
        success = self.repo.delete_pairing(pairing_id)
        self.assertTrue(success)
        
        # Verify restored
        self.assertEqual(self._get_remaining_quantity(self.purchase_id), 50.0)
        self.assertEqual(self._get_remaining_quantity(self.sale_id), 30.0)
    
    def test_multiple_pairings_accumulate_correctly(self):
        """Test that multiple pairings correctly accumulate remaining_quantity changes."""
        # Create second sale
        sale2_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 11, 20).timestamp()), 185.0, 25.0, TradeType.SELL
        )
        
        # Pair 15 from purchase to first sale
        self.repo.create_pairing(self.sale_id, self.purchase_id, 15.0, 'FIFO')
        self.assertEqual(self._get_remaining_quantity(self.purchase_id), 35.0)
        
        # Pair 20 from purchase to second sale
        self.repo.create_pairing(sale2_id, self.purchase_id, 20.0, 'FIFO')
        self.assertEqual(self._get_remaining_quantity(self.purchase_id), 15.0)  # 50 - 15 - 20
        
        # Check sales
        self.assertEqual(self._get_remaining_quantity(self.sale_id), 15.0)  # 30 - 15
        self.assertEqual(self._get_remaining_quantity(sale2_id), 5.0)  # 25 - 20
    
    def test_get_available_lots_uses_remaining_quantity(self):
        """Test that get_available_lots correctly uses remaining_quantity."""
        # Pair some shares
        self.repo.create_pairing(self.sale_id, self.purchase_id, 20.0, 'FIFO')
        
        # Create new sale to query available lots
        sale2_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 12, 1).timestamp()), 190.0, 30.0, TradeType.SELL
        )
        
        available_lots = self.repo.get_available_lots(self.security_id, int(datetime(2024, 12, 1).timestamp()))
        
        # Should have one lot with 30 shares remaining (50 - 20)
        self.assertEqual(len(available_lots), 1)
        self.assertEqual(available_lots[0]['id'], self.purchase_id)
        self.assertEqual(available_lots[0]['available_quantity'], 30.0)
        self.assertEqual(available_lots[0]['paired_quantity'], 20.0)
    
    def test_calculate_available_quantity_uses_remaining_quantity(self):
        """Test that calculate_available_quantity_for_purchase uses remaining_quantity."""
        # Pair some shares
        self.repo.create_pairing(self.sale_id, self.purchase_id, 25.0, 'FIFO')
        
        available = self.repo.calculate_available_quantity_for_purchase(self.purchase_id)
        
        # Should be 25 remaining (50 - 25)
        self.assertEqual(available, 25.0)
    
    def test_fifo_method_maintains_remaining_quantity(self):
        """Test that apply_fifo correctly maintains remaining_quantity."""
        # Create additional purchases
        purchase2_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 3, 20).timestamp()), 150.0, 40.0, TradeType.BUY
        )
        
        # Create large sale that requires both purchases
        sale_big_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 11, 25).timestamp()), 200.0, 80.0, TradeType.SELL
        )
        
        # Apply FIFO
        result = self.repo.apply_fifo(sale_big_id)
        self.assertTrue(result['success'])
        
        # Check remaining quantities
        # Purchase 1: 50 - 50 = 0 (fully used)
        # Purchase 2: 40 - 30 = 10 (partially used)
        # Sale: 80 - 80 = 0 (fully paired)
        self.assertEqual(self._get_remaining_quantity(self.purchase_id), 0.0)
        self.assertEqual(self._get_remaining_quantity(purchase2_id), 10.0)
        self.assertEqual(self._get_remaining_quantity(sale_big_id), 0.0)


class TestLIFOMethod(TestPairingsRepository):
    """Test LIFO (Last-In-First-Out) pairing method."""
    
    def setUp(self):
        """Set up test data for LIFO testing."""
        super().setUp()
        self.repo.create_table()
        self.security_id = self._create_test_security()
        
        # Create purchases at different times and prices (same as FIFO tests)
        # Purchase 1: Oldest, cheapest
        self.purchase1_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 1, 15).timestamp()), 100.0, 50.0, TradeType.BUY
        )
        # Purchase 2: Middle
        self.purchase2_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 3, 20).timestamp()), 150.0, 40.0, TradeType.BUY
        )
        # Purchase 3: Newest, most expensive
        self.purchase3_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 6, 10).timestamp()), 200.0, 60.0, TradeType.BUY
        )
        
        # Create sale
        self.sale_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 11, 15).timestamp()), 180.0, 100.0, TradeType.SELL
        )
    
    def test_lifo_simple_full_match(self):
        """Test LIFO with exact match of newest lot."""
        # Create small sale matching newest purchase
        small_sale_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 11, 15).timestamp()), 180.0, 60.0, TradeType.SELL
        )
        
        result = self.repo.apply_lifo(small_sale_id)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['pairings_created'], 1)
        self.assertEqual(result['total_quantity_paired'], 60.0)
        
        pairings = self.repo.get_pairings_for_sale(small_sale_id)
        self.assertEqual(len(pairings), 1)
        self.assertEqual(pairings[0]['purchase_trade_id'], self.purchase3_id)  # Newest
        self.assertEqual(pairings[0]['method'], 'LIFO')
    
    def test_lifo_multiple_purchases(self):
        """Test LIFO spanning multiple purchases (newest to oldest)."""
        result = self.repo.apply_lifo(self.sale_id)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['pairings_created'], 2)
        self.assertEqual(result['total_quantity_paired'], 100.0)
        
        pairings = self.repo.get_pairings_for_sale(self.sale_id)
        self.assertEqual(len(pairings), 2)
        
        # LIFO: P3(60) + P2(40) = 100
        self.assertEqual(pairings[0]['purchase_trade_id'], self.purchase3_id)
        self.assertEqual(pairings[0]['quantity'], 60.0)
        
        self.assertEqual(pairings[1]['purchase_trade_id'], self.purchase2_id)
        self.assertEqual(pairings[1]['quantity'], 40.0)
    
    def test_lifo_partial_lot_matching(self):
        """Test LIFO with partial use of lots."""
        # Sell 70 shares
        sale_70 = self._create_test_trade(
            self.security_id, int(datetime(2024, 11, 15).timestamp()), 180.0, 70.0, TradeType.SELL
        )
        
        result = self.repo.apply_lifo(sale_70)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['pairings_created'], 2)
        self.assertEqual(result['total_quantity_paired'], 70.0)
        
        pairings = self.repo.get_pairings_for_sale(sale_70)
        
        # LIFO: P3(60) + partial P2(10)
        self.assertEqual(pairings[0]['purchase_trade_id'], self.purchase3_id)
        self.assertEqual(pairings[0]['quantity'], 60.0)
        
        self.assertEqual(pairings[1]['purchase_trade_id'], self.purchase2_id)
        self.assertEqual(pairings[1]['quantity'], 10.0)
    
    def test_lifo_order_opposite_of_fifo(self):
        """Test that LIFO pairs in reverse order compared to FIFO."""
        result_lifo = self.repo.apply_lifo(self.sale_id)
        pairings_lifo = self.repo.get_pairings_for_sale(self.sale_id)
        
        # LIFO should use newest first
        self.assertEqual(pairings_lifo[0]['purchase_trade_id'], self.purchase3_id)
    
    def test_lifo_no_available_purchases(self):
        """Test LIFO when no purchases exist before sale."""
        early_sale_id = self._create_test_trade(
            self.security_id, int(datetime(2023, 1, 1).timestamp()), 180.0, 50.0, TradeType.SELL
        )
        
        result = self.repo.apply_lifo(early_sale_id)
        
        self.assertFalse(result['success'])
        self.assertIn('No available purchase lots', result['error'])


class TestMaxLoseMethod(TestPairingsRepository):
    """Test MaxLose (Highest Cost First) pairing method."""
    
    def setUp(self):
        """Set up test data for MaxLose testing."""
        super().setUp()
        self.repo.create_table()
        self.security_id = self._create_test_security()
        
        # Create purchases at different prices
        # Purchase 1: Cheapest
        self.purchase1_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 1, 15).timestamp()), 100.0, 50.0, TradeType.BUY
        )
        # Purchase 2: Medium price
        self.purchase2_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 3, 20).timestamp()), 150.0, 40.0, TradeType.BUY
        )
        # Purchase 3: Most expensive
        self.purchase3_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 6, 10).timestamp()), 200.0, 60.0, TradeType.BUY
        )
        
        # Create sale
        self.sale_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 11, 15).timestamp()), 180.0, 100.0, TradeType.SELL
        )
    
    def test_maxlose_simple_full_match(self):
        """Test MaxLose with exact match of most expensive lot."""
        small_sale_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 11, 15).timestamp()), 180.0, 60.0, TradeType.SELL
        )
        
        result = self.repo.apply_max_lose(small_sale_id)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['pairings_created'], 1)
        self.assertEqual(result['total_quantity_paired'], 60.0)
        
        pairings = self.repo.get_pairings_for_sale(small_sale_id)
        self.assertEqual(len(pairings), 1)
        self.assertEqual(pairings[0]['purchase_trade_id'], self.purchase3_id)  # Most expensive
        self.assertEqual(pairings[0]['method'], 'MaxLose')
    
    def test_maxlose_multiple_purchases(self):
        """Test MaxLose spanning multiple purchases (highest price first)."""
        result = self.repo.apply_max_lose(self.sale_id)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['pairings_created'], 2)
        self.assertEqual(result['total_quantity_paired'], 100.0)
        
        pairings = self.repo.get_pairings_for_sale(self.sale_id)
        
        # MaxLose: P3($200, 60) + P2($150, 40) = 100
        self.assertEqual(pairings[0]['purchase_trade_id'], self.purchase3_id)
        self.assertEqual(pairings[0]['quantity'], 60.0)
        
        self.assertEqual(pairings[1]['purchase_trade_id'], self.purchase2_id)
        self.assertEqual(pairings[1]['quantity'], 40.0)
    
    def test_maxlose_minimizes_gain(self):
        """Test that MaxLose minimizes gain by using expensive lots."""
        result = self.repo.apply_max_lose(self.sale_id)
        pairings = self.repo.get_pairings_for_sale(self.sale_id)
        
        # MaxLose uses: 60*200 + 40*150 = 12,000 + 6,000 = 18,000
        cost_basis = sum(p['purchase_price'] * p['quantity'] for p in pairings)
        sale_proceeds = 180.0 * 100.0  # 18,000
        gain = sale_proceeds - cost_basis
        
        self.assertEqual(cost_basis, 18000.0)
        self.assertEqual(gain, 0.0)  # Break-even


class TestMaxProfitMethod(TestPairingsRepository):
    """Test MaxProfit (Lowest Cost First) pairing method."""
    
    def setUp(self):
        """Set up test data for MaxProfit testing."""
        super().setUp()
        self.repo.create_table()
        self.security_id = self._create_test_security()
        
        # Create purchases at different prices
        # Purchase 1: Cheapest (should be used first)
        self.purchase1_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 1, 15).timestamp()), 100.0, 50.0, TradeType.BUY
        )
        # Purchase 2: Medium price
        self.purchase2_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 3, 20).timestamp()), 150.0, 40.0, TradeType.BUY
        )
        # Purchase 3: Most expensive
        self.purchase3_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 6, 10).timestamp()), 200.0, 60.0, TradeType.BUY
        )
        
        # Create sale
        self.sale_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 11, 15).timestamp()), 180.0, 100.0, TradeType.SELL
        )
    
    def test_maxprofit_simple_full_match(self):
        """Test MaxProfit with exact match of cheapest lot."""
        small_sale_id = self._create_test_trade(
            self.security_id, int(datetime(2024, 11, 15).timestamp()), 180.0, 50.0, TradeType.SELL
        )
        
        result = self.repo.apply_max_profit(small_sale_id)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['pairings_created'], 1)
        self.assertEqual(result['total_quantity_paired'], 50.0)
        
        pairings = self.repo.get_pairings_for_sale(small_sale_id)
        self.assertEqual(len(pairings), 1)
        self.assertEqual(pairings[0]['purchase_trade_id'], self.purchase1_id)  # Cheapest
        self.assertEqual(pairings[0]['method'], 'MaxProfit')
    
    def test_maxprofit_multiple_purchases(self):
        """Test MaxProfit spanning multiple purchases (lowest price first)."""
        result = self.repo.apply_max_profit(self.sale_id)
        
        self.assertTrue(result['success'])
        self.assertEqual(result['pairings_created'], 3)
        self.assertEqual(result['total_quantity_paired'], 100.0)
        
        pairings = self.repo.get_pairings_for_sale(self.sale_id)
        
        # MaxProfit: P1($100, 50) + P2($150, 40) + P3($200, 10) = 100
        self.assertEqual(pairings[0]['purchase_trade_id'], self.purchase1_id)
        self.assertEqual(pairings[0]['quantity'], 50.0)
        
        self.assertEqual(pairings[1]['purchase_trade_id'], self.purchase2_id)
        self.assertEqual(pairings[1]['quantity'], 40.0)
        
        self.assertEqual(pairings[2]['purchase_trade_id'], self.purchase3_id)
        self.assertEqual(pairings[2]['quantity'], 10.0)
    
    def test_maxprofit_maximizes_gain(self):
        """Test that MaxProfit maximizes gain by using cheap lots."""
        result = self.repo.apply_max_profit(self.sale_id)
        pairings = self.repo.get_pairings_for_sale(self.sale_id)
        
        # MaxProfit uses: 50*100 + 40*150 + 10*200 = 5,000 + 6,000 + 2,000 = 13,000
        cost_basis = sum(p['purchase_price'] * p['quantity'] for p in pairings)
        sale_proceeds = 180.0 * 100.0  # 18,000
        gain = sale_proceeds - cost_basis
        
        self.assertEqual(cost_basis, 13000.0)
        self.assertEqual(gain, 5000.0)


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
    suite.addTests(loader.loadTestsFromTestCase(TestLotAvailability))
    suite.addTests(loader.loadTestsFromTestCase(TestMethodCombinations))
    suite.addTests(loader.loadTestsFromTestCase(TestFIFOMethod))
    suite.addTests(loader.loadTestsFromTestCase(TestRemainingQuantityTracking))
    suite.addTests(loader.loadTestsFromTestCase(TestLIFOMethod))
    suite.addTests(loader.loadTestsFromTestCase(TestMaxLoseMethod))
    suite.addTests(loader.loadTestsFromTestCase(TestMaxProfitMethod))
    
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
