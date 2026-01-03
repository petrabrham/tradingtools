"""
Trades view for displaying trade transactions.

Shows hierarchical trade data grouped by security with buy/sell details.
"""

from tkinter import ttk, messagebox
import tkinter as tk
from datetime import datetime
from typing import Tuple, Optional
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
        
        # Check if pairing is possible with current selection
        can_pair, _ = self._validate_pairing_selection()
        
        # Add command - enable only if valid selection
        menu.add_command(
            label="Pair Selected Trades",
            command=self._pair_selected_trades,
            state=tk.NORMAL if can_pair else tk.DISABLED
        )
        
        # Show menu at cursor position
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
    
    def _validate_pairing_selection(self) -> Tuple[bool, Optional[str]]:
        """Validate if current selection can be paired.
        
        Returns:
            Tuple of (can_pair: bool, error_message: Optional[str])
        """
        selected_items = self.tree.selection()
        
        if not selected_items:
            return False, "No trades selected"
        
        # Filter trade items (exclude parent rows)
        trade_items = [item for item in selected_items if item.startswith("tr_trade_")]
        
        if len(trade_items) != 2:
            return False, "Must select exactly 2 trades"
        
        # Get values from tree for both trades
        try:
            trade1_values = self.tree.item(trade_items[0], 'values')
            trade2_values = self.tree.item(trade_items[1], 'values')
            
            # Extract trade info from tree values
            # Index 4 = Trade Type, Index 5 = Date, Index 7 = Remaining Shares
            type1 = trade1_values[4]
            type2 = trade2_values[4]
            date1 = trade1_values[5]
            date2 = trade2_values[5]
            remaining1 = float(trade1_values[7])
            remaining2 = float(trade2_values[7])
            
            # Check one BUY and one SELL
            if not ((type1 == "BUY" and type2 == "SELL") or (type1 == "SELL" and type2 == "BUY")):
                return False, "Must select 1 BUY and 1 SELL"
            
            # Check both have remaining quantity
            if type1 == "BUY":
                if remaining1 <= 0:
                    return False, "BUY trade fully paired"
                if remaining2 >= 0:
                    return False, "SELL trade fully paired"
            else:  # type1 == "SELL"
                if remaining1 >= 0:
                    return False, "SELL trade fully paired"
                if remaining2 <= 0:
                    return False, "BUY trade fully paired"
            
            # Check same security (same parent)
            parent1 = self.tree.parent(trade_items[0])
            parent2 = self.tree.parent(trade_items[1])
            if parent1 != parent2:
                return False, "Trades must be for same security"
            
            # Check chronological order (BUY before SELL)
            if type1 == "BUY":
                if date1 >= date2:
                    return False, "BUY must be older than SELL"
            else:  # type1 == "SELL"
                if date2 >= date1:
                    return False, "BUY must be older than SELL"
            
            return True, None
            
        except (IndexError, ValueError) as e:
            return False, f"Invalid selection: {e}"
    
    def _pair_selected_trades(self):
        """Manually pair selected trades."""
        if not self.db or not self.db.conn:
            messagebox.showerror("Error", "No database connection.")
            return
        
        selected_items = self.tree.selection()
        trade_items = [item for item in selected_items if item.startswith("tr_trade_")]
        
        if len(trade_items) != 2:
            return  # Should not happen as menu item is disabled
        
        # Extract trade IDs
        try:
            trade_ids = [int(item.replace("tr_trade_", "")) for item in trade_items]
        except ValueError:
            messagebox.showerror("Error", "Invalid trade selection.")
            return
        
        # Determine which is BUY and which is SELL from tree values
        type1 = self.tree.item(trade_items[0], 'values')[4]
        type2 = self.tree.item(trade_items[1], 'values')[4]
        
        if type1 == "BUY":
            buy_id, sell_id = trade_ids[0], trade_ids[1]
            buy_iid, sell_iid = trade_items[0], trade_items[1]
        else:
            buy_id, sell_id = trade_ids[1], trade_ids[0]
            buy_iid, sell_iid = trade_items[1], trade_items[0]
        
        # Get current remaining quantities from tree
        buy_remaining = float(self.tree.item(buy_iid, 'values')[7])
        sell_remaining = float(self.tree.item(sell_iid, 'values')[7])
        
        # Call manual_pair from repository
        result = self.db.pairings_repo.manual_pair(sell_id, buy_id)
        
        if not result['success']:
            messagebox.showerror("Pairing Failed", result['error'])
            return
        
        # Log success
        self.db.logger.info(
            f"Manual pairing created: {result['quantity_paired']:.7f} shares, "
            f"holding period: {result['holding_period_days']} days, "
            f"time test qualified: {result['time_test_qualified']}"
        )
        
        # Update remaining quantities in treeview
        pair_quantity = result['quantity_paired']
        new_buy_remaining = buy_remaining - pair_quantity
        new_sell_remaining = sell_remaining + pair_quantity
        
        buy_values = list(self.tree.item(buy_iid, 'values'))
        buy_values[7] = f"{new_buy_remaining:.7f}"
        self.tree.item(buy_iid, values=buy_values)
        
        sell_values = list(self.tree.item(sell_iid, 'values'))
        sell_values[7] = f"{new_sell_remaining:.7f}"
        self.tree.item(sell_iid, values=sell_values)
