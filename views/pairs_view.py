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
        self.start_date_entry = None
        self.end_date_entry = None
        self.security_filter_var = None
        self.status_filter_var = None
        
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
        # Configure parent frame
        parent_frame.grid_columnconfigure(0, weight=1)
        parent_frame.grid_rowconfigure(2, weight=1)
        
        # Create top section: Time interval selector
        self._create_interval_selector(parent_frame)
        
        # Create filter section
        self._create_filter_section(parent_frame)
        
        # Create main section: Sales list and details
        self._create_main_section(parent_frame)
        
        # Create bottom section: Action buttons
        self._create_action_section(parent_frame)
    
    def _create_interval_selector(self, parent_frame: ttk.Frame) -> None:
        """Create the time interval selector section."""
        interval_frame = ttk.LabelFrame(parent_frame, text="Time Interval", padding=10)
        interval_frame.grid(row=0, column=0, sticky="ew", padx=5, pady=5)
        
        # Start date
        ttk.Label(interval_frame, text="Start Date:").grid(row=0, column=0, padx=5, pady=2, sticky="w")
        self.start_date_entry = ttk.Entry(interval_frame, width=12)
        self.start_date_entry.grid(row=0, column=1, padx=5, pady=2)
        self.start_date_entry.insert(0, "2024-01-01")
        
        # End date
        ttk.Label(interval_frame, text="End Date:").grid(row=0, column=2, padx=5, pady=2, sticky="w")
        self.end_date_entry = ttk.Entry(interval_frame, width=12)
        self.end_date_entry.grid(row=0, column=3, padx=5, pady=2)
        self.end_date_entry.insert(0, datetime.now().strftime("%Y-%m-%d"))
        
        # Load button
        load_btn = ttk.Button(interval_frame, text="Load Sales", command=self._load_sales_in_interval)
        load_btn.grid(row=0, column=4, padx=10, pady=2)
        
        # Current year shortcut
        current_year_btn = ttk.Button(interval_frame, text="Current Year", 
                                       command=self._set_current_year)
        current_year_btn.grid(row=0, column=5, padx=5, pady=2)
        
        # Previous year shortcut
        prev_year_btn = ttk.Button(interval_frame, text="Previous Year", 
                                    command=self._set_previous_year)
        prev_year_btn.grid(row=0, column=6, padx=5, pady=2)
    
    def _create_filter_section(self, parent_frame: ttk.Frame) -> None:
        """Create the filter section."""
        filter_frame = ttk.LabelFrame(parent_frame, text="Filters", padding=10)
        filter_frame.grid(row=1, column=0, sticky="ew", padx=5, pady=5)
        
        # Security filter
        ttk.Label(filter_frame, text="Security:").grid(row=0, column=0, padx=5, pady=2, sticky="w")
        self.security_filter_var = tk.StringVar(value="All")
        security_combo = ttk.Combobox(filter_frame, textvariable=self.security_filter_var, 
                                      width=30, state="readonly")
        security_combo['values'] = ["All"]
        security_combo.grid(row=0, column=1, padx=5, pady=2)
        
        # Status filter
        ttk.Label(filter_frame, text="Pairing Status:").grid(row=0, column=2, padx=5, pady=2, sticky="w")
        self.status_filter_var = tk.StringVar(value="All")
        status_combo = ttk.Combobox(filter_frame, textvariable=self.status_filter_var, 
                                    width=20, state="readonly")
        status_combo['values'] = ["All", "Unpaired", "Partially Paired", "Fully Paired", "Locked"]
        status_combo.grid(row=0, column=3, padx=5, pady=2)
        
        # Apply filter button
        filter_btn = ttk.Button(filter_frame, text="Apply Filters", command=self._apply_filters)
        filter_btn.grid(row=0, column=4, padx=10, pady=2)
    
    def _create_main_section(self, parent_frame: ttk.Frame) -> None:
        """Create the main section with sales list and details panels."""
        main_frame = ttk.Frame(parent_frame)
        main_frame.grid(row=2, column=0, sticky="nsew", padx=5, pady=5)
        main_frame.grid_columnconfigure(0, weight=1)
        main_frame.grid_columnconfigure(1, weight=1)
        main_frame.grid_rowconfigure(0, weight=1)
        
        # Left panel: Sales list
        self._create_sales_panel(main_frame)
        
        # Right panel: Available lots and current pairings
        self._create_details_panel(main_frame)
    
    def _create_sales_panel(self, parent_frame: ttk.Frame) -> None:
        """Create the sales list panel."""
        sales_frame = ttk.LabelFrame(parent_frame, text="Sales Transactions", padding=5)
        sales_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
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
    
    def _create_details_panel(self, parent_frame: ttk.Frame) -> None:
        """Create the details panel with available lots and current pairings."""
        details_frame = ttk.Frame(parent_frame)
        details_frame.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
        details_frame.grid_columnconfigure(0, weight=1)
        details_frame.grid_rowconfigure(0, weight=1)
        details_frame.grid_rowconfigure(1, weight=1)
        
        # Top: Available purchase lots
        self._create_lots_panel(details_frame)
        
        # Bottom: Current pairings
        self._create_pairings_panel(details_frame)
    
    def _create_lots_panel(self, parent_frame: ttk.Frame) -> None:
        """Create the available purchase lots panel."""
        lots_frame = ttk.LabelFrame(parent_frame, text="Available Purchase Lots", padding=5)
        lots_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
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
        pairings_frame = ttk.LabelFrame(parent_frame, text="Current Pairings", padding=5)
        pairings_frame.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        pairings_frame.grid_columnconfigure(0, weight=1)
        pairings_frame.grid_rowconfigure(0, weight=1)
        
        # Pairings treeview
        columns = ("Purchase Date", "Quantity", "Method", "Holding", "TimeTest", "Locked")
        self.pairings_tree = ttk.Treeview(pairings_frame, columns=columns, show='headings', 
                                          selectmode='browse')
        self.pairings_tree.grid(row=0, column=0, sticky='nsew')
        
        # Configure columns
        self.pairings_tree.heading("Purchase Date", text="Purchase Date")
        self.pairings_tree.column("Purchase Date", anchor=tk.W, width=100)
        
        self.pairings_tree.heading("Quantity", text="Quantity Paired")
        self.pairings_tree.column("Quantity", anchor=tk.E, width=100)
        
        self.pairings_tree.heading("Method", text="Method")
        self.pairings_tree.column("Method", anchor=tk.W, width=100)
        
        self.pairings_tree.heading("Holding", text="Holding Period")
        self.pairings_tree.column("Holding", anchor=tk.W, width=120)
        
        self.pairings_tree.heading("TimeTest", text="⏰")
        self.pairings_tree.column("TimeTest", anchor=tk.CENTER, width=40)
        
        self.pairings_tree.heading("Locked", text="🔒")
        self.pairings_tree.column("Locked", anchor=tk.CENTER, width=40)
        
        # Scrollbars
        vsb = ttk.Scrollbar(pairings_frame, orient="vertical", command=self.pairings_tree.yview)
        vsb.grid(row=0, column=1, sticky='ns')
        self.pairings_tree.configure(yscrollcommand=vsb.set)
    
    def _create_action_section(self, parent_frame: ttk.Frame) -> None:
        """Create the action buttons section."""
        action_frame = ttk.LabelFrame(parent_frame, text="Actions", padding=10)
        action_frame.grid(row=3, column=0, sticky="ew", padx=5, pady=5)
        
        # Method selection
        ttk.Label(action_frame, text="Method:").grid(row=0, column=0, padx=5, pady=2)
        self.method_var = tk.StringVar(value="FIFO")
        method_combo = ttk.Combobox(action_frame, textvariable=self.method_var, 
                                    width=15, state="readonly")
        method_combo['values'] = ["FIFO", "LIFO", "MaxLose", "MaxProfit"]
        method_combo.grid(row=0, column=1, padx=5, pady=2)
        
        # Apply method button
        apply_btn = ttk.Button(action_frame, text="Apply Method to Selected Sale", 
                               command=self._apply_method_to_selected)
        apply_btn.grid(row=0, column=2, padx=10, pady=2)
        
        # Apply to interval button
        apply_interval_btn = ttk.Button(action_frame, text="Apply to All Unpaired in Interval", 
                                        command=self._apply_method_to_interval)
        apply_interval_btn.grid(row=0, column=3, padx=5, pady=2)
        
        # Delete pairing button
        delete_btn = ttk.Button(action_frame, text="Delete Selected Pairing", 
                                command=self._delete_selected_pairing)
        delete_btn.grid(row=0, column=4, padx=5, pady=2)
        
        # Refresh button
        refresh_btn = ttk.Button(action_frame, text="Refresh", command=self.refresh_view)
        refresh_btn.grid(row=0, column=5, padx=5, pady=2)
    
    def update_view(self, start_timestamp: int, end_timestamp: int) -> None:
        """
        Update the view with data for the given time range.
        
        Args:
            start_timestamp: Start of date range (Unix timestamp)
            end_timestamp: End of date range (Unix timestamp)
        """
        self.current_start_timestamp = start_timestamp
        self.current_end_timestamp = end_timestamp
        
        # Update date entries
        start_date = datetime.fromtimestamp(start_timestamp).strftime("%Y-%m-%d")
        end_date = datetime.fromtimestamp(end_timestamp).strftime("%Y-%m-%d")
        
        self.start_date_entry.delete(0, tk.END)
        self.start_date_entry.insert(0, start_date)
        
        self.end_date_entry.delete(0, tk.END)
        self.end_date_entry.insert(0, end_date)
        
        # Load sales
        self._load_sales_in_interval()
    
    def _load_sales_in_interval(self) -> None:
        """Load all sale transactions in the selected time interval."""
        try:
            # Parse dates
            start_date = self.start_date_entry.get()
            end_date = self.end_date_entry.get()
            
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            
            self.current_start_timestamp = int(start_dt.timestamp())
            self.current_end_timestamp = int(end_dt.timestamp())
            
            # Clear existing data
            self.clear_view()
            
            # Load sales from database
            sales_data = self._get_sales_in_interval(self.current_start_timestamp, 
                                                     self.current_end_timestamp)
            
            # Populate sales tree
            for sale in sales_data:
                self._insert_sale_row(sale)
            
            self.logger.info(f"Loaded {len(sales_data)} sales from {start_date} to {end_date}")
            
        except ValueError as e:
            messagebox.showerror("Date Error", f"Invalid date format. Use YYYY-MM-DD.\n{e}")
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
        
        item_id = self.sales_tree.insert('', 'end', values=values, tags=(tag,))
        
        # Store sale ID in item
        self.sales_tree.set(item_id, "#0", sale['id'])
        
        # Configure tags
        self.sales_tree.tag_configure("unpaired", background="#ffe6e6")
        self.sales_tree.tag_configure("paired", background="#e6ffe6")
    
    def _on_sale_selected(self, event) -> None:
        """Handle selection of a sale transaction."""
        selection = self.sales_tree.selection()
        if not selection:
            return
        
        # Get sale ID
        item = selection[0]
        sale_id = int(self.sales_tree.set(item, "#0"))
        self.current_sale_id = sale_id
        
        # Load details for this sale
        self._load_available_lots(sale_id)
        self._load_current_pairings(sale_id)
    
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
                item_id = self.lots_tree.insert('', 'end', values=values, tags=(tag,))
                
                # Store lot ID
                self.lots_tree.set(item_id, "#0", lot['id'])
            
            # Configure tag for time-qualified lots
            self.lots_tree.tag_configure("timetest", background="#ccffcc")
            
        except Exception as e:
            self.logger.error(f"Error loading available lots: {e}", exc_info=True)
    
    def _load_current_pairings(self, sale_trade_id: int) -> None:
        """Load existing pairings for the selected sale."""
        # Clear existing
        for item in self.pairings_tree.get_children():
            self.pairings_tree.delete(item)
        
        try:
            # Get pairings
            pairings = self.pairings_repo.get_pairings_for_purchase(sale_trade_id)
            
            for pairing in pairings:
                # Format holding period
                years = pairing['holding_period_days'] / 365.25
                holding_str = f"{years:.1f} years ({pairing['holding_period_days']} days)"
                
                # Time test icon
                timetest_icon = "✓" if pairing['time_test_qualified'] else "✗"
                
                # Locked icon
                locked_icon = "🔒" if pairing['locked'] else ""
                
                # Get purchase date
                purchase = self.trades_repo.get_by_id(pairing['purchase_trade_id'])
                purchase_date = datetime.fromtimestamp(purchase['timestamp']).strftime("%Y-%m-%d")
                
                values = (
                    purchase_date,
                    f"{pairing['quantity']:.6f}",
                    pairing['method'],
                    holding_str,
                    timetest_icon,
                    locked_icon
                )
                
                item_id = self.pairings_tree.insert('', 'end', values=values)
                
                # Store pairing ID
                self.pairings_tree.set(item_id, "#0", pairing['id'])
            
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
        
        # Get pairing ID
        item = selection[0]
        pairing_id = int(self.pairings_tree.set(item, "#0"))
        
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
    
    def _apply_filters(self) -> None:
        """Apply the current filter settings."""
        # TODO: Implement filtering logic
        self._load_sales_in_interval()
    
    def _set_current_year(self) -> None:
        """Set the interval to the current year."""
        year = datetime.now().year
        self.start_date_entry.delete(0, tk.END)
        self.start_date_entry.insert(0, f"{year}-01-01")
        self.end_date_entry.delete(0, tk.END)
        self.end_date_entry.insert(0, f"{year}-12-31")
    
    def _set_previous_year(self) -> None:
        """Set the interval to the previous year."""
        year = datetime.now().year - 1
        self.start_date_entry.delete(0, tk.END)
        self.start_date_entry.insert(0, f"{year}-01-01")
        self.end_date_entry.delete(0, tk.END)
        self.end_date_entry.insert(0, f"{year}-12-31")
    
    def refresh_view(self) -> None:
        """Refresh all data in the view after changes."""
        self._load_sales_in_interval()
        if self.current_sale_id:
            self._load_available_lots(self.current_sale_id)
            self._load_current_pairings(self.current_sale_id)
    
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
