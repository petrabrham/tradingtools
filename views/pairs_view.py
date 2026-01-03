"""
Pairs view for managing trade pairings between purchases and sales.

Allows users to view unpaired sales, available purchase lots, and create/manage pairings.
"""

from tkinter import ttk, messagebox
import tkinter as tk
from datetime import datetime
from typing import Optional, Dict, List
from .base_view import BaseView
from db.repositories.pairings import PairingsRepository
from db.repositories.trades import TradesRepository, TradeType
from config.logger_config import get_logger


class PairsView(BaseView):
    """View for managing trade pairings between purchases and sales."""
    
    def __init__(self, db_manager, root_widget):
        """
        Initialize the pairs view.
        
        Args:
            db_manager: DatabaseManager instance for data access
            root_widget: Root Tk widget for dialog operations
        """
        super().__init__(db_manager)
        self.root_widget = root_widget
        self.logger = get_logger(__name__)
        
        # Initialize repositories
        self.pairings_repo = PairingsRepository(db_manager.conn)
        self.trades_repo = TradesRepository(db_manager.conn)
        
        # UI references
        self.sales_tree = None
        self.lots_tree = None
        self.pairings_tree = None
        self.timetest_var = None
        
        # State
        self.current_sale_id = None
        self.current_start_timestamp = None
        self.current_end_timestamp = None
    
    def create_view(self, parent_frame: ttk.Frame) -> None:
        """
        Create the pairs view UI components.
        
        Args:
            parent_frame: The parent frame to create the view in
        """
        # Configure parent frame - 3 rows
        parent_frame.grid_columnconfigure(0, weight=1)
        parent_frame.grid_columnconfigure(1, weight=1)
        parent_frame.grid_rowconfigure(0, weight=2)  # Row 0: Sales and Lots (larger)
        parent_frame.grid_rowconfigure(1, weight=1)  # Row 1: Current Pairings
        parent_frame.grid_rowconfigure(2, weight=0)  # Row 2: Actions (fixed height)
        
        # Row 0, Column 0: Sales list
        self._create_sales_panel(parent_frame)
        
        # Row 0, Column 1: Available purchase lots
        self._create_lots_panel(parent_frame)
        
        # Row 1: Current pairings (full width)
        self._create_pairings_panel(parent_frame)
        
        # Row 2: Action buttons
        self._create_action_section(parent_frame)
    
    def _create_sales_panel(self, parent_frame: ttk.Frame) -> None:
        """Create the sales list panel."""
        sales_frame = ttk.LabelFrame(parent_frame, text="Sales Transactions", padding=5)
        sales_frame.grid(row=0, column=0, sticky="nsew", padx=(5, 2), pady=5)
        sales_frame.grid_columnconfigure(0, weight=1)
        sales_frame.grid_rowconfigure(0, weight=1)
        
        # Sales treeview
        columns = ("Security", "Ticker", "Date", "Quantity", "Remaining", "Price", 
                   "Total", "Status", "Method", "Locked")
        self.sales_tree = ttk.Treeview(sales_frame, columns=columns, show='headings', 
                                       selectmode='browse')
        self.sales_tree.grid(row=0, column=0, sticky='nsew')
        
        # Configure columns
        self.sales_tree.heading("Security", text="Security")
        self.sales_tree.column("Security", anchor=tk.W, width=150)
        
        self.sales_tree.heading("Ticker", text="Ticker")
        self.sales_tree.column("Ticker", anchor=tk.W, width=60)
        
        self.sales_tree.heading("Date", text="Date")
        self.sales_tree.column("Date", anchor=tk.W, width=100)
        
        self.sales_tree.heading("Quantity", text="Quantity")
        self.sales_tree.column("Quantity", anchor=tk.E, width=80)
        
        self.sales_tree.heading("Remaining", text="Remaining")
        self.sales_tree.column("Remaining", anchor=tk.E, width=80)
        
        self.sales_tree.heading("Price", text="Price/Share")
        self.sales_tree.column("Price", anchor=tk.E, width=90)
        
        self.sales_tree.heading("Total", text="Total (CZK)")
        self.sales_tree.column("Total", anchor=tk.E, width=100)
        
        self.sales_tree.heading("Status", text="Status")
        self.sales_tree.column("Status", anchor=tk.W, width=100)
        
        self.sales_tree.heading("Method", text="Method Used")
        self.sales_tree.column("Method", anchor=tk.W, width=150)
        
        self.sales_tree.heading("Locked", text="🔒")
        self.sales_tree.column("Locked", anchor=tk.CENTER, width=40)
        
        # Scrollbars
        vsb = ttk.Scrollbar(sales_frame, orient="vertical", command=self.sales_tree.yview)
        vsb.grid(row=0, column=1, sticky='ns')
        self.sales_tree.configure(yscrollcommand=vsb.set)
        
        hsb = ttk.Scrollbar(sales_frame, orient="horizontal", command=self.sales_tree.xview)
        hsb.grid(row=1, column=0, sticky='ew')
        self.sales_tree.configure(xscrollcommand=hsb.set)
        
        # Bind selection event
        self.sales_tree.bind('<<TreeviewSelect>>', self._on_sale_selected)
    
    def _create_lots_panel(self, parent_frame: ttk.Frame) -> None:
        """Create the available purchase lots panel."""
        lots_frame = ttk.LabelFrame(parent_frame, text="Available Purchase Lots", padding=5)
        lots_frame.grid(row=0, column=1, sticky="nsew", padx=(2, 5), pady=5)
        lots_frame.grid_columnconfigure(0, weight=1)
        lots_frame.grid_rowconfigure(0, weight=1)
        
        # Lots treeview
        columns = ("Date", "Quantity", "Available", "Price", "Holding", "TimeTest")
        self.lots_tree = ttk.Treeview(lots_frame, columns=columns, show='headings', 
                                      selectmode='browse')
        self.lots_tree.grid(row=0, column=0, sticky='nsew')
        
        # Configure columns
        self.lots_tree.heading("Date", text="Purchase Date")
        self.lots_tree.column("Date", anchor=tk.W, width=100)
        
        self.lots_tree.heading("Quantity", text="Original Qty")
        self.lots_tree.column("Quantity", anchor=tk.E, width=90)
        
        self.lots_tree.heading("Available", text="Available Qty")
        self.lots_tree.column("Available", anchor=tk.E, width=100)
        
        self.lots_tree.heading("Price", text="Price/Share")
        self.lots_tree.column("Price", anchor=tk.E, width=90)
        
        self.lots_tree.heading("Holding", text="Holding Period")
        self.lots_tree.column("Holding", anchor=tk.W, width=120)
        
        self.lots_tree.heading("TimeTest", text="⏰")
        self.lots_tree.column("TimeTest", anchor=tk.CENTER, width=40)
        
        # Scrollbars
        vsb = ttk.Scrollbar(lots_frame, orient="vertical", command=self.lots_tree.yview)
        vsb.grid(row=0, column=1, sticky='ns')
        self.lots_tree.configure(yscrollcommand=vsb.set)
    
    def _create_pairings_panel(self, parent_frame: ttk.Frame) -> None:
        """Create the current pairings panel."""
        pairings_frame = ttk.LabelFrame(parent_frame, text="Current Pairs", padding=5)
        pairings_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=5, pady=5)
        pairings_frame.grid_columnconfigure(0, weight=1)
        pairings_frame.grid_rowconfigure(0, weight=1)
        
        # Pairings treeview with expanded columns
        columns = ("🔒", "Sale Date", "Purchase Date", "Security", "Ticker", 
                   "Holding Period", "⏰", "Quantity", "Purchase Price", "Sale Price", 
                   "P&L (CZK)", "Method", "Lock Reason")
        self.pairings_tree = ttk.Treeview(pairings_frame, columns=columns, show='headings', 
                                          selectmode='browse')
        self.pairings_tree.grid(row=0, column=0, sticky='nsew')
        
        # Configure columns
        self.pairings_tree.heading("🔒", text="🔒")
        self.pairings_tree.column("🔒", anchor=tk.CENTER, width=30)
        
        self.pairings_tree.heading("Sale Date", text="Sale Date")
        self.pairings_tree.column("Sale Date", anchor=tk.W, width=90)
        
        self.pairings_tree.heading("Purchase Date", text="Purchase Date")
        self.pairings_tree.column("Purchase Date", anchor=tk.W, width=90)
        
        self.pairings_tree.heading("Security", text="Security")
        self.pairings_tree.column("Security", anchor=tk.W, width=150)
        
        self.pairings_tree.heading("Ticker", text="Ticker")
        self.pairings_tree.column("Ticker", anchor=tk.W, width=60)
        
        self.pairings_tree.heading("Holding Period", text="Holding Period")
        self.pairings_tree.column("Holding Period", anchor=tk.W, width=110)
        
        self.pairings_tree.heading("⏰", text="⏰")
        self.pairings_tree.column("⏰", anchor=tk.CENTER, width=30)
        
        self.pairings_tree.heading("Quantity", text="Quantity")
        self.pairings_tree.column("Quantity", anchor=tk.E, width=80)
        
        self.pairings_tree.heading("Purchase Price", text="Purchase Price")
        self.pairings_tree.column("Purchase Price", anchor=tk.E, width=110)
        
        self.pairings_tree.heading("Sale Price", text="Sale Price")
        self.pairings_tree.column("Sale Price", anchor=tk.E, width=110)
        
        self.pairings_tree.heading("P&L (CZK)", text="P&L (CZK)")
        self.pairings_tree.column("P&L (CZK)", anchor=tk.E, width=100)
        
        self.pairings_tree.heading("Method", text="Method")
        self.pairings_tree.column("Method", anchor=tk.W, width=80)
        
        self.pairings_tree.heading("Lock Reason", text="Lock Reason")
        self.pairings_tree.column("Lock Reason", anchor=tk.W, width=150)
        
        # Scrollbars
        vsb = ttk.Scrollbar(pairings_frame, orient="vertical", command=self.pairings_tree.yview)
        vsb.grid(row=0, column=1, sticky='ns')
        self.pairings_tree.configure(yscrollcommand=vsb.set)
    
    def _create_action_section(self, parent_frame: ttk.Frame) -> None:
        """Create the action buttons section."""
        action_frame = ttk.LabelFrame(parent_frame, text="Actions", padding=10)
        action_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=5, pady=5)
        
        # Method selection
        ttk.Label(action_frame, text="Method:").grid(row=0, column=0, padx=5, pady=2)
        self.method_var = tk.StringVar(value="FIFO")
        method_combo = ttk.Combobox(action_frame, textvariable=self.method_var, 
                                    width=15, state="readonly")
        method_combo['values'] = ["FIFO", "LIFO", "MaxLose", "MaxProfit"]
        method_combo.grid(row=0, column=1, padx=5, pady=2)
        
        # TimeTest filter checkbox
        self.timetest_var = tk.BooleanVar(value=False)
        timetest_check = ttk.Checkbutton(action_frame, text="Time Test Only (3+ years)", 
                                         variable=self.timetest_var)
        timetest_check.grid(row=0, column=2, padx=10, pady=2)
        
        # Apply method button
        apply_btn = ttk.Button(action_frame, text="Apply Method to Selected Sale", 
                               command=self._apply_method_to_selected)
        apply_btn.grid(row=0, column=3, padx=10, pady=2)
        
        # Apply to interval button
        apply_interval_btn = ttk.Button(action_frame, text="Apply to All Unpaired in Interval", 
                                        command=self._apply_method_to_interval)
        apply_interval_btn.grid(row=0, column=4, padx=5, pady=2)
        
        # Delete pairing button
        delete_btn = ttk.Button(action_frame, text="Delete Selected Pairing", 
                                command=self._delete_selected_pairing)
        delete_btn.grid(row=0, column=5, padx=5, pady=2)
        
        # Refresh button
        refresh_btn = ttk.Button(action_frame, text="Refresh", command=self.refresh_view)
        refresh_btn.grid(row=0, column=6, padx=5, pady=2)
    
    def update_view(self, start_timestamp: int, end_timestamp: int) -> None:
        """
        Update the view with data for the given time range.
        
        Args:
            start_timestamp: Start of date range (Unix timestamp)
            end_timestamp: End of date range (Unix timestamp)
        """
        self.current_start_timestamp = start_timestamp
        self.current_end_timestamp = end_timestamp
        
        # Load all data independently
        self._load_sales_in_interval()
        self._load_current_pairings(start_timestamp, end_timestamp)
    
    def _load_sales_in_interval(self) -> None:
        """Load all sale transactions in the selected time interval."""
        try:
            # Check if timestamps are set
            if self.current_start_timestamp is None or self.current_end_timestamp is None:
                return
            
            # Clear existing data
            self.clear_view()
            
            # Load sales from database
            sales_data = self._get_sales_in_interval(self.current_start_timestamp, 
                                                     self.current_end_timestamp)
            
            # Populate sales tree
            for sale in sales_data:
                self._insert_sale_row(sale)
            
            start_date = datetime.fromtimestamp(self.current_start_timestamp).strftime("%Y-%m-%d")
            end_date = datetime.fromtimestamp(self.current_end_timestamp).strftime("%Y-%m-%d")
            self.logger.info(f"Loaded {len(sales_data)} sales from {start_date} to {end_date}")
            
        except Exception as e:
            self.logger.error(f"Error loading sales: {e}", exc_info=True)
            messagebox.showerror("Error", f"Failed to load sales: {e}")
    
    def _get_sales_in_interval(self, start_timestamp: int, end_timestamp: int) -> List[Dict]:
        """Get all SELL trades in the time interval with pairing status."""
        sql = """
            SELECT 
                t.id,
                s.name,
                s.ticker,
                t.timestamp,
                t.number_of_shares,
                t.remaining_quantity,
                t.price_for_share,
                (t.number_of_shares * t.price_for_share * -1) as total_czk
            FROM trades t
            JOIN securities s ON t.isin_id = s.id
            WHERE t.trade_type = ?
            AND t.timestamp >= ?
            AND t.timestamp <= ?
            ORDER BY t.timestamp DESC
        """
        
        cur = self.db.conn.execute(sql, (TradeType.SELL, start_timestamp, end_timestamp))
        rows = cur.fetchall()
        
        result = []
        for row in rows:
            sale_id = row[0]
            
            # Get pairing info
            pairings = self.pairings_repo.get_pairings_for_purchase(sale_id)
            is_locked = self.pairings_repo.is_pairing_locked(sale_id) if pairings else False
            
            # Determine status
            remaining_qty = abs(row[5])
            total_qty = abs(row[4])
            if remaining_qty < 1e-10:
                status = "Fully Paired"
            elif remaining_qty >= total_qty - 1e-10:
                status = "Unpaired"
            else:
                status = "Partially Paired"
            
            # Get method combination if paired
            method = ""
            if pairings:
                method = self.pairings_repo.derive_method_combination(sale_id)
            
            result.append({
                'id': sale_id,
                'name': row[1],
                'ticker': row[2],
                'timestamp': row[3],
                'quantity': row[4],
                'remaining_quantity': row[5],
                'price': row[6],
                'total_czk': row[7],
                'status': status,
                'method': method,
                'locked': is_locked
            })
        
        return result
    
    def _insert_sale_row(self, sale: Dict) -> None:
        """Insert a sale row into the sales tree."""
        date_str = datetime.fromtimestamp(sale['timestamp']).strftime("%Y-%m-%d")
        locked_str = "🔒" if sale['locked'] else ""
        
        values = (
            sale['name'],
            sale['ticker'],
            date_str,
            f"{abs(sale['quantity']):.6f}",
            f"{abs(sale['remaining_quantity']):.6f}",
            f"{sale['price']:.2f}",
            f"{sale['total_czk']:.2f}",
            sale['status'],
            sale['method'],
            locked_str
        )
        
        # Tag for color coding
        tag = ""
        if sale['status'] == "Unpaired":
            tag = "unpaired"
        elif sale['status'] == "Fully Paired":
            tag = "paired"
        
        # Store sale ID using iid parameter
        item_id = self.sales_tree.insert('', 'end', iid=str(sale['id']), values=values, tags=(tag,))
        
        # Configure tags
        self.sales_tree.tag_configure("unpaired", background="#ffe6e6")
        self.sales_tree.tag_configure("paired", background="#e6ffe6")
    
    def _on_sale_selected(self, event) -> None:
        """Handle selection of a sale transaction."""
        selection = self.sales_tree.selection()
        if not selection:
            return
        
        # Get sale ID from item iid
        item = selection[0]
        sale_id = int(item)
        self.current_sale_id = sale_id
        
        # Load available lots for this sale
        self._load_available_lots(sale_id)
    
    def _load_available_lots(self, sale_trade_id: int) -> None:
        """Load available purchase lots for the selected sale."""
        # Clear existing
        for item in self.lots_tree.get_children():
            self.lots_tree.delete(item)
        
        try:
            # Get sale info
            sale = self.trades_repo.get_by_id(sale_trade_id)
            if not sale:
                return
            
            # Get available lots
            lots = self.pairings_repo.get_available_lots(sale['isin_id'], sale['timestamp'])
            
            for lot in lots:
                # Format holding period
                years = lot['holding_period_days'] / 365.25
                holding_str = f"{years:.1f} years ({lot['holding_period_days']} days)"
                
                # Time test icon
                timetest_icon = "✓" if lot['time_test_qualified'] else "✗"
                
                date_str = datetime.fromtimestamp(lot['timestamp']).strftime("%Y-%m-%d")
                
                values = (
                    date_str,
                    f"{lot['quantity']:.6f}",
                    f"{lot['available_quantity']:.6f}",
                    f"{lot['price_for_share']:.2f}",
                    holding_str,
                    timetest_icon
                )
                
                # Tag for color coding time-qualified lots
                tag = "timetest" if lot['time_test_qualified'] else ""
                # Store lot ID using iid parameter
                item_id = self.lots_tree.insert('', 'end', iid=str(lot['id']), values=values, tags=(tag,))
            
            # Configure tag for time-qualified lots
            self.lots_tree.tag_configure("timetest", background="#ccffcc")
            
        except Exception as e:
            self.logger.error(f"Error loading available lots: {e}", exc_info=True)
    
    def _load_current_pairings(self, start_timestamp: int = None, end_timestamp: int = None) -> None:
        """Load all pairings in the date range."""
        # Clear existing
        for item in self.pairings_tree.get_children():
            self.pairings_tree.delete(item)
        
        if not self.db.conn:
            self.logger.warning("No database connection - cannot load pairings")
            self.pairings_tree.insert('', 'end', values=(
                "", "", "", "No database connection", "", "", "", "", "", "", "", "", ""
            ))
            return
        
        # Use stored timestamps if not provided
        if start_timestamp is None:
            start_timestamp = self.current_start_timestamp
        if end_timestamp is None:
            end_timestamp = self.current_end_timestamp
            
        if start_timestamp is None or end_timestamp is None:
            self.logger.warning("No date range set - cannot load pairings")
            self.pairings_tree.insert('', 'end', values=(
                "", "", "", "No date range selected - use main filter", "", "", "", "", "", "", "", "", ""
            ))
            return
        
        try:
            # Log the date range being queried
            start_date_str = datetime.fromtimestamp(start_timestamp).strftime("%Y-%m-%d")
            end_date_str = datetime.fromtimestamp(end_timestamp).strftime("%Y-%m-%d")
            self.logger.info(f"Loading pairings for date range: {start_date_str} to {end_date_str}")
            
            # Single SQL query to fetch all pairing data with JOINs, filtered by sale date
            sql = """
                SELECT 
                    p.id,
                    p.quantity,
                    p.method,
                    p.holding_period_days,
                    p.time_test_qualified,
                    p.locked,
                    p.locked_reason,
                    st.timestamp as sale_timestamp,
                    pt.timestamp as purchase_timestamp,
                    s.name as security_name,
                    s.ticker,
                    pt.price_for_share as purchase_price,
                    pt.currency_of_price as purchase_currency,
                    pt.number_of_shares as purchase_qty,
                    pt.total_czk as purchase_total_czk,
                    st.price_for_share as sale_price,
                    st.currency_of_price as sale_currency,
                    st.number_of_shares as sale_qty,
                    st.total_czk as sale_total_czk
                FROM pairings p
                JOIN trades pt ON p.purchase_trade_id = pt.id
                JOIN trades st ON p.sale_trade_id = st.id
                JOIN securities s ON st.isin_id = s.id
                WHERE st.timestamp >= ? AND st.timestamp <= ?
                ORDER BY st.timestamp DESC, pt.timestamp
            """
            
            cur = self.db.conn.execute(sql, (start_timestamp, end_timestamp))
            pairings = cur.fetchall()
            
            self.logger.info(f"Loading pairings: found {len(pairings)} pairs in date range")
            
            if len(pairings) == 0:
                # Check if there are ANY pairings in the database
                count_sql = "SELECT COUNT(*) FROM pairings"
                count_cur = self.db.conn.execute(count_sql)
                total_count = count_cur.fetchone()[0]
                
                if total_count > 0:
                    # There are pairings, but none in this date range
                    self.pairings_tree.insert('', 'end', values=(
                        "", "", "", f"No pairings in date range ({total_count} total in database)", "", "", "", "", "", "", "", "", ""
                    ))
                else:
                    # No pairings at all
                    self.pairings_tree.insert('', 'end', values=(
                        "", "", "", "No pairings found - create some using the actions below", "", "", "", "", "", "", "", "", ""
                    ))
                return
            
            for row in pairings:
                pairing_id = row[0]
                quantity = row[1]
                method = row[2]
                holding_days = row[3]
                time_qualified = row[4]
                locked = row[5]
                locked_reason = row[6] if row[6] else ""
                sale_timestamp = row[7]
                purchase_timestamp = row[8]
                security_name = row[9]
                ticker = row[10]
                purchase_price = row[11]
                purchase_currency = row[12]
                purchase_qty = row[13]
                purchase_total_czk = row[14]
                sale_price = row[15]
                sale_currency = row[16]
                sale_qty = row[17]
                sale_total_czk = row[18]
                
                # Format dates
                purchase_date = datetime.fromtimestamp(purchase_timestamp).strftime("%Y-%m-%d")
                sale_date = datetime.fromtimestamp(sale_timestamp).strftime("%Y-%m-%d")
                
                # Format holding period
                years = holding_days / 365.25
                holding_str = f"{years:.1f} years ({holding_days} days)"
                
                # Time test icon
                timetest_icon = "✓" if time_qualified else "✗"
                
                # Locked icon
                locked_icon = "🔒" if locked else ""
                
                # Format prices with currency
                purchase_price_str = f"{purchase_price:.2f} {purchase_currency}"
                sale_price_str = f"{sale_price:.2f} {sale_currency}"
                
                # Calculate P&L in CZK (per-share basis * quantity paired)
                purchase_qty_abs = abs(purchase_qty) if purchase_qty else 1
                sale_qty_abs = abs(sale_qty) if sale_qty else 1
                
                purchase_czk_per_share = abs(purchase_total_czk) / purchase_qty_abs if purchase_qty_abs > 0 else 0
                sale_czk_per_share = abs(sale_total_czk) / sale_qty_abs if sale_qty_abs > 0 else 0
                
                pnl_czk = (sale_czk_per_share - purchase_czk_per_share) * abs(quantity)
                pnl_str = f"{pnl_czk:,.2f}"
                
                values = (
                    locked_icon,
                    sale_date,
                    purchase_date,
                    security_name,
                    ticker,
                    holding_str,
                    timetest_icon,
                    f"{abs(quantity):.6f}",
                    purchase_price_str,
                    sale_price_str,
                    pnl_str,
                    method,
                    locked_reason
                )
                
                # Store pairing ID using iid parameter
                item_id = self.pairings_tree.insert('', 'end', iid=str(pairing_id), values=values)
            
        except Exception as e:
            self.logger.error(f"Error loading pairings: {e}", exc_info=True)
    
    def _apply_method_to_selected(self) -> None:
        """Apply the selected method to the currently selected sale."""
        if not self.current_sale_id:
            messagebox.showwarning("No Selection", "Please select a sale transaction first.")
            return
        
        method = self.method_var.get()
        
        try:
            # Apply method
            if method == "FIFO":
                result = self.pairings_repo.apply_fifo(self.current_sale_id)
            elif method == "LIFO":
                result = self.pairings_repo.apply_lifo(self.current_sale_id)
            elif method == "MaxLose":
                result = self.pairings_repo.apply_max_lose(self.current_sale_id)
            elif method == "MaxProfit":
                result = self.pairings_repo.apply_max_profit(self.current_sale_id)
            else:
                messagebox.showerror("Error", f"Unknown method: {method}")
                return
            
            if result['success']:
                self.logger.info(f"Applied {method} to sale {self.current_sale_id}: "
                               f"{result['pairings_created']} pairings, "
                               f"{result['total_quantity_paired']} shares")
                messagebox.showinfo("Success", 
                                   f"Applied {method} method:\n"
                                   f"Pairings created: {result['pairings_created']}\n"
                                   f"Quantity paired: {result['total_quantity_paired']:.6f}")
                self.refresh_view()
            else:
                messagebox.showerror("Error", f"Failed to apply {method}:\n{result['error']}")
        
        except Exception as e:
            self.logger.error(f"Error applying method: {e}", exc_info=True)
            messagebox.showerror("Error", f"Failed to apply method: {e}")
    
    def _apply_method_to_interval(self) -> None:
        """Apply the selected method to all unpaired sales in the interval."""
        method = self.method_var.get()
        
        if not messagebox.askyesno("Confirm", 
                                   f"Apply {method} method to all unpaired sales in the interval?\n"
                                   f"This cannot be easily undone."):
            return
        
        try:
            # Get all unpaired sales
            sales_data = self._get_sales_in_interval(self.current_start_timestamp, 
                                                     self.current_end_timestamp)
            unpaired_sales = [s for s in sales_data if s['status'] in ["Unpaired", "Partially Paired"]]
            
            success_count = 0
            error_count = 0
            
            for sale in unpaired_sales:
                try:
                    if method == "FIFO":
                        result = self.pairings_repo.apply_fifo(sale['id'])
                    elif method == "LIFO":
                        result = self.pairings_repo.apply_lifo(sale['id'])
                    elif method == "MaxLose":
                        result = self.pairings_repo.apply_max_lose(sale['id'])
                    elif method == "MaxProfit":
                        result = self.pairings_repo.apply_max_profit(sale['id'])
                    
                    if result['success']:
                        success_count += 1
                    else:
                        error_count += 1
                        self.logger.warning(f"Failed to pair sale {sale['id']}: {result['error']}")
                
                except Exception as e:
                    error_count += 1
                    self.logger.error(f"Error pairing sale {sale['id']}: {e}", exc_info=True)
            
            self.logger.info(f"Batch pairing complete: {success_count} success, {error_count} errors")
            messagebox.showinfo("Batch Pairing Complete", 
                               f"Successfully paired: {success_count}\n"
                               f"Errors: {error_count}")
            self.refresh_view()
        
        except Exception as e:
            self.logger.error(f"Error in batch pairing: {e}", exc_info=True)
            messagebox.showerror("Error", f"Batch pairing failed: {e}")
    
    def _delete_selected_pairing(self) -> None:
        """Delete the currently selected pairing."""
        selection = self.pairings_tree.selection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a pairing to delete.")
            return
        
        # Get pairing ID from item iid
        item = selection[0]
        pairing_id = int(item)
        
        # Check if locked
        if self.pairings_repo.is_pairing_locked(pairing_id):
            messagebox.showerror("Locked", "This pairing is locked and cannot be deleted.")
            return
        
        if not messagebox.askyesno("Confirm", "Delete this pairing?"):
            return
        
        try:
            success = self.pairings_repo.delete_pairing(pairing_id)
            if success:
                self.logger.info(f"Deleted pairing {pairing_id}")
                messagebox.showinfo("Success", "Pairing deleted successfully.")
                self.refresh_view()
            else:
                messagebox.showerror("Error", "Failed to delete pairing.")
        
        except Exception as e:
            self.logger.error(f"Error deleting pairing: {e}", exc_info=True)
            messagebox.showerror("Error", f"Failed to delete pairing: {e}")
    
    def refresh_view(self) -> None:
        """Refresh all data in the view after changes."""
        # Reload everything with current timestamps
        if self.current_start_timestamp and self.current_end_timestamp:
            self._load_sales_in_interval()
            self._load_current_pairings(self.current_start_timestamp, self.current_end_timestamp)
            if self.current_sale_id:
                self._load_available_lots(self.current_sale_id)
    
    def clear_view(self) -> None:
        """Clear all items from the tree views."""
        if self.sales_tree:
            for item in self.sales_tree.get_children():
                self.sales_tree.delete(item)
        if self.lots_tree:
            for item in self.lots_tree.get_children():
                self.lots_tree.delete(item)
        if self.pairings_tree:
            for item in self.pairings_tree.get_children():
                self.pairings_tree.delete(item)
