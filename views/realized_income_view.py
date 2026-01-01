"""
Realized Income View - FIFO P&L calculations for closed positions
"""
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from .base_view import BaseView


class RealizedIncomeView(BaseView):
    """View for displaying realized income using FIFO matching."""
    
    def __init__(self, db_manager, root):
        """
        Initialize the RealizedIncomeView.
        
        Args:
            db_manager: DatabaseManager instance
            root: Root tk widget for event binding
        """
        super().__init__(db_manager)
        self.root = root
        self.tree = None
        
        # Summary variables (will be set before create_view is called)
        self.realized_pnl_var = None
        self.total_buy_cost_var = None
        self.total_sell_proceeds_var = None
        self.unrealized_shares_var = None
    
    def set_summary_variables(self, realized_pnl_var, total_buy_cost_var, 
                              total_sell_proceeds_var, unrealized_shares_var):
        """
        Set the StringVar objects for summary display.
        
        Args:
            realized_pnl_var: StringVar for total realized P&L
            total_buy_cost_var: StringVar for total buy cost
            total_sell_proceeds_var: StringVar for total sell proceeds
            unrealized_shares_var: StringVar for total unrealized shares
        """
        self.realized_pnl_var = realized_pnl_var
        self.total_buy_cost_var = total_buy_cost_var
        self.total_sell_proceeds_var = total_sell_proceeds_var
        self.unrealized_shares_var = unrealized_shares_var
    
    def create_view(self, parent_frame):
        """
        Create the realized income view with FIFO calculation results.
        
        Args:
            parent_frame: Parent ttk.Frame to contain the view
        """
        parent_frame.grid_columnconfigure(0, weight=1)
        parent_frame.grid_rowconfigure(0, weight=1)  # Treeview (expands)
        parent_frame.grid_rowconfigure(1, weight=0)  # Summary Panel (fixed height)

        # --- Top Part: Treeview for Realized Income (Row 0) ---
        treeview_frame = ttk.Frame(parent_frame)
        treeview_frame.grid(row=0, column=0, sticky="nsew")
        
        treeview_frame.grid_columnconfigure(0, weight=1)
        treeview_frame.grid_rowconfigure(0, weight=1)
        
        columns = ("Name", "Ticker", "Realized P&L (CZK)", "Shares Sold", 
                   "Buy Cost (CZK)", "Sell Proceeds (CZK)", "Unrealized Shares")
        tree = ttk.Treeview(treeview_frame, columns=columns, show='headings')
        tree.grid(row=0, column=0, sticky='nsew')
        
        self.tree = tree
        
        # Configure columns
        tree.heading("Name", text="Name")
        tree.column("Name", anchor=tk.W, width=200)
        
        tree.heading("Ticker", text="Ticker")
        tree.column("Ticker", anchor=tk.W, width=100)
        
        tree.heading("Realized P&L (CZK)", text="Realized P&L (CZK)")
        tree.column("Realized P&L (CZK)", anchor=tk.E, width=150)
        
        tree.heading("Shares Sold", text="Shares Sold")
        tree.column("Shares Sold", anchor=tk.E, width=120)
        
        tree.heading("Buy Cost (CZK)", text="Buy Cost (CZK)")
        tree.column("Buy Cost (CZK)", anchor=tk.E, width=130)
        
        tree.heading("Sell Proceeds (CZK)", text="Sell Proceeds (CZK)")
        tree.column("Sell Proceeds (CZK)", anchor=tk.E, width=150)
        
        tree.heading("Unrealized Shares", text="Unrealized Shares")
        tree.column("Unrealized Shares", anchor=tk.E, width=140)
        
        # Scrollbars
        vsb = ttk.Scrollbar(treeview_frame, orient="vertical", command=tree.yview)
        vsb.grid(row=0, column=1, sticky='ns')
        tree.configure(yscrollcommand=vsb.set)
        
        hsb = ttk.Scrollbar(treeview_frame, orient="horizontal", command=tree.xview)
        hsb.grid(row=1, column=0, sticky='ew')
        tree.configure(xscrollcommand=hsb.set)
        
        # Bind Ctrl+C for clipboard copy
        tree.bind("<Control-c>", lambda e: self.copy_to_clipboard(e, self.root))
        tree.bind("<Control-C>", lambda e: self.copy_to_clipboard(e, self.root))
        
        # --- Bottom Part: Summary Panel (Row 1) ---
        summary_frame = ttk.LabelFrame(parent_frame, text="Summary")
        summary_frame.grid(row=1, column=0, sticky="ew", pady=(5, 0), padx=2)
        
        summary_frame.grid_columnconfigure(0, weight=0)
        summary_frame.grid_columnconfigure(1, weight=1)
        summary_frame.grid_columnconfigure(2, weight=0)
        summary_frame.grid_columnconfigure(3, weight=1)
        
        # Row 0: Total Realized P&L and Unrealized Shares
        ttk.Label(summary_frame, text="Total Realized P&L:", font=('TkDefaultFont', 9, 'bold')).grid(
            row=0, column=0, padx=10, pady=5, sticky="w")
        ttk.Entry(summary_frame, textvariable=self.realized_pnl_var, state='readonly', 
                  width=20, justify='right').grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        
        ttk.Label(summary_frame, text="Total Unrealized Shares:", font=('TkDefaultFont', 9, 'bold')).grid(
            row=0, column=2, padx=10, pady=5, sticky="w")
        ttk.Entry(summary_frame, textvariable=self.unrealized_shares_var, state='readonly', 
                  width=20, justify='right').grid(row=0, column=3, padx=5, pady=5, sticky="ew")
        
        # Row 1: Total Buy Cost and Total Sell Proceeds
        ttk.Label(summary_frame, text="Total Buy Cost:").grid(
            row=1, column=0, padx=10, pady=5, sticky="w")
        ttk.Entry(summary_frame, textvariable=self.total_buy_cost_var, state='readonly', 
                  width=20, justify='right').grid(row=1, column=1, padx=5, pady=5, sticky="ew")
        
        ttk.Label(summary_frame, text="Total Sell Proceeds:").grid(
            row=1, column=2, padx=10, pady=5, sticky="w")
        ttk.Entry(summary_frame, textvariable=self.total_sell_proceeds_var, state='readonly', 
                  width=20, justify='right').grid(row=1, column=3, padx=5, pady=5, sticky="ew")
    
    def update_view(self, start_timestamp, end_timestamp):
        """
        Calculate and display realized income using FIFO matching.
        Shows P&L from closed positions (buys that have been sold).
        
        Args:
            start_timestamp: Start of the date range (Unix timestamp)
            end_timestamp: End of the date range (Unix timestamp)
        """
        if not self.tree:
            return
        
        # Clear existing data
        self.clear_view()
        
        if not self.db or not self.db.conn or not self.db.trades_repo:
            self.realized_pnl_var.set("0.00 CZK")
            self.total_buy_cost_var.set("0.00 CZK")
            self.total_sell_proceeds_var.set("0.00 CZK")
            self.unrealized_shares_var.set("0")
            return
        
        try:
            # Get realized income calculations
            results = self.db.trades_repo.calculate_realized_income(start_timestamp, end_timestamp)
            
            # Track totals
            total_realized_pnl = 0.0
            total_buy_cost = 0.0
            total_sell_proceeds = 0.0
            total_unrealized_shares = 0.0
            
            # Populate tree with individual securities
            for result in results:
                name = result['name'] or ""
                ticker = result['ticker'] or ""
                realized_pnl = result['realized_pnl']
                shares_sold = result['shares_sold']
                buy_cost = result['total_buy_cost']
                sell_proceeds = result['total_sell_proceeds']
                unrealized_shares = result['unrealized_shares']
                
                # Color coding for P&L
                pnl_str = f"{realized_pnl:,.2f}"
                if realized_pnl > 0:
                    pnl_display = f"+{pnl_str}"
                elif realized_pnl < 0:
                    pnl_display = pnl_str
                else:
                    pnl_display = pnl_str
                
                self.tree.insert("", tk.END, values=(
                    name,
                    ticker,
                    pnl_display,
                    f"{shares_sold:.4f}",
                    f"{buy_cost:,.2f}",
                    f"{sell_proceeds:,.2f}",
                    f"{unrealized_shares:.4f}"
                ))
                
                # Update totals
                total_realized_pnl += realized_pnl
                total_buy_cost += buy_cost
                total_sell_proceeds += sell_proceeds
                total_unrealized_shares += unrealized_shares
            
            # Update summary fields
            pnl_str = f"{total_realized_pnl:,.2f}"
            if total_realized_pnl > 0:
                self.realized_pnl_var.set(f"+{pnl_str} CZK")
            elif total_realized_pnl < 0:
                self.realized_pnl_var.set(f"{pnl_str} CZK")
            else:
                self.realized_pnl_var.set(f"{pnl_str} CZK")
            
            self.total_buy_cost_var.set(f"{total_buy_cost:,.2f} CZK")
            self.total_sell_proceeds_var.set(f"{total_sell_proceeds:,.2f} CZK")
            self.unrealized_shares_var.set(f"{total_unrealized_shares:,.4f}")
            
        except Exception as e:
            messagebox.showerror("Database Error", f"Error calculating realized income: {e}")
