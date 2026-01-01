"""
Trades view for displaying trade transactions.

Shows hierarchical trade data grouped by security with buy/sell details.
"""

from tkinter import ttk, messagebox
import tkinter as tk
from datetime import datetime
from .base_view import BaseView


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
            "Price per Share",
            "Total (CZK)",
            "Stamp Tax (CZK)",
            "Conversion Fee (CZK)",
            "French Transaction Tax (CZK)",
        )

        tree = ttk.Treeview(tree_frame, columns=columns, show='tree headings')
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
                    price_per_share = r[6]
                    currency_of_price = r[7]
                    total_czk = r[8]
                    stamp_tax_czk = r[9]
                    conversion_fee_czk = r[10]
                    french_tax_czk = r[11]

                    dt_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else ""
                    trade_type_str = "BUY" if int(trade_type_val) == 1 else ("SELL" if int(trade_type_val) == 2 else "?")
                    
                    # Determine tag for coloring
                    tag = 'buy' if int(trade_type_val) == 1 else ('sell' if int(trade_type_val) == 2 else '')

                    self.tree.insert(parent_iid, tk.END, tags=(tag,), values=(
                        "",  # Name
                        "",  # Ticker
                        "",  # Shares Before / To
                        "",  # Total Before / To (CZK)
                        trade_type_str,
                        dt_str,
                        f"{num_shares:.7f}",
                        f"{price_per_share:.2f} {currency_of_price}",
                        f"{total_czk:.2f}",
                        f"{stamp_tax_czk:.2f}",
                        f"{conversion_fee_czk:.2f}",
                        f"{french_tax_czk:.2f}"
                    ))
        except Exception as e:
            messagebox.showerror("Database Error", f"Error loading trades: {e}")
