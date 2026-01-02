from datetime import datetime
from typing import List, Dict, Optional, Tuple
import sqlite3
from ..base import BaseRepository
from .trades import TradeType


class PairingsRepository(BaseRepository):
    """Repository for managing trade pairings between purchases and sales.
    
    This repository handles the pairing of sale transactions with specific purchase lots
    for optimized tax reporting using various matching methods (FIFO, LIFO, MaxLose, MaxProfit).
    """

    def create_table(self) -> None:
        """Create the pairings table with indexes."""
        sql = (
            "CREATE TABLE IF NOT EXISTS pairings ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "sale_trade_id INTEGER NOT NULL, "
            "purchase_trade_id INTEGER NOT NULL, "
            "quantity REAL NOT NULL, "
            "method TEXT NOT NULL, "  # 'FIFO', 'LIFO', 'MaxLose', 'MaxProfit', 'Manual'
            "time_test_qualified BOOLEAN DEFAULT 0, "  # Whether this pairing meets 3-year time test
            "holding_period_days INTEGER, "  # Calculated holding period in days
            "locked BOOLEAN DEFAULT 0, "  # Lock pairs used in tax returns
            "locked_reason TEXT, "  # Why locked (e.g., "Tax Return 2024")
            "notes TEXT, "
            "FOREIGN KEY (sale_trade_id) REFERENCES trades(id) ON DELETE RESTRICT, "
            "FOREIGN KEY (purchase_trade_id) REFERENCES trades(id) ON DELETE RESTRICT"
            ")"
        )
        cur = self.execute(sql)
        
        # Create indexes for common queries
        cur.execute("CREATE INDEX IF NOT EXISTS idx_pairings_sale ON pairings(sale_trade_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_pairings_purchase ON pairings(purchase_trade_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_pairings_time_test ON pairings(time_test_qualified)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_pairings_method ON pairings(method)")
        
        self.commit()
        self.logger.info("Pairings table created successfully")

    def create_pairing(self, 
                       sale_trade_id: int, 
                       purchase_trade_id: int, 
                       quantity: float, 
                       method: str, 
                       time_test_qualified: bool = False,
                       holding_period_days: Optional[int] = None,
                       notes: Optional[str] = None) -> int:
        """Create a new pairing between a sale and purchase.
        
        Args:
            sale_trade_id: ID of the sale transaction
            purchase_trade_id: ID of the purchase transaction
            quantity: Quantity of shares/units being paired
            method: Pairing method used ('FIFO', 'LIFO', 'MaxLose', 'MaxProfit', 'Manual')
            time_test_qualified: Whether this pairing meets 3-year time test (Czech tax exemption)
            holding_period_days: Number of days between purchase and sale
            notes: Optional notes about this pairing
            
        Returns:
            The ID of the newly created pairing record
            
        Raises:
            ValueError: If required parameters are invalid
        """
        if quantity <= 0:
            raise ValueError("Quantity must be positive")
        if method not in ('FIFO', 'LIFO', 'MaxLose', 'MaxProfit', 'Manual'):
            raise ValueError(f"Invalid method: {method}")
        
        sql = (
            "INSERT INTO pairings "
            "(sale_trade_id, purchase_trade_id, quantity, method, "
            "time_test_qualified, holding_period_days, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)"
        )
        cur = self.execute(sql, (
            sale_trade_id, 
            purchase_trade_id, 
            quantity, 
            method,
            int(time_test_qualified),
            holding_period_days,
            notes
        ))
        self.commit()
        self.logger.info(f"Created pairing: sale_id={sale_trade_id}, purchase_id={purchase_trade_id}, "
                        f"quantity={quantity}, method={method}, time_test={time_test_qualified}")
        return cur.lastrowid

    def get_pairings_for_sale(self, sale_trade_id: int) -> List[Dict]:
        """Get all pairings for a specific sale transaction.
        
        Args:
            sale_trade_id: ID of the sale transaction
            
        Returns:
            List of pairing dictionaries with full details
        """
        sql = (
            "SELECT p.*, "
            "pt.timestamp as purchase_timestamp, pt.price_for_share as purchase_price, "
            "st.timestamp as sale_timestamp, st.price_for_share as sale_price "
            "FROM pairings p "
            "JOIN trades pt ON p.purchase_trade_id = pt.id "
            "JOIN trades st ON p.sale_trade_id = st.id "
            "WHERE p.sale_trade_id = ? "
            "ORDER BY p.id"
        )
        cur = self.execute(sql, (sale_trade_id,))
        rows = cur.fetchall()
        
        # Convert to list of dictionaries
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in rows]

    def get_pairings_for_purchase(self, purchase_trade_id: int) -> List[Dict]:
        """Get all pairings using a specific purchase lot.
        
        Args:
            purchase_trade_id: ID of the purchase transaction
            
        Returns:
            List of pairing dictionaries
        """
        sql = (
            "SELECT p.*, "
            "st.timestamp as sale_timestamp, st.price_for_share as sale_price "
            "FROM pairings p "
            "JOIN trades st ON p.sale_trade_id = st.id "
            "WHERE p.purchase_trade_id = ? "
            "ORDER BY p.id"
        )
        cur = self.execute(sql, (purchase_trade_id,))
        rows = cur.fetchall()
        
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in rows]

    def delete_pairing(self, pairing_id: int) -> bool:
        """Delete a specific pairing (only if not locked).
        
        Args:
            pairing_id: ID of the pairing to delete
            
        Returns:
            True if pairing was deleted, False if it was locked or didn't exist
        """
        # Check if pairing is locked
        check_sql = "SELECT locked FROM pairings WHERE id = ?"
        cur = self.execute(check_sql, (pairing_id,))
        row = cur.fetchone()
        
        if not row:
            self.logger.warning(f"Pairing {pairing_id} not found")
            return False
        
        if row[0]:  # locked = 1
            self.logger.warning(f"Cannot delete locked pairing {pairing_id}")
            return False
        
        # Delete the pairing
        delete_sql = "DELETE FROM pairings WHERE id = ?"
        self.execute(delete_sql, (pairing_id,))
        self.commit()
        self.logger.info(f"Deleted pairing {pairing_id}")
        return True

    def lock_pairing(self, pairing_id: int, reason: str) -> bool:
        """Lock a pairing to prevent modification (e.g., after tax filing).
        
        Args:
            pairing_id: ID of the pairing to lock
            reason: Reason for locking (e.g., "Tax Return 2024")
            
        Returns:
            True if successfully locked, False if pairing doesn't exist
        """
        sql = "UPDATE pairings SET locked = 1, locked_reason = ? WHERE id = ?"
        cur = self.execute(sql, (reason, pairing_id))
        self.commit()
        
        if cur.rowcount > 0:
            self.logger.info(f"Locked pairing {pairing_id}: {reason}")
            return True
        else:
            self.logger.warning(f"Pairing {pairing_id} not found")
            return False

    def unlock_pairing(self, pairing_id: int) -> bool:
        """Unlock a pairing to allow modification.
        
        Args:
            pairing_id: ID of the pairing to unlock
            
        Returns:
            True if successfully unlocked, False if pairing doesn't exist
        """
        sql = "UPDATE pairings SET locked = 0, locked_reason = NULL WHERE id = ?"
        cur = self.execute(sql, (pairing_id,))
        self.commit()
        
        if cur.rowcount > 0:
            self.logger.info(f"Unlocked pairing {pairing_id}")
            return True
        else:
            self.logger.warning(f"Pairing {pairing_id} not found")
            return False

    def lock_pairings_by_year(self, year: int, reason: str) -> int:
        """Lock all pairings for a specific tax year.
        
        Args:
            year: Tax year (e.g., 2024)
            reason: Reason for locking (e.g., "Tax Return 2024 Filed")
            
        Returns:
            Number of pairings locked
        """
        # Calculate timestamp range for the year
        start_timestamp = int(datetime(year, 1, 1).timestamp())
        end_timestamp = int(datetime(year, 12, 31, 23, 59, 59).timestamp())
        
        sql = (
            "UPDATE pairings "
            "SET locked = 1, locked_reason = ? "
            "WHERE sale_trade_id IN ("
            "  SELECT id FROM trades "
            "  WHERE timestamp >= ? AND timestamp <= ?"
            ") AND locked = 0"
        )
        cur = self.execute(sql, (reason, start_timestamp, end_timestamp))
        self.commit()
        
        count = cur.rowcount
        self.logger.info(f"Locked {count} pairings for year {year}: {reason}")
        return count

    def is_pairing_locked(self, pairing_id: int) -> bool:
        """Check if a pairing is locked.
        
        Args:
            pairing_id: ID of the pairing to check
            
        Returns:
            True if locked, False otherwise
        """
        sql = "SELECT locked FROM pairings WHERE id = ?"
        cur = self.execute(sql, (pairing_id,))
        row = cur.fetchone()
        return bool(row[0]) if row else False

    def get_pairing_summary(self, year: int) -> List[Dict]:
        """Get summary of all pairings for a tax year.
        
        Returns summary including derived method combinations based on:
        - Grouping pairings by sale_trade_id
        - Identifying which pairings have time_test_qualified=True
        - Determining effective method combination (e.g., "MaxProfit+TT → MaxLose")
        
        Args:
            year: Tax year to summarize
            
        Returns:
            List of summary dictionaries, one per sale transaction with pairings
        """
        start_timestamp = int(datetime(year, 1, 1).timestamp())
        end_timestamp = int(datetime(year, 12, 31, 23, 59, 59).timestamp())
        
        sql = (
            "SELECT "
            "p.sale_trade_id, "
            "st.timestamp as sale_timestamp, "
            "s.isin, s.ticker, s.name, "
            "SUM(p.quantity) as total_quantity, "
            "COUNT(p.id) as pairing_count, "
            "SUM(CASE WHEN p.time_test_qualified = 1 THEN p.quantity ELSE 0 END) as time_qualified_quantity, "
            "GROUP_CONCAT(DISTINCT p.method) as methods_used, "
            "MAX(p.locked) as is_locked "
            "FROM pairings p "
            "JOIN trades st ON p.sale_trade_id = st.id "
            "JOIN securities s ON st.isin_id = s.id "
            "WHERE st.timestamp >= ? AND st.timestamp <= ? "
            "GROUP BY p.sale_trade_id "
            "ORDER BY st.timestamp"
        )
        cur = self.execute(sql, (start_timestamp, end_timestamp))
        rows = cur.fetchall()
        
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in rows]

    def calculate_holding_period(self, purchase_date: str, sale_date: str) -> int:
        """Calculate holding period in days between purchase and sale.
        
        Args:
            purchase_date: Purchase date as ISO string or timestamp
            sale_date: Sale date as ISO string or timestamp
            
        Returns:
            Number of days between purchase and sale
        """
        try:
            # Try parsing as timestamp first
            purchase_ts = int(purchase_date) if isinstance(purchase_date, (int, float)) else int(datetime.fromisoformat(purchase_date).timestamp())
            sale_ts = int(sale_date) if isinstance(sale_date, (int, float)) else int(datetime.fromisoformat(sale_date).timestamp())
            
            days = (sale_ts - purchase_ts) / (24 * 3600)
            return int(days)
        except (ValueError, TypeError) as e:
            self.logger.error(f"Error calculating holding period: {e}")
            return 0

    def check_time_test(self, purchase_date: str, sale_date: str) -> bool:
        """Check if a purchase-sale pair meets 3-year time test (Czech tax exemption).
        
        The test is based on calendar dates, not a fixed number of days. 
        For example, shares purchased on Jan 15, 2020 qualify on Jan 16, 2023 (after 3 full years).
        
        Args:
            purchase_date: Purchase date as ISO string or timestamp
            sale_date: Sale date as ISO string or timestamp
            
        Returns:
            True if holding period exceeds 3 years (calendar-based)
        """
        try:
            # Convert to datetime objects
            if isinstance(purchase_date, (int, float)):
                purchase_dt = datetime.fromtimestamp(purchase_date)
            else:
                purchase_dt = datetime.fromisoformat(str(purchase_date))
            
            if isinstance(sale_date, (int, float)):
                sale_dt = datetime.fromtimestamp(sale_date)
            else:
                sale_dt = datetime.fromisoformat(str(sale_date))
            
            # Calculate the date exactly 3 years after purchase
            # Handle Feb 29 leap year edge case
            try:
                three_years_later = purchase_dt.replace(year=purchase_dt.year + 3)
            except ValueError:
                # Feb 29 in a leap year -> Feb 28 three years later if not a leap year
                three_years_later = purchase_dt.replace(year=purchase_dt.year + 3, day=28)
            
            # Qualify if sale is AFTER the 3-year anniversary (not on the same day)
            return sale_dt > three_years_later
            
        except (ValueError, TypeError) as e:
            self.logger.error(f"Error checking time test: {e}")
            return False

    def get_available_lots(self, security_id: int, sale_timestamp: int) -> List[Dict]:
        """Get all available purchase lots for a security that can be paired with a sale.
        
        Returns purchase trades with their remaining available quantities after accounting
        for quantities already used in other pairings.
        
        Args:
            security_id: ID of the security
            sale_timestamp: Timestamp of the sale (only purchases before this are available)
            
        Returns:
            List of dictionaries with purchase trade info and available quantities:
            {
                'id': trade_id,
                'timestamp': purchase_timestamp,
                'price_for_share': price,
                'quantity': original_quantity,
                'paired_quantity': already_paired_quantity,
                'available_quantity': remaining_quantity,
                'holding_period_days': days_until_sale,
                'time_test_qualified': bool
            }
        """
        # Get all purchase trades for this security before the sale
        sql = """
            SELECT t.id, t.timestamp, t.price_for_share, t.number_of_shares
            FROM trades t
            WHERE t.isin_id = ?
            AND t.trade_type = ?
            AND t.timestamp < ?
            ORDER BY t.timestamp
        """
        cur = self.execute(sql, (security_id, TradeType.BUY, sale_timestamp))
        purchases = cur.fetchall()
        
        # Calculate paired quantities for each purchase
        result = []
        for purchase in purchases:
            purchase_id, timestamp, price, original_qty = purchase
            
            # Get total quantity already paired from this purchase
            paired_sql = """
                SELECT COALESCE(SUM(quantity), 0)
                FROM pairings
                WHERE purchase_trade_id = ?
            """
            paired_cur = self.execute(paired_sql, (purchase_id,))
            paired_qty = paired_cur.fetchone()[0]
            
            available_qty = original_qty - paired_qty
            
            # Calculate holding period and time test
            holding_days = self.calculate_holding_period(timestamp, sale_timestamp)
            time_qualified = self.check_time_test(timestamp, sale_timestamp)
            
            result.append({
                'id': purchase_id,
                'timestamp': timestamp,
                'price_for_share': price,
                'quantity': original_qty,
                'paired_quantity': paired_qty,
                'available_quantity': available_qty,
                'holding_period_days': holding_days,
                'time_test_qualified': time_qualified
            })
        
        return result

    def calculate_available_quantity_for_purchase(self, purchase_trade_id: int) -> float:
        """Calculate remaining available quantity for a specific purchase lot.
        
        Args:
            purchase_trade_id: ID of the purchase trade
            
        Returns:
            Remaining quantity available for pairing
        """
        # Get original quantity
        trade_sql = "SELECT number_of_shares FROM trades WHERE id = ?"
        cur = self.execute(trade_sql, (purchase_trade_id,))
        row = cur.fetchone()
        
        if not row:
            self.logger.warning(f"Purchase trade {purchase_trade_id} not found")
            return 0.0
        
        original_qty = row[0]
        
        # Get paired quantity
        paired_sql = "SELECT COALESCE(SUM(quantity), 0) FROM pairings WHERE purchase_trade_id = ?"
        paired_cur = self.execute(paired_sql, (purchase_trade_id,))
        paired_qty = paired_cur.fetchone()[0]
        
        return original_qty - paired_qty

    def validate_pairing_availability(self, purchase_trade_id: int, requested_quantity: float) -> Tuple[bool, str]:
        """Validate that sufficient quantity is available for a pairing.
        
        Args:
            purchase_trade_id: ID of the purchase trade
            requested_quantity: Quantity to pair
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        available = self.calculate_available_quantity_for_purchase(purchase_trade_id)
        
        if requested_quantity <= 0:
            return False, "Requested quantity must be positive"
        
        if available <= 0:
            return False, f"Purchase lot {purchase_trade_id} is fully paired (no quantity available)"
        
        if requested_quantity > available:
            return False, f"Insufficient quantity: {available} available, {requested_quantity} requested"
        
        return True, ""
