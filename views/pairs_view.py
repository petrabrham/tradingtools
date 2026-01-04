"""
Pairs view for managing trade pairings between purchases and sales.

Allows users to view unpaired sales, available purchase lots, and create/manage pairings.
"""

from tkinter import ttk, messagebox, simpledialog
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
                                       selectmode='extended')
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
        
        # Create context menu for manual pairing
        self.lots_context_menu = tk.Menu(self.lots_tree, tearoff=0)
        self.lots_context_menu.add_command(label="Pair Manually", command=self._pair_manually)
        
        # Bind right-click to show context menu
        self.lots_tree.bind("<Button-3>", self._show_lots_context_menu)
    
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
                                          selectmode='extended')
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
        
        hsb = ttk.Scrollbar(pairings_frame, orient="horizontal", command=self.pairings_tree.xview)
        hsb.grid(row=1, column=0, sticky='ew')
        self.pairings_tree.configure(xscrollcommand=hsb.set)
        
        # Bind selection event
        self.pairings_tree.bind('<<TreeviewSelect>>', self._on_pairing_selected)
    
    def _create_action_section(self, parent_frame: ttk.Frame) -> None:
        """Create the action buttons section."""
        # Main container frame
        action_container = ttk.Frame(parent_frame)
        action_container.grid(row=2, column=0, columnspan=2, sticky="ew", padx=5, pady=5)
        action_container.grid_columnconfigure(0, weight=1)
        action_container.grid_columnconfigure(1, weight=1)
        action_container.grid_columnconfigure(2, weight=0)
        
        # LEFT: Sales Action
        sales_frame = ttk.LabelFrame(action_container, text="Sales Action", padding=10)
        sales_frame.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        
        # Row 0: Method selection and TimeTest checkbox
        ttk.Label(sales_frame, text="Method:").grid(row=0, column=0, padx=5, pady=2, sticky="w")
        self.method_var = tk.StringVar(value="FIFO")
        method_combo = ttk.Combobox(sales_frame, textvariable=self.method_var, 
                                    width=12, state="readonly")
        method_combo['values'] = ["FIFO", "LIFO", "MaxLose", "MaxProfit"]
        method_combo.grid(row=0, column=1, padx=5, pady=2, sticky="w")
        
        self.timetest_var = tk.BooleanVar(value=False)
        timetest_check = ttk.Checkbutton(sales_frame, text="Time Test Only (3+ years)", 
                                         variable=self.timetest_var)
        timetest_check.grid(row=0, column=2, padx=5, pady=2, sticky="w")
        
        # Row 1: Buttons
        pair_selected_btn = ttk.Button(sales_frame, text="Pair Selected Sale", 
                                       command=self._apply_method_to_selected)
        pair_selected_btn.grid(row=1, column=0, columnspan=2, padx=5, pady=2, sticky="ew")
        
        pair_all_btn = ttk.Button(sales_frame, text="Pair All Sales", 
                                  command=self._apply_method_to_interval)
        pair_all_btn.grid(row=1, column=2, padx=5, pady=2, sticky="ew")
        
        # MIDDLE: Pair Action
        pair_frame = ttk.LabelFrame(action_container, text="Pair Action", padding=10)
        pair_frame.grid(row=0, column=1, sticky="ew", padx=5)
        
        # Row 0: Lock reason editbox
        ttk.Label(pair_frame, text="Lock Reason:").grid(row=0, column=0, padx=5, pady=2, sticky="w")
        self.lock_reason_var = tk.StringVar(value="Manually locked")
        lock_reason_entry = ttk.Entry(pair_frame, textvariable=self.lock_reason_var, width=25)
        lock_reason_entry.grid(row=0, column=1, columnspan=3, padx=5, pady=2, sticky="ew")
        
        # Row 1: Buttons
        unpair_selected_btn = ttk.Button(pair_frame, text="Unpair Selected", 
                                         command=self._unpair_selected)
        unpair_selected_btn.grid(row=1, column=0, padx=2, pady=2, sticky="ew")
        
        unpair_all_btn = ttk.Button(pair_frame, text="Unpair All", 
                                     command=self._unpair_all)
        unpair_all_btn.grid(row=1, column=1, padx=2, pady=2, sticky="ew")
        
        lock_selected_btn = ttk.Button(pair_frame, text="Lock Selected", 
                                       command=self._lock_selected)
        lock_selected_btn.grid(row=1, column=2, padx=2, pady=2, sticky="ew")
        
        lock_all_btn = ttk.Button(pair_frame, text="Lock All", 
                                  command=self._lock_all)
        lock_all_btn.grid(row=1, column=3, padx=2, pady=2, sticky="ew")
        
        unlock_selected_btn = ttk.Button(pair_frame, text="Unlock Selected", 
                                         command=self._unlock_selected)
        unlock_selected_btn.grid(row=1, column=4, padx=2, pady=2, sticky="ew")
        
        unlock_all_btn = ttk.Button(pair_frame, text="Unlock All", 
                                     command=self._unlock_all)
        unlock_all_btn.grid(row=1, column=5, padx=2, pady=2, sticky="ew")
        
        # RIGHT: Refresh
        refresh_frame = ttk.LabelFrame(action_container, text="Refresh", padding=10)
        refresh_frame.grid(row=0, column=2, sticky="ew", padx=(5, 0))
        
        # Refresh button
        refresh_btn = ttk.Button(refresh_frame, text="Refresh", command=self.refresh_view)
        refresh_btn.grid(row=0, column=0, padx=5, pady=2, sticky="ew")
    
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
        """
        Load all SELL transactions in the selected time interval that match the date filter.
        Only transactions with timestamps between current_start_timestamp and current_end_timestamp are included.
        """
        try:
            # Check if timestamps are set
            if self.current_start_timestamp is None or self.current_end_timestamp is None:
                self.logger.warning("Cannot load sales - no date filter set")
                return
            
            # Clear existing sales data only
            for item in self.sales_tree.get_children():
                self.sales_tree.delete(item)
            
            # Also clear lots tree since no sale is selected
            for item in self.lots_tree.get_children():
                self.lots_tree.delete(item)
            
            # Reset current sale selection
            self.current_sale_id = None
            
            # Load sales from database with date filter
            start_date = datetime.fromtimestamp(self.current_start_timestamp).strftime("%Y-%m-%d")
            end_date = datetime.fromtimestamp(self.current_end_timestamp).strftime("%Y-%m-%d")
            self.logger.info(f"Loading sales transactions for date range: {start_date} to {end_date}")
            
            sales_data = self._get_sales_in_interval(self.current_start_timestamp, 
                                                     self.current_end_timestamp)
            
            if not sales_data:
                return
            
            # Populate sales tree with filtered data
            for sale in sales_data:
                self._insert_sale_row(sale)
            
            self.logger.info(f"Loaded {len(sales_data)} sales from {start_date} to {end_date}")
            
        except Exception as e:
            self.logger.error(f"Error loading sales: {e}", exc_info=True)
            messagebox.showerror("Error", f"Failed to load sales: {e}")
    
    def _get_sales_in_interval(self, start_timestamp: int, end_timestamp: int) -> List[Dict]:
        """
        Get all SELL trades in the time interval with pairing status.
        
        Args:
            start_timestamp: Start of date range (Unix timestamp)
            end_timestamp: End of date range (Unix timestamp)
            
        Returns:
            List of sale dictionaries with pairing information
        """
        if not self.db.conn:
            self.logger.warning("No database connection - cannot load sales")
            return []
        
        # Update repository connections if needed
        if not self.pairings_repo.conn:
            self.pairings_repo.conn = self.db.conn
        
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
            ORDER BY s.name, t.timestamp ASC
        """
        
        cur = self.db.conn.execute(sql, (TradeType.SELL, start_timestamp, end_timestamp))
        rows = cur.fetchall()
        
        result = []
        for row in rows:
            sale_id = row[0]
            
            # Determine status from remaining quantity
            remaining_qty = abs(row[5])
            total_qty = abs(row[4])
            
            # Get pairing info (with connection check)
            pairings = []
            is_locked = False
            method = ""
            
            if self.db.conn:
                try:
                    pairings = self.pairings_repo.get_pairings_for_purchase(sale_id)
                    is_locked = self.pairings_repo.is_pairing_locked(sale_id) if pairings else False
                    if pairings:
                        method = self.pairings_repo.derive_method_combination(sale_id)
                except Exception as e:
                    self.logger.warning(f"Error getting pairing info for sale {sale_id}: {e}")
            
            # Determine status
            if remaining_qty < 1e-10:
                status = "Fully Paired"
            elif remaining_qty >= total_qty - 1e-10:
                status = "Unpaired"
            else:
                status = "Partially Paired"
            
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
        
        # Select matching pairings in the pairings tree
        self._select_pairings_for_sale(sale_id)
    
    def _select_pairings_for_sale(self, sale_id: int) -> None:
        """Select all pairings in the pairings tree that belong to the given sale."""
        # Clear current selection
        self.pairings_tree.selection_remove(*self.pairings_tree.selection())
        
        # Find and select all items tagged with this sale_id
        tag = f"sale_{sale_id}"
        matching_items = []
        
        for item in self.pairings_tree.get_children():
            item_tags = self.pairings_tree.item(item, 'tags')
            if tag in item_tags:
                matching_items.append(item)
        
        if matching_items:
            # Select all matching items
            self.pairings_tree.selection_set(matching_items)
            # Scroll to the first selected item
            self.pairings_tree.see(matching_items[0])
    
    def _on_pairing_selected(self, event) -> None:
        """Handle selection of a pairing - select corresponding purchase lot."""
        selection = self.pairings_tree.selection()
        if not selection:
            return
        
        # Clear current lot selection
        self.lots_tree.selection_remove(*self.lots_tree.selection())
        
        # Collect all unique purchase_trade_ids from selected pairings
        purchase_ids = set()
        for item in selection:
            item_tags = self.pairings_tree.item(item, 'tags')
            for tag in item_tags:
                if tag.startswith('purchase_'):
                    purchase_id = int(tag.replace('purchase_', ''))
                    purchase_ids.add(purchase_id)
        
        # Select matching lots in the lots tree
        matching_lots = []
        for item in self.lots_tree.get_children():
            item_id = self.lots_tree.item(item, 'text')
            try:
                lot_id = int(item) if item else None
                if lot_id in purchase_ids:
                    matching_lots.append(item)
            except (ValueError, TypeError):
                continue
        
        if matching_lots:
            self.lots_tree.selection_set(matching_lots)
            # Scroll to the first selected lot
            self.lots_tree.see(matching_lots[0])
    
    def _load_available_lots(self, sale_trade_id: int) -> None:
        """Load available purchase lots for the selected sale."""
        # Clear existing
        for item in self.lots_tree.get_children():
            self.lots_tree.delete(item)
        
        if not self.db.conn:
            self.logger.warning("No database connection - cannot load available lots")
            return
        
        # Update repository connections if needed
        if not self.trades_repo.conn:
            self.trades_repo.conn = self.db.conn
        if not self.pairings_repo.conn:
            self.pairings_repo.conn = self.db.conn
        
        try:
            # Get sale info
            sale = self.trades_repo.get_by_id(sale_trade_id)
            if not sale:
                self.logger.warning(f"Sale {sale_trade_id} not found in database")
                return
            
            # Log the raw sale data for debugging
            # self.logger.info(f"Raw sale data for {sale_trade_id}: {sale}")
            
            # Convert tuple to dict if needed
            if isinstance(sale, tuple):
                # Trade row structure from get_by_id:
                # Index 0: id (231)
                # Index 1: timestamp (1733900413)
                # Index 2: isin_id (11) <-- This is the SECURITY ID
                # Index 3: transaction_id ('EOF24806460464')
                # Index 4: trade_type (2)
                sale_timestamp = sale[1]  # timestamp is at index 1
                sale_isin_id = sale[2]     # isin_id is at index 2 (not 4!)
            else:
                sale_isin_id = sale['isin_id']
                sale_timestamp = sale['timestamp']
            
            sale_date = datetime.fromtimestamp(sale_timestamp).strftime("%Y-%m-%d %H:%M:%S")
            self.logger.info(f"Loading lots for sale {sale_trade_id}: isin_id={sale_isin_id}, timestamp={sale_timestamp} ({sale_date})")
            
            # Get available lots
            lots = self.pairings_repo.get_available_lots(sale_isin_id, sale_timestamp)
            
            self.logger.info(f"Found {len(lots)} available purchase lots for sale {sale_trade_id}")
            
            if not lots:
                return
            
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
            # Show error message in the tree
            self.lots_tree.insert('', 'end', values=(
                f"Error: {str(e)}", "", "", "", "", ""
            ))
    
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
                    st.total_czk as sale_total_czk,
                    p.sale_trade_id,
                    p.purchase_trade_id
                FROM pairings p
                JOIN trades pt ON p.purchase_trade_id = pt.id
                JOIN trades st ON p.sale_trade_id = st.id
                JOIN securities s ON st.isin_id = s.id
                WHERE st.timestamp >= ? AND st.timestamp <= ?
                ORDER BY st.timestamp ASC, pt.timestamp ASC
            """
            
            cur = self.db.conn.execute(sql, (start_timestamp, end_timestamp))
            pairings = cur.fetchall()
            
            self.logger.info(f"Loading pairings: found {len(pairings)} pairs in date range")
            
            if len(pairings) == 0:
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
                sale_trade_id = row[19]
                purchase_trade_id = row[20]
                
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
                
                # Store pairing ID using iid parameter and sale_trade_id, purchase_trade_id as tags
                item_id = self.pairings_tree.insert('', 'end', iid=str(pairing_id), values=values, tags=(f"sale_{sale_trade_id}", f"purchase_{purchase_trade_id}"))
            
        except Exception as e:
            self.logger.error(f"Error loading pairings: {e}", exc_info=True)
    
    def _apply_method_to_selected(self) -> None:
        """Apply the selected method to all currently selected sales."""
        # Get all selected sales from the tree
        selection = self.sales_tree.selection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select one or more sale transactions first.")
            return
        
        method = self.method_var.get()
        
        # Get sale IDs in order (as they appear in the tree, which is already sorted oldest first)
        sale_ids = [int(item) for item in selection]
        
        # Confirm if multiple sales are selected
        if len(sale_ids) > 1:
            if not messagebox.askyesno("Confirm", 
                                       f"Apply {method} method to {len(sale_ids)} selected sales?\n"
                                       f"Sales will be processed in order from oldest to newest."):
                return
        
        # Update repository connections if needed
        if not self.pairings_repo.conn:
            self.pairings_repo.conn = self.db.conn
        if not self.trades_repo.conn:
            self.trades_repo.conn = self.db.conn
        # Also update the nested trades_repo inside pairings_repo
        if not self.pairings_repo.trades_repo.conn:
            self.pairings_repo.trades_repo.conn = self.db.conn
        
        success_count = 0
        error_count = 0
        total_pairings = 0
        total_quantity = 0.0
        
        try:
            for sale_id in sale_ids:
                try:
                    # Apply method based on selection
                    if method == "FIFO":
                        result = self.pairings_repo.apply_fifo(sale_id)
                    elif method == "LIFO":
                        result = self.pairings_repo.apply_lifo(sale_id)
                    elif method == "MaxLose":
                        result = self.pairings_repo.apply_max_lose(sale_id)
                    elif method == "MaxProfit":
                        result = self.pairings_repo.apply_max_profit(sale_id)
                    else:
                        messagebox.showerror("Error", f"Unknown method: {method}")
                        return
                    
                    if result['success']:
                        success_count += 1
                        total_pairings += result['pairings_created']
                        total_quantity += result['total_quantity_paired']
                        self.logger.info(f"Applied {method} to sale {sale_id}: "
                                       f"{result['pairings_created']} pairings, "
                                       f"{result['total_quantity_paired']} shares")
                    else:
                        error_count += 1
                        self.logger.warning(f"Failed to apply {method} to sale {sale_id}: {result.get('error', 'Unknown error')}")
                
                except Exception as e:
                    error_count += 1
                    self.logger.error(f"Error applying method to sale {sale_id}: {e}", exc_info=True)
            
            # Show summary
            if len(sale_ids) == 1:
                # Single sale - show detailed result
                if success_count == 0:
                    messagebox.showerror("Error", f"Failed to apply {method} method")
            else:
                # Multiple sales - show summary
                self.logger.info(f"Batch pairing complete: {success_count} success, {error_count} errors, "
                               f"{total_pairings} total pairings, {total_quantity:.6f} total quantity")
             
            self.refresh_view()
        
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
    
    def _unpair_selected(self) -> None:
        """Delete the currently selected pairing(s)."""
        selection = self.pairings_tree.selection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select pairing(s) to delete.")
            return
        
        # Update repository connections if needed
        if not self.trades_repo.conn:
            self.trades_repo.conn = self.db.conn
        if not self.pairings_repo.conn:
            self.pairings_repo.conn = self.db.conn
        # Also update the trades_repo inside pairings_repo
        if not self.pairings_repo.trades_repo.conn:
            self.pairings_repo.trades_repo.conn = self.db.conn
        
        # Confirm deletion
        if len(selection) == 1:
            confirm_msg = "Delete this pairing?"
        else:
            confirm_msg = f"Delete {len(selection)} pairings?"
        
        if not messagebox.askyesno("Confirm", confirm_msg):
            return
        
        success_count = 0
        locked_count = 0
        error_count = 0
        
        try:
            for item in selection:
                pairing_id = int(item)
                
                # Check if locked
                if self.pairings_repo.is_pairing_locked(pairing_id):
                    locked_count += 1
                    continue
                
                try:
                    if self.pairings_repo.delete_pairing(pairing_id):
                        success_count += 1
                        self.logger.info(f"Deleted pairing {pairing_id}")
                    else:
                        error_count += 1
                except Exception as e:
                    self.logger.error(f"Error deleting pairing {pairing_id}: {e}")
                    error_count += 1
            
            self.logger.info(f"Unpair selected: {success_count} deleted, {locked_count} locked, {error_count} errors")
            
            self.refresh_view()
        
        except Exception as e:
            self.logger.error(f"Error deleting pairing: {e}", exc_info=True)
            messagebox.showerror("Error", f"Failed to delete pairing: {e}")
    
    def _unpair_all(self) -> None:
        """Delete all pairings in the current view."""
        all_pairings = self.pairings_tree.get_children()
        if not all_pairings:
            messagebox.showwarning("No Pairings", "No pairings to delete.")
            return
        
        if not messagebox.askyesno("Confirm", 
                                   f"Delete all {len(all_pairings)} pairings?\n"
                                   f"This cannot be easily undone."):
            return
        
        # Update repository connections if needed
        if not self.trades_repo.conn:
            self.trades_repo.conn = self.db.conn
        if not self.pairings_repo.conn:
            self.pairings_repo.conn = self.db.conn
        # Also update the trades_repo inside pairings_repo
        if not self.pairings_repo.trades_repo.conn:
            self.pairings_repo.trades_repo.conn = self.db.conn
        
        success_count = 0
        locked_count = 0
        error_count = 0
        
        try:
            for item in all_pairings:
                pairing_id = int(item)
                
                # Skip locked pairings
                if self.pairings_repo.is_pairing_locked(pairing_id):
                    locked_count += 1
                    continue
                
                try:
                    if self.pairings_repo.delete_pairing(pairing_id):
                        success_count += 1
                    else:
                        error_count += 1
                except Exception as e:
                    self.logger.error(f"Error deleting pairing {pairing_id}: {e}")
                    error_count += 1
            
            self.logger.info(f"Unpair all: {success_count} deleted, {locked_count} locked, {error_count} errors")
            self.refresh_view()
        
        except Exception as e:
            self.logger.error(f"Error in unpair all: {e}", exc_info=True)
            messagebox.showerror("Error", f"Unpair all failed: {e}")
    
    def _lock_selected(self) -> None:
        """Lock the selected pairing(s)."""
        selection = self.pairings_tree.selection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select pairing(s) to lock.")
            return
        
        # Update repository connections if needed
        if not self.pairings_repo.conn:
            self.pairings_repo.conn = self.db.conn
        
        reason = self.lock_reason_var.get().strip() or "Manually locked"
        success_count = 0
        error_count = 0
        
        try:
            for item in selection:
                pairing_id = int(item)
                
                try:
                    if self.pairings_repo.lock_pairing(pairing_id, reason):
                        success_count += 1
                    else:
                        error_count += 1
                except Exception as e:
                    self.logger.error(f"Error locking pairing {pairing_id}: {e}")
                    error_count += 1
            
            self.logger.info(f"Lock selected: {success_count} locked, {error_count} errors")
            
            if len(selection) == 1:
                if success_count == 1:
                    messagebox.showinfo("Success", "Pairing locked successfully.")
                else:
                    messagebox.showerror("Error", "Failed to lock pairing.")

            self.refresh_view()
        
        except Exception as e:
            self.logger.error(f"Error in lock selected: {e}", exc_info=True)
            messagebox.showerror("Error", f"Lock selected failed: {e}")
    
    def _lock_all(self) -> None:
        """Lock all pairings in the current view."""
        all_pairings = self.pairings_tree.get_children()
        if not all_pairings:
            messagebox.showwarning("No Pairings", "No pairings to lock.")
            return
        
        if not messagebox.askyesno("Confirm", 
                                   f"Lock all {len(all_pairings)} pairings?"):
            return
        
        # Update repository connections if needed
        if not self.pairings_repo.conn:
            self.pairings_repo.conn = self.db.conn
        
        reason = self.lock_reason_var.get().strip() or "Bulk locked"
        success_count = 0
        already_locked_count = 0
        error_count = 0
        
        try:
            for item in all_pairings:
                pairing_id = int(item)
                
                # Check if already locked
                if self.pairings_repo.is_pairing_locked(pairing_id):
                    already_locked_count += 1
                    continue
                
                try:
                    if self.pairings_repo.lock_pairing(pairing_id, reason):
                        success_count += 1
                    else:
                        error_count += 1
                except Exception as e:
                    self.logger.error(f"Error locking pairing {pairing_id}: {e}")
                    error_count += 1
            
            self.logger.info(f"Lock all: {success_count} locked, {already_locked_count} already locked, {error_count} errors")
            self.refresh_view()
        
        except Exception as e:
            self.logger.error(f"Error in lock all: {e}", exc_info=True)
            messagebox.showerror("Error", f"Lock all failed: {e}")
    
    def _unlock_selected(self) -> None:
        """Unlock the selected pairing(s)."""
        selection = self.pairings_tree.selection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select pairing(s) to unlock.")
            return
        
        # Update repository connections if needed
        if not self.pairings_repo.conn:
            self.pairings_repo.conn = self.db.conn
        
        success_count = 0
        error_count = 0
        
        try:
            for item in selection:
                pairing_id = int(item)
                
                try:
                    if self.pairings_repo.unlock_pairing(pairing_id):
                        success_count += 1
                    else:
                        error_count += 1
                except Exception as e:
                    self.logger.error(f"Error unlocking pairing {pairing_id}: {e}")
                    error_count += 1
            
            self.logger.info(f"Unlock selected: {success_count} unlocked, {error_count} errors")
            
            if len(selection) == 1:
                if success_count == 1:
                    messagebox.showinfo("Success", "Pairing unlocked successfully.")
                else:
                    messagebox.showerror("Error", "Failed to unlock pairing.")

            self.refresh_view()
        
        except Exception as e:
            self.logger.error(f"Error in unlock selected: {e}", exc_info=True)
            messagebox.showerror("Error", f"Unlock selected failed: {e}")
    
    def _unlock_all(self) -> None:
        """Unlock all pairings in the current view."""
        all_pairings = self.pairings_tree.get_children()
        if not all_pairings:
            messagebox.showwarning("No Pairings", "No pairings to unlock.")
            return
        
        if not messagebox.askyesno("Confirm", 
                                   f"Unlock all {len(all_pairings)} pairings?"):
            return
        
        # Update repository connections if needed
        if not self.pairings_repo.conn:
            self.pairings_repo.conn = self.db.conn
        
        success_count = 0
        already_unlocked_count = 0
        error_count = 0
        
        try:
            for item in all_pairings:
                pairing_id = int(item)
                
                # Check if already unlocked
                if not self.pairings_repo.is_pairing_locked(pairing_id):
                    already_unlocked_count += 1
                    continue
                
                try:
                    if self.pairings_repo.unlock_pairing(pairing_id):
                        success_count += 1
                    else:
                        error_count += 1
                except Exception as e:
                    self.logger.error(f"Error unlocking pairing {pairing_id}: {e}")
                    error_count += 1
            
            self.logger.info(f"Unlock all: {success_count} unlocked, {already_unlocked_count} already unlocked, {error_count} errors")
            self.refresh_view()
        
        except Exception as e:
            self.logger.error(f"Error in unlock all: {e}", exc_info=True)
            messagebox.showerror("Error", f"Unlock all failed: {e}")
    
    def refresh_view(self) -> None:
        """Refresh all data in the view after changes."""
        # Reload everything with current timestamps
        if self.current_start_timestamp and self.current_end_timestamp:
            self._load_sales_in_interval()
            self._load_current_pairings(self.current_start_timestamp, self.current_end_timestamp)
            if self.current_sale_id:
                self._load_available_lots(self.current_sale_id)
    
    def _show_lots_context_menu(self, event) -> None:
        """Show context menu for lots tree on right-click."""
        # Select the item under the cursor
        item = self.lots_tree.identify_row(event.y)
        if item:
            self.lots_tree.selection_set(item)
            self.lots_context_menu.post(event.x_root, event.y_root)
    
    def _pair_manually(self) -> None:
        """Manually pair selected sale with selected purchase lot."""
        # Check if a sale is selected
        if not self.current_sale_id:
            messagebox.showwarning("No Sale Selected", "Please select a sale transaction first.")
            return
        
        # Check if a lot is selected
        lot_selection = self.lots_tree.selection()
        if not lot_selection:
            messagebox.showwarning("No Lot Selected", "Please select a purchase lot to pair with.")
            return
        
        # Get lot ID from selection
        lot_item = lot_selection[0]
        lot_id = int(lot_item)
        
        # Get lot details from tree to check available quantity
        lot_values = self.lots_tree.item(lot_item, 'values')
        if not lot_values or len(lot_values) < 3:
            messagebox.showerror("Error", "Could not retrieve lot information.")
            return
        
        available_qty_str = lot_values[2]  # Available Qty column
        try:
            purchase_available_qty = float(available_qty_str)
        except ValueError:
            messagebox.showerror("Error", f"Invalid available quantity: {available_qty_str}")
            return
        
        # Check if lot has available quantity
        if purchase_available_qty <= 0:
            messagebox.showwarning("No Available Quantity", "This lot has no available quantity for pairing.")
            return
        
        # Get sale's remaining quantity from the sales tree
        sale_item = str(self.current_sale_id)
        if not self.sales_tree.exists(sale_item):
            messagebox.showerror("Error", "Selected sale not found in sales table.")
            return
        
        sale_values = self.sales_tree.item(sale_item, 'values')
        if not sale_values or len(sale_values) < 5:
            messagebox.showerror("Error", "Could not retrieve sale information.")
            return
        
        sale_remaining_str = sale_values[4]  # Remaining column (index 4)
        try:
            sale_remaining_qty = abs(float(sale_remaining_str))
        except ValueError:
            messagebox.showerror("Error", f"Invalid sale remaining quantity: {sale_remaining_str}")
            return
        
        # Calculate maximum quantity that can be paired (minimum of both)
        max_pair_qty = min(purchase_available_qty, sale_remaining_qty)
        
        # Ask user for quantity to pair
        quantity = simpledialog.askfloat(
            "Pair Manually",
            f"Enter quantity to pair:\n"
            f"Purchase available: {purchase_available_qty:.6f}\n"
            f"Sale remaining: {sale_remaining_qty:.6f}\n"
            f"Max pairable: {max_pair_qty:.6f}",
            initialvalue=max_pair_qty,
            minvalue=0.000001,
            maxvalue=max_pair_qty
        )
        
        if quantity is None:  # User cancelled
            return
        
        # Update repository connections if needed
        if not self.pairings_repo.conn:
            self.pairings_repo.conn = self.db.conn
        if not self.trades_repo.conn:
            self.trades_repo.conn = self.db.conn
        # Also update the nested trades_repo inside pairings_repo
        if not self.pairings_repo.trades_repo.conn:
            self.pairings_repo.trades_repo.conn = self.db.conn
        
        try:
            # Create manual pairing
            result = self.pairings_repo.create_manual_pairing(
                sale_trade_id=self.current_sale_id,
                purchase_trade_id=lot_id,
                quantity=quantity
            )
            
            if result.get('success'):
                self.logger.info(f"Manual pairing created: sale {self.current_sale_id} with purchase {lot_id}, qty {quantity}")
                messagebox.showinfo("Success", f"Successfully paired {quantity:.6f} shares.")
                self.refresh_view()
            else:
                error_msg = result.get('error', 'Unknown error')
                messagebox.showerror("Error", f"Failed to create pairing:\n{error_msg}")
        
        except Exception as e:
            self.logger.error(f"Error creating manual pairing: {e}", exc_info=True)
            messagebox.showerror("Error", f"Failed to create pairing: {e}")
    
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
