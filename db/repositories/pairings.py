from datetime import datetime
from typing import List, Dict, Optional, Tuple
import sqlite3
from ..base import BaseRepository
from .trades import TradeType, TradesRepository


class PairingsRepository(BaseRepository):
    """Repository for managing trade pairings between purchases and sales.
    
    This repository handles the pairing of sale transactions with specific purchase lots
    for optimized tax reporting using various matching methods (FIFO, LIFO, MaxLose, MaxProfit).
    """

    def __init__(self, conn=None, logger=None):
        """Initialize the PairingsRepository.
        
        Args:
            conn: Optional database connection
            logger: Optional logger instance
        """
        super().__init__(conn, logger)
        self.trades_repo = TradesRepository(conn, logger)

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
        
        # Update remaining_quantity for both purchase and sale trades
        self.trades_repo.update_remaining_quantity(purchase_trade_id, -quantity)
        self.trades_repo.update_remaining_quantity(sale_trade_id, -quantity)
        
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
        # Get pairing details before deletion
        get_pairing_sql = "SELECT locked, quantity, sale_trade_id, purchase_trade_id FROM pairings WHERE id = ?"
        cur = self.execute(get_pairing_sql, (pairing_id,))
        row = cur.fetchone()
        
        if not row:
            self.logger.warning(f"Pairing {pairing_id} not found")
            return False
        
        locked, quantity, sale_trade_id, purchase_trade_id = row
        
        if locked:  # locked = 1
            self.logger.warning(f"Cannot delete locked pairing {pairing_id}")
            return False
        
        # Delete the pairing
        delete_sql = "DELETE FROM pairings WHERE id = ?"
        self.execute(delete_sql, (pairing_id,))
        
        # Restore remaining_quantity for both trades
        self.trades_repo.update_remaining_quantity(purchase_trade_id, quantity)
        self.trades_repo.update_remaining_quantity(sale_trade_id, quantity)
        
        self.commit()
        self.logger.info(f"Deleted pairing {pairing_id}, restored {quantity} to trades")
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

    def derive_method_combination(self, sale_trade_id: int) -> str:
        """Derive the effective method combination used for a sale.
        
        Analyzes all pairings for a sale and determines the method combination string.
        For example:
        - "FIFO" - if only one method used, no TimeTest
        - "MaxProfit+TT → MaxLose" - if TimeTest filter applied with fallback
        - "MaxProfit" - if all lots are time-qualified (implicit TimeTest)
        
        Args:
            sale_trade_id: ID of the sale transaction
            
        Returns:
            Method combination string (e.g., "FIFO", "MaxProfit+TT → MaxLose")
        """
        # Get all pairings for this sale
        sql = """
            SELECT method, time_test_qualified, quantity
            FROM pairings
            WHERE sale_trade_id = ?
            ORDER BY id
        """
        cur = self.execute(sql, (sale_trade_id,))
        pairings = cur.fetchall()
        
        if not pairings:
            return "No pairings"
        
        # Group by time test status
        time_qualified_pairings = []
        non_qualified_pairings = []
        
        for method, time_qualified, quantity in pairings:
            if time_qualified:
                time_qualified_pairings.append((method, quantity))
            else:
                non_qualified_pairings.append((method, quantity))
        
        # Case 1: All pairings are from one method, no TimeTest split
        if len(time_qualified_pairings) == 0:
            # No time-qualified lots used
            methods = list(set(p[0] for p in non_qualified_pairings))
            if len(methods) == 1:
                return methods[0]
            else:
                return "Mixed: " + ", ".join(sorted(methods))
        
        if len(non_qualified_pairings) == 0:
            # All lots are time-qualified (implicit TimeTest success)
            methods = list(set(p[0] for p in time_qualified_pairings))
            if len(methods) == 1:
                return methods[0]  # Could add "+TT (all)" suffix if desired
            else:
                return "Mixed: " + ", ".join(sorted(methods))
        
        # Case 2: TimeTest combination - both qualified and non-qualified lots used
        tt_methods = list(set(p[0] for p in time_qualified_pairings))
        fallback_methods = list(set(p[0] for p in non_qualified_pairings))
        
        primary = tt_methods[0] if len(tt_methods) == 1 else "Mixed(" + ",".join(sorted(tt_methods)) + ")"
        fallback = fallback_methods[0] if len(fallback_methods) == 1 else "Mixed(" + ",".join(sorted(fallback_methods)) + ")"
        
        return f"{primary}+TT → {fallback}"

    def get_method_breakdown(self, sale_trade_id: int) -> Dict:
        """Get detailed breakdown of methods used for a sale.
        
        Args:
            sale_trade_id: ID of the sale transaction
            
        Returns:
            Dictionary with method breakdown:
            {
                'combination': 'MaxProfit+TT → MaxLose',
                'time_qualified': {
                    'quantity': 70.0,
                    'methods': {'MaxProfit': 70.0}
                },
                'non_qualified': {
                    'quantity': 30.0,
                    'methods': {'MaxLose': 30.0}
                },
                'total_quantity': 100.0
            }
        """
        sql = """
            SELECT method, time_test_qualified, SUM(quantity) as qty
            FROM pairings
            WHERE sale_trade_id = ?
            GROUP BY method, time_test_qualified
        """
        cur = self.execute(sql, (sale_trade_id,))
        rows = cur.fetchall()
        
        time_qualified_methods = {}
        non_qualified_methods = {}
        time_qualified_qty = 0.0
        non_qualified_qty = 0.0
        
        for method, time_qualified, qty in rows:
            if time_qualified:
                time_qualified_methods[method] = qty
                time_qualified_qty += qty
            else:
                non_qualified_methods[method] = qty
                non_qualified_qty += qty
        
        return {
            'combination': self.derive_method_combination(sale_trade_id),
            'time_qualified': {
                'quantity': time_qualified_qty,
                'methods': time_qualified_methods
            },
            'non_qualified': {
                'quantity': non_qualified_qty,
                'methods': non_qualified_methods
            },
            'total_quantity': time_qualified_qty + non_qualified_qty
        }

    def is_timetest_applied(self, sale_trade_id: int) -> bool:
        """Check if TimeTest filter was applied to a sale.
        
        Returns True if the sale has both time-qualified and non-qualified pairings,
        indicating a TimeTest filter with fallback was used.
        
        Args:
            sale_trade_id: ID of the sale transaction
            
        Returns:
            True if TimeTest filter was applied (has both qualified and non-qualified lots)
        """
        sql = """
            SELECT 
                SUM(CASE WHEN time_test_qualified = 1 THEN 1 ELSE 0 END) as qualified_count,
                SUM(CASE WHEN time_test_qualified = 0 THEN 1 ELSE 0 END) as non_qualified_count
            FROM pairings
            WHERE sale_trade_id = ?
        """
        cur = self.execute(sql, (sale_trade_id,))
        row = cur.fetchone()
        
        if not row:
            return False
        
        qualified_count, non_qualified_count = row
        
        # Handle None values (when no pairings exist)
        if qualified_count is None or non_qualified_count is None:
            return False
        
        # TimeTest filter applied if we have both types
        return qualified_count > 0 and non_qualified_count > 0

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
        
        Returns purchase trades with their remaining available quantities.
        
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
        # Use remaining_quantity directly from trades table (much faster!)
        sql = """
            SELECT t.id, t.timestamp, t.price_for_share, t.number_of_shares, t.remaining_quantity
            FROM trades t
            WHERE t.isin_id = ?
            AND t.trade_type = ?
            AND t.timestamp < ?
            ORDER BY t.timestamp
        """
        cur = self.execute(sql, (security_id, TradeType.BUY, sale_timestamp))
        purchases = cur.fetchall()
        
        # Build result list
        result = []
        for purchase in purchases:
            purchase_id, timestamp, price, original_qty, remaining_qty = purchase
            
            paired_qty = original_qty - remaining_qty
            
            # Calculate holding period and time test
            holding_days = self.calculate_holding_period(timestamp, sale_timestamp)
            time_qualified = self.check_time_test(timestamp, sale_timestamp)
            
            result.append({
                'id': purchase_id,
                'timestamp': timestamp,
                'price_for_share': price,
                'quantity': original_qty,
                'paired_quantity': paired_qty,
                'available_quantity': remaining_qty,
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
        # Simply read remaining_quantity from trades table
        trade_sql = "SELECT remaining_quantity FROM trades WHERE id = ?"
        cur = self.execute(trade_sql, (purchase_trade_id,))
        row = cur.fetchone()
        
        if not row:
            self.logger.warning(f"Purchase trade {purchase_trade_id} not found")
            return 0.0
        
        return row[0]

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

    def _get_next_available_lot(self, security_id: int, sale_timestamp: int, order_by: str, time_test_only: bool = False) -> Optional[Dict]:
        """Get the next available purchase lot based on method criteria.
        
        Args:
            security_id: ID of the security
            sale_timestamp: Timestamp of the sale
            order_by: SQL ORDER BY clause (e.g., 't.timestamp ASC', 't.price_for_share DESC')
            time_test_only: If True, only return lots that meet 3-year time test
            
        Returns:
            Dictionary with lot info or None if no lots available
        """
        # Calculate 3-year threshold if time test required
        time_test_threshold = 0
        if time_test_only:
            # 3 years in seconds (accounting for leap years, approximately)
            three_years_seconds = 3 * 365.25 * 24 * 3600
            time_test_threshold = sale_timestamp - int(three_years_seconds)
        
        sql = f"""
            SELECT t.id, t.timestamp, t.price_for_share, t.remaining_quantity
            FROM trades t
            WHERE t.isin_id = ?
            AND t.trade_type = ?
            AND t.timestamp < ?
            AND t.remaining_quantity > 0
            {'AND t.timestamp < ?' if time_test_only else ''}
            ORDER BY {order_by}
            LIMIT 1
        """
        
        params = (security_id, TradeType.BUY, sale_timestamp)
        if time_test_only:
            params = params + (time_test_threshold,)
        
        cur = self.execute(sql, params)
        row = cur.fetchone()
        
        if not row:
            return None
        
        lot_id, timestamp, price, remaining_qty = row
        
        # Calculate holding period and time test qualification
        holding_days = self.calculate_holding_period(timestamp, sale_timestamp)
        time_qualified = self.check_time_test(timestamp, sale_timestamp)
        
        return {
            'id': lot_id,
            'timestamp': timestamp,
            'price_for_share': price,
            'available_quantity': remaining_qty,
            'holding_period_days': holding_days,
            'time_test_qualified': time_qualified
        }

    def _apply_pairing_method(self, sale_trade_id: int, method: str, order_by: str, time_test_only: bool = False) -> Dict:
        """Apply a pairing method using the common algorithm.
        
        This is the core pairing algorithm used by all methods (FIFO, LIFO, MaxLose, MaxProfit).
        The only difference between methods is the ORDER BY clause and optional time test filter.
        
        Algorithm:
        0) Get sale_trade.remaining_quantity
        1) Search for next BUY trade using method-specific query
        2) quantity_pairing = min(sale_trade.remaining_quantity, buy_trade.remaining_quantity)
        3) Create pairing (automatically updates remaining_quantity for both trades)
        4) Repeat until sale_trade.remaining_quantity <= 0
        
        Args:
            sale_trade_id: ID of the sale trade to pair
            method: Pairing method name ('FIFO', 'LIFO', 'MaxLose', 'MaxProfit')
            order_by: SQL ORDER BY clause for lot selection
            time_test_only: If True, only use lots that meet 3-year time test
            
        Returns:
            Dictionary with pairing results
        """
        # Get sale transaction details
        sale_sql = """
            SELECT t.id, t.isin_id, t.number_of_shares, t.timestamp, t.trade_type, t.remaining_quantity
            FROM trades t
            WHERE t.id = ?
        """
        cur = self.execute(sale_sql, (sale_trade_id,))
        sale = cur.fetchone()
        
        if not sale:
            raise ValueError(f"Sale trade {sale_trade_id} not found")
        
        sale_id, security_id, sale_qty, sale_timestamp, trade_type, remaining_to_pair = sale
        
        if trade_type != TradeType.SELL:
            raise ValueError(f"Trade {sale_trade_id} is not a SELL transaction")
        
        # Check remaining unpaired quantity
        if remaining_to_pair <= 0:
            return {
                'success': True,
                'pairings_created': 0,
                'total_quantity_paired': 0.0,
                'error': f"Sale {sale_trade_id} is already fully paired"
            }
        
        # Apply pairing algorithm: loop until sale is fully paired
        pairings_created = 0
        total_paired = 0.0
        
        while remaining_to_pair > 0:
            # Step 1: Get next available lot based on method
            lot = self._get_next_available_lot(security_id, sale_timestamp, order_by, time_test_only)
            
            if not lot:
                # No more lots available
                if pairings_created == 0:
                    # No lots found at all
                    error_msg = f"No available purchase lots found for security {security_id} before {sale_timestamp}"
                else:
                    # Some lots paired, but not enough
                    error_msg = f"Insufficient quantity: need {remaining_to_pair} more, but no lots available"
                
                return {
                    'success': False,
                    'pairings_created': pairings_created,
                    'total_quantity_paired': total_paired,
                    'error': error_msg
                }
            
            # Step 2: Calculate quantity to pair from this lot
            quantity_to_pair = min(remaining_to_pair, lot['available_quantity'])
            
            # Step 3: Create pairing (this updates remaining_quantity in database)
            pairing_id = self.create_pairing(
                sale_trade_id=sale_trade_id,
                purchase_trade_id=lot['id'],
                quantity=quantity_to_pair,
                method=method,
                time_test_qualified=lot['time_test_qualified'],
                holding_period_days=lot['holding_period_days']
            )
            
            # Step 4: Read updated remaining_quantity from database
            pairings_created += 1
            total_paired += quantity_to_pair
            remaining_to_pair = self.trades_repo.get_remaining_quantity(sale_trade_id)
            
            self.logger.debug(f"{method} pairing: sale={sale_trade_id}, purchase={lot['id']}, "
                            f"qty={quantity_to_pair}, holding_days={lot['holding_period_days']}, "
                            f"time_qualified={lot['time_test_qualified']}")
        
        self.logger.info(f"{method} method applied to sale {sale_trade_id}: "
                        f"{pairings_created} pairings created, {total_paired} shares paired")
        
        return {
            'success': True,
            'pairings_created': pairings_created,
            'total_quantity_paired': total_paired,
            'error': None
        }

    def apply_fifo(self, sale_trade_id: int) -> Dict:
        """Apply FIFO (First-In-First-Out) method to pair a sale with purchases.
        
        FIFO matches the oldest available purchase lots first. This is a common
        default method in many jurisdictions.
        
        Note: If the sale already has pairings, this method will only pair the
        remaining unpaired quantity. To replace existing pairings, delete them
        first using delete_pairing() before calling this method.
        
        Args:
            sale_trade_id: ID of the sale trade to pair
            
        Returns:
            Dictionary with pairing results:
            {
                'success': bool,
                'pairings_created': int,
                'total_quantity_paired': float,
                'error': Optional[str]
            }
            
        Raises:
            ValueError: If sale trade doesn't exist or isn't a SELL transaction
        """
        return self._apply_pairing_method(sale_trade_id, 'FIFO', 't.timestamp ASC')
