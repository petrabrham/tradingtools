from datetime import datetime
from typing import List, Tuple, Optional
import sqlite3
from enum import IntEnum
from ..base import BaseRepository

class TradeType(IntEnum):
    """Types of trade entries in the database."""
    BUY = 1
    SELL = 2

class TradesRepository(BaseRepository):
    """Repository for the `trades` table operations."""

    def create_table(self) -> None:
        sql = (
            "CREATE TABLE IF NOT EXISTS trades ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "timestamp INTEGER NOT NULL, "
            "isin_id INTEGER NOT NULL, "
            "id_string TEXT NOT NULL UNIQUE, "
            "trade_type INTEGER NOT NULL, "
            "number_of_shares REAL NOT NULL, "
            "remaining_quantity REAL NOT NULL, "  # Tracks unpaired/unmatched quantity
            "price_for_share REAL NOT NULL, "
            "currency_of_price TEXT NOT NULL, "
            "total_czk REAL NOT NULL, "
            "stamp_tax_czk REAL DEFAULT 0, "
            "conversion_fee_czk REAL DEFAULT 0, "
            "french_transaction_tax_czk REAL DEFAULT 0, "
            "FOREIGN KEY (isin_id) REFERENCES securities(id) ON DELETE RESTRICT"
            ")"
        )
        cur = self.execute(sql)
        # Indexes for common queries
        cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_isin_id ON trades(isin_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_remaining ON trades(remaining_quantity)")
        self.commit()

    def insert(self,
               timestamp: int,
               isin_id: int,
               id_string: str,
               trade_type: TradeType,
               number_of_shares: float,
               price_for_share: float,
               currency_of_price: str,
               total_czk: float,
               stamp_tax_czk: float = 0.0,
               conversion_fee_czk: float = 0.0,
               french_transaction_tax_czk: float = 0.0) -> int:
        """Insert a single trade record and return the inserted row id."""
        if timestamp < 0:
            raise ValueError("timestamp must be a positive Unix timestamp")
        if not id_string:
            raise ValueError("id_string must be provided and non-empty")

        sql = (
            "INSERT OR IGNORE INTO trades (timestamp, isin_id, id_string, trade_type, number_of_shares, "
            "remaining_quantity, price_for_share, currency_of_price, total_czk, stamp_tax_czk, conversion_fee_czk, "
            "french_transaction_tax_czk) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
        cur = self.execute(sql, (
            timestamp, isin_id, id_string, int(trade_type), number_of_shares,
            number_of_shares,  # Initialize remaining_quantity to full amount
            price_for_share, currency_of_price, total_czk, stamp_tax_czk,
            conversion_fee_czk, french_transaction_tax_czk
        ))
        self.commit()
        return cur.lastrowid

    def update_remaining_quantity(self, trade_id: int, quantity_change: float) -> None:
        """Update the remaining_quantity for a trade.
        
        Args:
            trade_id: ID of the trade to update
            quantity_change: Amount to change (positive to add, negative to subtract)
        """
        sql = "UPDATE trades SET remaining_quantity = remaining_quantity + ? WHERE id = ?"
        self.execute(sql, (quantity_change, trade_id))

    def get_remaining_quantity(self, trade_id: int) -> float:
        """Get the current remaining_quantity for a trade.
        
        Args:
            trade_id: ID of the trade
            
        Returns:
            Current remaining quantity, or 0.0 if trade not found
        """
        sql = "SELECT remaining_quantity FROM trades WHERE id = ?"
        cur = self.execute(sql, (trade_id,))
        row = cur.fetchone()
        return row[0] if row else 0.0
    
    def get_by_id(self, trade_id: int) -> Optional[Tuple]:
        """Get a trade by its ID.
        
        Args:
            trade_id: ID of the trade to retrieve
            
        Returns:
            Trade record as tuple, or None if not found
        """
        sql = "SELECT * FROM trades WHERE id = ?"
        cur = self.execute(sql, (trade_id,))
        return cur.fetchone()


    def get_by_date_range(self, start_timestamp: int, end_timestamp: int) -> List[Tuple]:
        sql = (
            "SELECT t.*, s.isin, s.ticker, s.name "
            "FROM trades t "
            "JOIN securities s ON t.isin_id = s.id "
            "WHERE t.timestamp >= ? AND t.timestamp <= ? "
            "ORDER BY t.timestamp"
        )
        cur = self.execute(sql, (start_timestamp, end_timestamp))
        return cur.fetchall()

    def get_by_isin(self, isin_id: int) -> List[Tuple]:
        sql = (
            "SELECT t.*, s.isin, s.ticker, s.name "
            "FROM trades t "
            "JOIN securities s ON t.isin_id = s.id "
            "WHERE t.isin_id = ? "
            "ORDER BY t.timestamp"
        )
        cur = self.execute(sql, (isin_id,))
        return cur.fetchall()

    def get_by_isin_and_date_range(self, isin_id: int, start_timestamp: int, end_timestamp: int) -> List[Tuple]:
        """Get trades for a specific ISIN within a date range, ordered by time."""
        sql = (
            "SELECT t.*, s.isin, s.ticker, s.name "
            "FROM trades t "
            "JOIN securities s ON t.isin_id = s.id "
            "WHERE t.isin_id = ? AND t.timestamp >= ? AND t.timestamp <= ? "
            "ORDER BY t.timestamp"
        )
        cur = self.execute(sql, (isin_id, start_timestamp, end_timestamp))
        return cur.fetchall()

    def get_summary_grouped_by_isin(self, start_timestamp: int, end_timestamp: int) -> List[Tuple]:
        """Return summary rows grouped by ISIN with aggregated values for the date range.
        
        Returns tuple: (isin_id, name, ticker, total_shares, total_czk, stamp_tax_czk, 
                       conversion_fee_czk, french_transaction_tax_czk)
        """
        sql = (
            "SELECT s.id AS isin_id, s.name, s.ticker, "
            "COALESCE(SUM(t.number_of_shares), 0.0) AS total_shares, "
            "COALESCE(SUM(t.total_czk), 0.0) AS total_czk, "
            "COALESCE(SUM(t.stamp_tax_czk), 0.0) AS stamp_tax_czk, "
            "COALESCE(SUM(t.conversion_fee_czk), 0.0) AS conversion_fee_czk, "
            "COALESCE(SUM(t.french_transaction_tax_czk), 0.0) AS french_transaction_tax_czk "
            "FROM trades t "
            "JOIN securities s ON t.isin_id = s.id "
            "WHERE t.timestamp >= ? AND t.timestamp <= ? "
            "GROUP BY s.id, s.name, s.ticker "
            "ORDER BY s.name COLLATE NOCASE"
        )
        cur = self.execute(sql, (start_timestamp, end_timestamp))
        return cur.fetchall()

    def get_cumulative_totals_by_isin(self, isin_id: int, up_to_timestamp: int) -> Tuple[float, float]:
        """Return cumulative shares and total_czk for a specific ISIN up to a given timestamp.
        
        Returns tuple: (cumulative_shares, cumulative_total_czk)
        """
        sql = (
            "SELECT "
            "COALESCE(SUM(number_of_shares), 0.0) AS cumulative_shares, "
            "COALESCE(SUM(total_czk), 0.0) AS cumulative_total_czk "
            "FROM trades "
            "WHERE isin_id = ? AND timestamp <= ? "
        )
        cur = self.execute(sql, (isin_id, up_to_timestamp))
        result = cur.fetchone()
        return result if result else (0.0, 0.0)

    def calculate_realized_income(self, start_timestamp: int, end_timestamp: int) -> List[dict]:
        """
        Calculate realized income using FIFO (First In, First Out) method.
        Returns a list of dictionaries with realized P&L details for each security.
        
        Returns:
            List of dicts with keys: isin_id, name, ticker, realized_pnl, 
            total_buy_cost, total_sell_proceeds, shares_sold, unrealized_shares
        """
        # Get all ISINs that have trades
        sql_isins = (
            "SELECT DISTINCT s.id, s.name, s.ticker "
            "FROM trades t "
            "JOIN securities s ON t.isin_id = s.id "
            "WHERE t.trade_type = ? "
            "AND t.timestamp >= ? "
            "AND t.timestamp <= ? "
            "ORDER BY s.name COLLATE NOCASE"
        )
        cur = self.execute(sql_isins, (TradeType.SELL, start_timestamp, end_timestamp))
        isins = cur.fetchall()
        
        results = []
        
        for isin_row in isins:
            isin_id, name, ticker = isin_row
            
            # Get all trades for this ISIN, ordered by timestamp
            sql_trades = (
                "SELECT id, timestamp, trade_type, number_of_shares, "
                "price_for_share, currency_of_price, total_czk, "
                "stamp_tax_czk, conversion_fee_czk, french_transaction_tax_czk "
                "FROM trades "
                "WHERE isin_id = ? "
                "ORDER BY timestamp"
            )
            cur = self.execute(sql_trades, (isin_id,))
            trades = cur.fetchall()
            
            # FIFO queue: each entry is [shares, cost_basis_per_share]
            buy_queue = []
            realized_pnl = 0.0
            total_buy_cost = 0.0
            total_sell_proceeds = 0.0
            shares_sold = 0.0
            total_buy_shares = 0.0
            
            for trade in trades:
                (trade_id, ts, trade_type, num_shares, price_per_share, 
                 currency, total_czk, stamp_tax, conv_fee, french_tax) = trade
                
                # Calculate total transaction cost
                transaction_cost = abs(stamp_tax) + abs(conv_fee) + abs(french_tax)
                
                if trade_type == TradeType.BUY:
                    # For BUY: add to queue with cost basis including fees
                    # Cost basis per share = (total paid + fees) / shares
                    total_cost = abs(total_czk) + transaction_cost
                    shares = abs(num_shares)
                    cost_per_share = total_cost / shares if shares > 0 else 0
                    buy_queue.append([shares, cost_per_share, trade_id, ts])
                    total_buy_cost += total_cost
                    total_buy_shares += shares
                    
                elif trade_type == TradeType.SELL:
                    # For SELL: match with oldest buys (FIFO)
                    shares_to_sell = abs(num_shares)
                    sell_proceeds = abs(total_czk) - transaction_cost  # Net proceeds after fees
                    sell_price_per_share = sell_proceeds / shares_to_sell if shares_to_sell > 0 else 0
                    
                    shares_sold += shares_to_sell
                    total_sell_proceeds += sell_proceeds
                    
                    # Only calculate realized P&L if this sell occurred in the date range
                    if start_timestamp <= ts <= end_timestamp:
                        remaining_to_sell = shares_to_sell
                        
                        while remaining_to_sell > 0 and len(buy_queue) > 0:
                            buy_shares, buy_cost_per_share, _, _ = buy_queue[0]
                            
                            if buy_shares <= remaining_to_sell:
                                # Consume entire buy position
                                pnl = (sell_price_per_share - buy_cost_per_share) * buy_shares
                                realized_pnl += pnl
                                remaining_to_sell -= buy_shares
                                buy_queue.pop(0)
                            else:
                                # Partial consumption of buy position
                                pnl = (sell_price_per_share - buy_cost_per_share) * remaining_to_sell
                                realized_pnl += pnl
                                buy_queue[0][0] -= remaining_to_sell
                                remaining_to_sell = 0
                    else:
                        # Sell outside date range - still remove from queue but don't count P&L
                        remaining_to_sell = shares_to_sell
                        while remaining_to_sell > 0 and len(buy_queue) > 0:
                            buy_shares = buy_queue[0][0]
                            if buy_shares <= remaining_to_sell:
                                remaining_to_sell -= buy_shares
                                buy_queue.pop(0)
                            else:
                                buy_queue[0][0] -= remaining_to_sell
                                remaining_to_sell = 0
            
            # Calculate unrealized shares (still in queue)
            unrealized_shares = sum(b[0] for b in buy_queue)
            
            # Only include securities that had activity
            if total_buy_shares > 0 or shares_sold > 0:
                results.append({
                    'isin_id': isin_id,
                    'name': name,
                    'ticker': ticker,
                    'realized_pnl': realized_pnl,
                    'total_buy_cost': total_buy_cost,
                    'total_sell_proceeds': total_sell_proceeds,
                    'shares_sold': shares_sold,
                    'total_buy_shares': total_buy_shares,
                    'unrealized_shares': unrealized_shares
                })
        
        return results