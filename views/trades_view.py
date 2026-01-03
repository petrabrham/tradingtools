"""
Trades view for displaying trade transactions.

Shows hierarchical trade data grouped by security with buy/sell details.
"""

from tkinter import ttk, messagebox
import tkinter as tk
from datetime import datetime
from .base_view import BaseView
from db.repositories.trades import TradeType


class TradesView(BaseView):
    """View for displaying trades data with hierarchical grouping by security."""
    
    def __init__(self, db_manager, root_widget):
        """
        Initialize the trades view.
        
        Args:
            db_manager: DatabaseManager instance for data access
            root_widget: Root Tk widget for clipboard operations
        """
        super().__init__(db_manager)
        self.root_widget = root_widget
    
    def create_view(self, parent_frame: ttk.Frame) -> None:
        """
        Create the trades view UI components.
        
        Args:
            parent_frame: The parent frame to create the view in
        """
        # Layout
        parent_frame.grid_columnconfigure(0, weight=1)
        parent_frame.grid_rowconfigure(0, weight=1)

        tree_frame = ttk.Frame(parent_frame)
        tree_frame.grid(row=0, column=0, sticky="nsew")
        tree_frame.grid_columnconfigure(0, weight=1)
        tree_frame.grid_rowconfigure(0, weight=1)

        columns = (
            "Name",
            "Ticker",
            "Shares Before / To",
            "Total Before / To (CZK)",
            "Trade Type",
            "Date",
            "Shares",
            "Remaining Shares",
            "Price per Share",
            "Total (CZK)",
            "Stamp Tax (CZK)",
            "Conversion Fee (CZK)",
            "French Transaction Tax (CZK)",
        )

        tree = ttk.Treeview(tree_frame, columns=columns, show='tree headings', selectmode='extended')
        tree.grid(row=0, column=0, sticky='nsew')
        self.tree = tree

        # Tree column for expand/collapse icons
        tree.heading("#0", text="")
        tree.column("#0", width=30, stretch=False)

        # Configure columns
        tree.heading("Name", text="Name")
        tree.column("Name", anchor=tk.W, width=200)

        tree.heading("Ticker", text="Ticker")
        tree.column("Ticker", anchor=tk.W, width=40)

        tree.heading("Shares Before / To", text="Shares Before / To")
        tree.column("Shares Before / To", anchor=tk.E, width=120)

        tree.heading("Total Before / To (CZK)", text="Total Before / To (CZK)")
        tree.column("Total Before / To (CZK)", anchor=tk.E, width=150)

        tree.heading("Trade Type", text="Trade Type")
        tree.column("Trade Type", anchor=tk.W, width=90)

        tree.heading("Date", text="Date")
        tree.column("Date", anchor=tk.W, width=110)

        tree.heading("Shares", text="Shares")
        tree.column("Shares", anchor=tk.E, width=90)

        tree.heading("Remaining Shares", text="Remaining Shares")
        tree.column("Remaining Shares", anchor=tk.E, width=130)

        tree.heading("Price per Share", text="Price per Share")
        tree.column("Price per Share", anchor=tk.E, width=120)

        tree.heading("Total (CZK)", text="Total (CZK)")
        tree.column("Total (CZK)", anchor=tk.E, width=110)

        tree.heading("Stamp Tax (CZK)", text="Stamp Tax (CZK)")
        tree.column("Stamp Tax (CZK)", anchor=tk.E, width=130)

        tree.heading("Conversion Fee (CZK)", text="Conversion Fee (CZK)")
        tree.column("Conversion Fee (CZK)", anchor=tk.E, width=150)

        tree.heading("French Transaction Tax (CZK)", text="French Transaction Tax (CZK)")
        tree.column("French Transaction Tax (CZK)", anchor=tk.E, width=200)

        # Scrollbars
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        vsb.grid(row=0, column=1, sticky='ns')
        tree.configure(yscrollcommand=vsb.set)

        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=tree.xview)
        hsb.grid(row=1, column=0, sticky='ew')
        tree.configure(xscrollcommand=hsb.set)

        # Configure tags for coloring BUY and SELL rows
        tree.tag_configure('buy', foreground='green')
        tree.tag_configure('sell', foreground='red')

        # Bind Ctrl+C for clipboard copy
        tree.bind("<Control-c>", lambda e: self.copy_to_clipboard(e, self.root_widget))
        tree.bind("<Control-C>", lambda e: self.copy_to_clipboard(e, self.root_widget))
        
        # Bind right-click for context menu
        tree.bind("<Button-3>", self._show_context_menu)
    
    def update_view(self, start_timestamp: int, end_timestamp: int) -> None:
        """
        Update the trades view with data for the given time range.
        
        Args:
            start_timestamp: Start of date range (Unix timestamp)
            end_timestamp: End of date range (Unix timestamp)
        """
        if not self.tree:
            return
        
        # Clear existing data
        self.clear_view()

        if not self.db or not self.db.conn:
            return

        try:
            # Get all ISINs that have trades in the filter period with aggregated sums
            parents = self.db.trades_repo.get_summary_grouped_by_isin(start_timestamp, end_timestamp)
            
            for parent in parents:
                isin_id, name, ticker, filter_shares, filter_total_czk, filter_stamp_tax, filter_conversion_fee, filter_french_tax = parent
                parent_iid = f"tr_parent_{isin_id}"
                
                # Get cumulative totals before filter start (up to start_timestamp - 1)
                shares_before, total_before = self.db.trades_repo.get_cumulative_totals_by_isin(isin_id, start_timestamp - 1)
                
                # Get cumulative totals up to filter end
                shares_to, total_to = self.db.trades_repo.get_cumulative_totals_by_isin(isin_id, end_timestamp)
                
                # Insert parent row with calculated values
                self.tree.insert("", tk.END, iid=parent_iid, text="", values=(
                    name or "",
                    ticker or "",
                    f"{shares_before:.4f} / {shares_to:.4f}",
                    f"{total_before:.2f} / {total_to:.2f}",
                    "",  # Trade Type (empty for parent)
                    "",  # Date (empty for parent)
                    f"{filter_shares:.4f}",
                    "",  # Remaining Shares (empty for parent)
                    "",  # Price per Share (empty for parent)
                    f"{filter_total_czk:.2f}",
                    f"{filter_stamp_tax:.2f}",
                    f"{filter_conversion_fee:.2f}",
                    f"{filter_french_tax:.2f}"
                ))

                # Child trades for this ISIN within range
                filter_trades = self.db.trades_repo.get_by_isin_and_date_range(isin_id, start_timestamp, end_timestamp)
                for r in filter_trades:
                    # Indices based on trades table layout
                    ts = r[1]
                    trade_type_val = r[4]
                    num_shares = r[5]
                    remaining_quantity = r[6]
                    price_per_share = r[7]
                    currency_of_price = r[8]
                    total_czk = r[9]
                    stamp_tax_czk = r[10]
                    conversion_fee_czk = r[11]
                    french_tax_czk = r[12]

                    dt_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else ""
                    trade_type_str = "BUY" if int(trade_type_val) == 1 else ("SELL" if int(trade_type_val) == 2 else "?")
                    
                    # Determine tag for coloring
                    tag = 'buy' if int(trade_type_val) == 1 else ('sell' if int(trade_type_val) == 2 else '')
                    
                    # Use trade ID as iid for later retrieval
                    trade_id = r[0]
                    child_iid = f"tr_trade_{trade_id}"

                    self.tree.insert(parent_iid, tk.END, iid=child_iid, tags=(tag,), values=(
                        "",  # Name
                        "",  # Ticker
                        "",  # Shares Before / To
                        "",  # Total Before / To (CZK)
                        trade_type_str,
                        dt_str,
                        f"{num_shares:.7f}",
                        f"{remaining_quantity:.7f}",
                        f"{price_per_share:.2f} {currency_of_price}",
                        f"{total_czk:.2f}",
                        f"{stamp_tax_czk:.2f}",
                        f"{conversion_fee_czk:.2f}",
                        f"{french_tax_czk:.2f}"
                    ))
        except Exception as e:
            messagebox.showerror("Database Error", f"Error loading trades: {e}")
    
    def _show_context_menu(self, event):
        """Show context menu on right-click."""
        # Create context menu
        menu = tk.Menu(self.tree, tearoff=0)
        menu.add_command(label="Pair Selected Trades", command=self._pair_selected_trades)
        
        # Show menu at cursor position
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
    
    def _pair_selected_trades(self):
        """Manually pair selected trades."""
        if not self.db or not self.db.conn:
            messagebox.showerror("Error", "No database connection.")
            return
        
        selected_items = self.tree.selection()
        
        if not selected_items:
            messagebox.showerror("Error", "No trades selected.")
            return
        
        # Filter out parent rows - only process child rows (trades)
        trade_items = []
        for item_id in selected_items:
            if item_id.startswith("tr_trade_"):
                trade_items.append(item_id)
        
        if len(trade_items) != 2:
            messagebox.showerror("Error", "Please select exactly 2 trades (1 BUY and 1 SELL).")
            return
        
        # Extract trade IDs from iids
        try:
            trade_ids = [int(item_id.replace("tr_trade_", "")) for item_id in trade_items]
        except ValueError:
            messagebox.showerror("Error", "Invalid trade selection.")
            return
        
        # Fetch trade details from database
        try:
            trades_data = []
            for trade_id in trade_ids:
                trade = self.db.trades_repo.get_by_id(trade_id)
                if not trade:
                    messagebox.showerror("Error", f"Trade with ID {trade_id} not found.")
                    return
                trades_data.append(trade)
            
            # Validate: exactly one BUY and one SELL
            buy_trades = [t for t in trades_data if t[4] == TradeType.BUY]
            sell_trades = [t for t in trades_data if t[4] == TradeType.SELL]
            
            if len(buy_trades) != 1 or len(sell_trades) != 1:
                messagebox.showerror("Error", "Please select exactly 1 BUY trade and 1 SELL trade.")
                return
            
            buy_trade = buy_trades[0]
            sell_trade = sell_trades[0]
            
            # Validate: same security (isin_id)
            if buy_trade[2] != sell_trade[2]:
                messagebox.showerror("Error", "Selected trades must be for the same security.")
                return
            
            # Validate: buy must be older than sell
            buy_timestamp = buy_trade[1]
            sell_timestamp = sell_trade[1]
            if buy_timestamp >= sell_timestamp:
                messagebox.showerror("Error", "BUY trade must be older than SELL trade.")
                return
            
            # Get available quantities
            buy_id = buy_trade[0]
            sell_id = sell_trade[0]
            buy_remaining = buy_trade[6]  # remaining_quantity
            sell_remaining = sell_trade[6]  # remaining_quantity (should be negative or zero)
            
            if buy_remaining <= 0:
                messagebox.showerror("Error", "BUY trade is fully paired (no remaining quantity).")
                return
            
            if sell_remaining >= 0:
                messagebox.showerror("Error", "SELL trade is fully paired (no remaining quantity).")
                return
            
            # Determine pairing quantity (minimum of available quantities)
            pair_quantity = min(buy_remaining, -sell_remaining)
            
            # Calculate holding period in days
            holding_period_days = (sell_timestamp - buy_timestamp) // (24 * 3600)
            
            # Check if time test qualified (>3 years = 1095 days, accounting for leap years)
            time_test_qualified = holding_period_days >= 1095
            
            # Create the pairing
            pairing_id = self.db.pairings_repo.create_pairing(
                sale_trade_id=sell_id,
                purchase_trade_id=buy_id,
                quantity=pair_quantity,
                method='Manual',
                time_test_qualified=time_test_qualified,
                holding_period_days=holding_period_days,
                notes=None
            )
            
            self.db.conn.commit()
            
            self.db.logger.info(
                f"Manual pairing created: {pair_quantity:.7f} shares, "
                f"holding period: {holding_period_days} days, "
                f"time test qualified: {time_test_qualified}"
            )
            
            # Update remaining quantities in the treeview
            new_buy_remaining = buy_remaining - pair_quantity
            new_sell_remaining = sell_remaining + pair_quantity
            
            buy_iid = f"tr_trade_{buy_id}"
            sell_iid = f"tr_trade_{sell_id}"
            
            # Update the "Remaining Shares" column (index 7) in tree values
            buy_values = list(self.tree.item(buy_iid, 'values'))
            buy_values[7] = f"{new_buy_remaining:.7f}"
            self.tree.item(buy_iid, values=buy_values)
            
            sell_values = list(self.tree.item(sell_iid, 'values'))
            sell_values[7] = f"{new_sell_remaining:.7f}"
            self.tree.item(sell_iid, values=sell_values)
            
        except Exception as e:
            self.db.conn.rollback()
            messagebox.showerror("Error", f"Failed to create pairing: {e}")
