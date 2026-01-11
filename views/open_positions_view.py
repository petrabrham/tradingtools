"""
Open Positions view for displaying current holdings.

Shows securities with remaining unpaired quantities (open positions).
"""

from tkinter import ttk, messagebox
import tkinter as tk
from datetime import datetime
from .base_view import BaseView
from db.repositories.trades import TradesRepository, TradeType


class OpenPositionsView(BaseView):
    """View for displaying open positions (unpaired purchase quantities)."""
    
    def __init__(self, db_manager, root_widget):
        """
        Initialize the open positions view.
        
        Args:
            db_manager: DatabaseManager instance for data access
            root_widget: Root Tk widget for clipboard operations
        """
        super().__init__(db_manager)
        self.root_widget = root_widget
        self.trades_repo = TradesRepository(db_manager.conn)
    
    def create_view(self, parent_frame: ttk.Frame) -> None:
        """
        Create the open positions view UI components.
        
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
            "ISIN",
            "Name",
            "Ticker",
            "Total Quantity",
            "Total Cost (CZK)",
            "Avg Price (CZK)",
            "Earliest Trade",
            "Latest Trade"
        )

        tree = ttk.Treeview(tree_frame, columns=columns, show='headings', selectmode='extended')
        tree.grid(row=0, column=0, sticky='nsew')
        self.tree = tree

        # Configure columns
        tree.heading("ISIN", text="ISIN")
        tree.column("ISIN", anchor=tk.W, width=100)

        tree.heading("Name", text="Name")
        tree.column("Name", anchor=tk.W, width=200)

        tree.heading("Ticker", text="Ticker")
        tree.column("Ticker", anchor=tk.W, width=80)

        tree.heading("Total Quantity", text="Total Quantity")
        tree.column("Total Quantity", anchor=tk.E, width=120)

        tree.heading("Total Cost (CZK)", text="Total Cost (CZK)")
        tree.column("Total Cost (CZK)", anchor=tk.E, width=130)

        tree.heading("Avg Price (CZK)", text="Avg Price (CZK)")
        tree.column("Avg Price (CZK)", anchor=tk.E, width=130)

        tree.heading("Earliest Trade", text="Earliest Trade")
        tree.column("Earliest Trade", anchor=tk.W, width=130)

        tree.heading("Latest Trade", text="Latest Trade")
        tree.column("Latest Trade", anchor=tk.W, width=130)

        # Scrollbars
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        vsb.grid(row=0, column=1, sticky='ns')
        tree.configure(yscrollcommand=vsb.set)

        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=tree.xview)
        hsb.grid(row=1, column=0, sticky='ew')
        tree.configure(xscrollcommand=hsb.set)

        # Context menu
        self.context_menu = tk.Menu(tree, tearoff=0)
        self.context_menu.add_command(label="Copy", command=self.copy_selection)
        tree.bind("<Button-3>", self.show_context_menu)

    def copy_selection(self):
        """Copy selected rows to clipboard."""
        from ui import copy_treeview_to_clipboard
        copy_treeview_to_clipboard(self.tree, self.root_widget)

    def show_context_menu(self, event):
        """Show context menu on right-click."""
        # Select item under cursor
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            self.context_menu.post(event.x_root, event.y_root)

    def update_view(self, start_timestamp: int, end_timestamp: int) -> None:
        """
        Update the view with open positions data.
        
        Note: For open positions, start_timestamp is ignored (we use beginning of data).
        Only end_timestamp is used to filter positions as of that date.
        
        Args:
            start_timestamp: Ignored for open positions
            end_timestamp: End of date range (Unix timestamp) - positions as of this date
        """
        self.clear_view()

        if not self.db.conn:
            return

        try:
            # Update repository connection if needed
            if not self.trades_repo.conn:
                self.trades_repo.conn = self.db.conn
            
            # Get open positions from database using aggregation
            # Only pass end_timestamp since we want all purchases from beginning up to this date
            open_positions = self.trades_repo.get_open_positions(end_timestamp)

            if not open_positions:
                # No open positions
                return

            for position in open_positions:
                (isin, name, ticker, total_quantity, total_cost, avg_price,
                 earliest_date, latest_date) = position

                # Format values
                total_quantity_str = f"{total_quantity:.10f}".rstrip('0').rstrip('.')
                total_cost_str = f"{total_cost:,.2f}"
                avg_price_str = f"{avg_price:,.2f}" if avg_price else "0.00"
                
                # Format dates
                earliest_str = datetime.fromtimestamp(earliest_date).strftime("%Y-%m-%d") if earliest_date else ""
                latest_str = datetime.fromtimestamp(latest_date).strftime("%Y-%m-%d") if latest_date else ""

                self.tree.insert(
                    "",
                    "end",
                    values=(
                        isin,
                        name,
                        ticker,
                        total_quantity_str,
                        total_cost_str,
                        avg_price_str,
                        earliest_str,
                        latest_str
                    )
                )

        except Exception as e:
            messagebox.showerror("Error", f"Error loading open positions: {str(e)}")
