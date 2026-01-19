"""
Realized Income View - Shows P&L from actual pairings
"""
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from .base_view import BaseView
from db.repositories.pairings import PairingsRepository


class RealizedIncomeView(BaseView):
    """View for displaying realized income from actual pairings."""
    
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
        self.pairings_repo = PairingsRepository(db_manager.conn)
        
        # Summary variables (will be set before create_view is called)
        self.realized_pnl_var = None
        self.total_buy_cost_var = None
        self.total_sell_proceeds_var = None
        self.unrealized_shares_var = None
        self.warning_label = None  # Warning label for unpaired shares
    
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
        
        columns = ("Name", "Ticker", "Shares Sold", "Shares Paired", 
                   "Buy Cost (CZK)", "Sell Proceeds (CZK)", "Realized P&L (CZK)",
                   "Conversion Fee (Buy/Sell)", "Stamp Tax (Buy/Sell)", "French Tax (Buy/Sell)")
        tree = ttk.Treeview(treeview_frame, columns=columns, show='headings')
        tree.grid(row=0, column=0, sticky='nsew')
        
        self.tree = tree
        
        # Configure tag colors for P&L
        tree.tag_configure('profit', foreground='green')
        tree.tag_configure('loss', foreground='red')
        tree.tag_configure('neutral', foreground='black')
        
        # Configure columns
        tree.heading("Name", text="Name")
        tree.column("Name", anchor=tk.W, width=180)
        
        tree.heading("Ticker", text="Ticker")
        tree.column("Ticker", anchor=tk.W, width=80)
        
        tree.heading("Shares Sold", text="Shares Sold")
        tree.column("Shares Sold", anchor=tk.E, width=100)
        
        tree.heading("Shares Paired", text="Shares Paired")
        tree.column("Shares Paired", anchor=tk.E, width=110)
        
        tree.heading("Buy Cost (CZK)", text="Buy Cost (CZK)")
        tree.column("Buy Cost (CZK)", anchor=tk.E, width=120)
        
        tree.heading("Sell Proceeds (CZK)", text="Sell Proceeds (CZK)")
        tree.column("Sell Proceeds (CZK)", anchor=tk.E, width=130)
        
        tree.heading("Realized P&L (CZK)", text="Realized P&L (CZK)")
        tree.column("Realized P&L (CZK)", anchor=tk.E, width=130)
        
        tree.heading("Conversion Fee (Buy/Sell)", text="Conversion Fee (Buy/Sell)")
        tree.column("Conversion Fee (Buy/Sell)", anchor=tk.E, width=160)
        
        tree.heading("Stamp Tax (Buy/Sell)", text="Stamp Tax (Buy/Sell)")
        tree.column("Stamp Tax (Buy/Sell)", anchor=tk.E, width=150)
        
        tree.heading("French Tax (Buy/Sell)", text="French Tax (Buy/Sell)")
        tree.column("French Tax (Buy/Sell)", anchor=tk.E, width=150)
        
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
        summary_frame.grid_columnconfigure(4, weight=0)
        summary_frame.grid_columnconfigure(5, weight=1)
        
        # Single row with 3 values: Total Buy Cost, Total Sell Proceeds, Total Realized P&L
        ttk.Label(summary_frame, text="Total Purchase (CZK):").grid(
            row=0, column=0, padx=10, pady=5, sticky="w")
        ttk.Entry(summary_frame, textvariable=self.total_buy_cost_var, state='readonly', 
                  width=20, justify='right').grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        
        ttk.Label(summary_frame, text="Total Sold (CZK):").grid(
            row=0, column=2, padx=10, pady=5, sticky="w")
        ttk.Entry(summary_frame, textvariable=self.total_sell_proceeds_var, state='readonly', 
                  width=20, justify='right').grid(row=0, column=3, padx=5, pady=5, sticky="ew")
        
        ttk.Label(summary_frame, text="Total P&L (CZK):", font=('TkDefaultFont', 9, 'bold')).grid(
            row=0, column=4, padx=10, pady=5, sticky="w")
        ttk.Entry(summary_frame, textvariable=self.realized_pnl_var, state='readonly', 
                  width=20, justify='right').grid(row=0, column=5, padx=5, pady=5, sticky="ew")
        
        # Warning label for unpaired shares (row 1, spans all columns)
        self.warning_label = ttk.Label(summary_frame, 
                                       text="⚠️ Warning: Not all shares are fully paired. Purchase cost and P&L values are partial.",
                                       foreground='orange', 
                                       font=('TkDefaultFont', 9, 'bold'))
        # Initially hidden, will be shown if needed
    
    def update_view(self, start_timestamp, end_timestamp):
        """
        Calculate and display realized income from actual pairings.
        Shows P&L from sales with pairings within the date range.
        
        Args:
            start_timestamp: Start of the date range (Unix timestamp)
            end_timestamp: End of the date range (Unix timestamp)
        """
        if not self.tree:
            return
        
        # Clear existing data
        self.clear_view()
        
        if not self.db or not self.db.conn:
            self.realized_pnl_var.set("0.00 CZK")
            self.total_buy_cost_var.set("0.00 CZK")
            self.total_sell_proceeds_var.set("0.00 CZK")
            self.unrealized_shares_var.set("0")
            return
        
        try:
            # Update repository connection if needed
            if not self.pairings_repo.conn:
                self.pairings_repo.conn = self.db.conn
            
            # Get realized income calculations from pairings
            results = self.pairings_repo.calculate_realized_income(start_timestamp, end_timestamp)
            
            # Track totals
            total_realized_pnl = 0.0
            total_buy_cost = 0.0
            total_sell_proceeds = 0.0
            total_unrealized_shares = 0.0
            has_unpaired_shares = False  # Track if any securities have unpaired shares
            
            # Populate tree with individual securities
            for result in results:
                name = result['name'] or ""
                ticker = result['ticker'] or ""
                shares_sold = result['shares_sold']
                shares_paired = result['shares_paired']
                buy_cost = result['total_buy_cost']
                sell_proceeds = result['total_sell_proceeds']
                realized_pnl = result['realized_pnl']
                unrealized_shares = result['unrealized_shares']
                
                # Tax values
                buy_conversion = result['buy_conversion_fee']
                sell_conversion = result['sell_conversion_fee']
                buy_stamp = result['buy_stamp_tax']
                sell_stamp = result['sell_stamp_tax']
                buy_french = result['buy_french_tax']
                sell_french = result['sell_french_tax']
                
                # Check if shares are fully paired
                is_fully_paired = abs(shares_sold - shares_paired) < 0.0000001  # tolerance for floating point
                
                # Format P&L and determine color tag
                pnl_str = f"{realized_pnl:,.2f}"
                
                # If not fully paired, always use black text
                if not is_fully_paired:
                    has_unpaired_shares = True
                    if realized_pnl > 0:
                        pnl_display = f"+{pnl_str}"
                    else:
                        pnl_display = pnl_str
                    tag = 'neutral'
                # If fully paired, use color based on P&L
                elif realized_pnl > 0:
                    pnl_display = f"+{pnl_str}"
                    tag = 'profit'
                elif realized_pnl < 0:
                    pnl_display = pnl_str
                    tag = 'loss'
                else:
                    pnl_display = pnl_str
                    tag = 'neutral'
                
                self.tree.insert("", tk.END, values=(
                    name,
                    ticker,
                    f"{shares_sold:.9f}",
                    f"{shares_paired:.9f}",
                    f"{buy_cost:,.2f}",
                    f"{sell_proceeds:,.2f}",
                    pnl_display,
                    f"{buy_conversion:,.2f} / {sell_conversion:,.2f}",
                    f"{buy_stamp:,.2f} / {sell_stamp:,.2f}",
                    f"{buy_french:,.2f} / {sell_french:,.2f}"
                ), tags=(tag,))
                
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
            
            # Show/hide warning label based on pairing status
            if has_unpaired_shares:
                self.warning_label.grid(row=1, column=0, columnspan=6, padx=10, pady=5, sticky="w")
            else:
                self.warning_label.grid_forget()
            
        except Exception as e:
            messagebox.showerror("Database Error", f"Error calculating realized income: {e}")
