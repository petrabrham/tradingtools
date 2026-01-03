"""
Unit tests for TradesRepository.get_by_id method.
"""

import unittest
import sqlite3
import os
import sys
from unittest.mock import Mock

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from db.repositories.trades import TradesRepository, TradeType


class TestTradesGetById(unittest.TestCase):
    """Test suite for TradesRepository.get_by_id method."""

    def setUp(self):
        """Set up test database and repository before each test."""
        # Create in-memory database for testing
        self.conn = sqlite3.connect(':memory:')
        self.conn.execute('PRAGMA foreign_keys = ON')
        
        # Create mock logger
        self.logger = Mock()
        
        # Initialize repository
        self.repo = TradesRepository(self.conn, self.logger)
        
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
        
        # Create the trades table using the repository
        self.repo.create_table()
        
        self.conn.commit()
        
    def _create_test_security(self, isin='US0378331005', ticker='AAPL', name='Apple Inc.'):
        """Helper to create a test security."""
        cur = self.conn.execute(
            "INSERT INTO securities (isin, ticker, name) VALUES (?, ?, ?)",
            (isin, ticker, name)
        )
        self.conn.commit()
        return cur.lastrowid

    def test_get_by_id_existing_trade(self):
        """Test retrieving an existing trade by ID."""
        # Create test security
        security_id = self._create_test_security()
        
        # Insert a trade
        trade_id = self.repo.insert(
            timestamp=1609459200,  # 2021-01-01
            isin_id=security_id,
            id_string="TEST001",
            trade_type=TradeType.BUY,
            number_of_shares=100.0,
            price_for_share=150.50,
            currency_of_price='USD',
            total_czk=15050.00,
            stamp_tax_czk=10.0,
            conversion_fee_czk=5.0,
            french_transaction_tax_czk=0.0
        )
        
        # Retrieve the trade
        trade = self.repo.get_by_id(trade_id)
        
        # Verify trade data
        self.assertIsNotNone(trade)
        self.assertEqual(trade[0], trade_id)  # id
        self.assertEqual(trade[1], 1609459200)  # timestamp
        self.assertEqual(trade[2], security_id)  # isin_id
        self.assertEqual(trade[3], "TEST001")  # id_string
        self.assertEqual(trade[4], TradeType.BUY)  # trade_type
        self.assertEqual(trade[5], 100.0)  # number_of_shares
        self.assertEqual(trade[6], 100.0)  # remaining_quantity (initially same as number_of_shares)
        self.assertEqual(trade[7], 150.50)  # price_for_share

    def test_get_by_id_nonexistent_trade(self):
        """Test retrieving a non-existent trade returns None."""
        trade = self.repo.get_by_id(99999)
        self.assertIsNone(trade)

    def test_get_by_id_after_pairing(self):
        """Test that get_by_id reflects updated remaining_quantity after pairing."""
        # Create test security
        security_id = self._create_test_security()
        
        # Insert a trade
        trade_id = self.repo.insert(
            timestamp=1609459200,
            isin_id=security_id,
            id_string="TEST002",
            trade_type=TradeType.BUY,
            number_of_shares=100.0,
            price_for_share=150.50,
            currency_of_price='USD',
            total_czk=15050.00
        )
        
        # Simulate pairing by updating remaining_quantity
        self.repo.update_remaining_quantity(trade_id, -30.0)
        
        # Retrieve the trade
        trade = self.repo.get_by_id(trade_id)
        
        # Verify remaining_quantity was updated
        self.assertIsNotNone(trade)
        self.assertEqual(trade[5], 100.0)  # original number_of_shares unchanged
        self.assertEqual(trade[6], 70.0)  # remaining_quantity decreased by 30


if __name__ == '__main__':
    unittest.main()
