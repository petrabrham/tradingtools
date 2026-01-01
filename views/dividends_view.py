"""
Dividends View - Hierarchical display of dividend income with country-based tax calculations
"""
import tkinter as tk
from tkinter import ttk
from .base_view import BaseView


class DividendsView(BaseView):
    """View for displaying dividend income with hierarchical structure and country summary."""
    
    def __init__(self, db_manager, root, tax_rates_loader, country_resolver, use_json_tax_rates_var):
        """
        Initialize the DividendsView.
        
        Args:
            db_manager: DatabaseManager instance
            root: Root tk widget for event binding
            tax_rates_loader: TaxRatesLoader instance for JSON-based calculations
            country_resolver: CountryResolver instance for country detection
            use_json_tax_rates_var: BooleanVar controlling tax calculation mode
        """
        super().__init__(db_manager)
        self.root = root
        self.tax_rates_loader = tax_rates_loader
        self.country_resolver = country_resolver
        self.use_json_tax_rates = use_json_tax_rates_var
        
        self.tree = None
        self.country_summary_tree = None
        
        # Summary variables (will be set before create_view is called)
        self.dividend_gross_var = None
        self.dividend_tax_var = None
        self.dividend_net_var = None
    
    def set_summary_variables(self, dividend_gross_var, dividend_tax_var, dividend_net_var):
        """
        Set the StringVar objects for summary display.
        
        Args:
            dividend_gross_var: StringVar for total gross income
            dividend_tax_var: StringVar for total withholding tax
            dividend_net_var: StringVar for total net income
        """
        self.dividend_gross_var = dividend_gross_var
        self.dividend_tax_var = dividend_tax_var
        self.dividend_net_var = dividend_net_var
    
    def create_view(self, parent_frame):
        """
        Create the dividends view with three sections:
        1. Hierarchical treeview (top)
        2. Country summary table (middle)
        3. Total summary panel (bottom)
        
        Args:
            parent_frame: Parent ttk.Frame to contain the view
        """
        parent_frame.grid_columnconfigure(0, weight=1)
        parent_frame.grid_rowconfigure(0, weight=1) # Treeview (expands) 
        parent_frame.grid_rowconfigure(1, weight=0) # Country Summary Table (fixed height)
        parent_frame.grid_rowconfigure(2, weight=0) # Total Summary Panel (fixed height)

        # --- Top Part: Treeview for Dividends (Row 0) ---
        treeview_frame = ttk.Frame(parent_frame)
        treeview_frame.grid(row=0, column=0, sticky="nsew")
        
        # Configure frame for treeview and scrollbars
        treeview_frame.grid_columnconfigure(0, weight=1)
        treeview_frame.grid_rowconfigure(0, weight=1)
        
        # Create Treeview with tree structure visible (show='tree headings')
        dividend_columns = ("Name", "Ticker", "Date", "Price per Share", "Gross Income (CZK)", "Withholding Tax (CZK)", "Net Income (CZK)")
        tree = ttk.Treeview(treeview_frame, columns=dividend_columns, show='tree headings')
        tree.grid(row=0, column=0, sticky='nsew')

        # Store reference
        self.tree = tree

        # Configure column headings and widths
        tree.heading("#0", text="")  # Tree column (for expand/collapse icons)
        tree.column("#0", width=30, stretch=False)  # Narrow column for tree icons

        tree.heading("Name", text="Name")
        tree.column("Name", anchor=tk.W, width=200)

        tree.heading("Ticker", text="Ticker")
        tree.column("Ticker", anchor=tk.W, width=100)

        tree.heading("Date", text="Date")
        tree.column("Date", anchor=tk.W, width=100)

        tree.heading("Price per Share", text="Price per Share")
        tree.column("Price per Share", anchor=tk.E, width=120)

        tree.heading("Gross Income (CZK)", text="Gross Income (CZK)")
        tree.column("Gross Income (CZK)", anchor=tk.E, width=130)

        tree.heading("Withholding Tax (CZK)", text="Withholding Tax (CZK)")
        tree.column("Withholding Tax (CZK)", anchor=tk.E, width=150)

        tree.heading("Net Income (CZK)", text="Net Income (CZK)")
        tree.column("Net Income (CZK)", anchor=tk.E, width=130)

        # Add scrollbars
        vsb = ttk.Scrollbar(treeview_frame, orient="vertical", command=tree.yview)
        vsb.grid(row=0, column=1, sticky='ns')
        tree.configure(yscrollcommand=vsb.set)

        hsb = ttk.Scrollbar(treeview_frame, orient="horizontal", command=tree.xview)
        hsb.grid(row=1, column=0, sticky='ew')
        tree.configure(xscrollcommand=hsb.set)

        # Bind Ctrl+C for clipboard copy
        tree.bind("<Control-c>", lambda e: self.copy_to_clipboard(e, self.root))
        tree.bind("<Control-C>", lambda e: self.copy_to_clipboard(e, self.root))

        # --- Middle Part: Country Summary Table (Row 1) ---
        country_summary_frame = ttk.LabelFrame(parent_frame, text="Summary by Country")
        country_summary_frame.grid(row=1, column=0, sticky="ew", pady=(5, 0), padx=2)
        
        country_summary_frame.grid_columnconfigure(0, weight=1)
        country_summary_frame.grid_rowconfigure(0, weight=1)
        
        # Create Treeview for country summary
        country_columns = ("Country", "Gross dividend (CZK)", "Rate of withholding tax (%)", "Withholding tax (CZK)", "Net dividends (CZK)")
        self.country_summary_tree = ttk.Treeview(country_summary_frame, columns=country_columns, show='headings', height=6)
        self.country_summary_tree.grid(row=0, column=0, sticky='nsew')
        
        # Configure columns
        self.country_summary_tree.heading("Country", text="Country")
        self.country_summary_tree.column("Country", anchor=tk.W, width=150)
        
        self.country_summary_tree.heading("Gross dividend (CZK)", text="Gross dividend (CZK)")
        self.country_summary_tree.column("Gross dividend (CZK)", anchor=tk.E, width=150)
        
        self.country_summary_tree.heading("Rate of withholding tax (%)", text="Rate of withholding tax (%)")
        self.country_summary_tree.column("Rate of withholding tax (%)", anchor=tk.E, width=180)
        
        self.country_summary_tree.heading("Withholding tax (CZK)", text="Withholding tax (CZK)")
        self.country_summary_tree.column("Withholding tax (CZK)", anchor=tk.E, width=150)
        
        self.country_summary_tree.heading("Net dividends (CZK)", text="Net dividends (CZK)")
        self.country_summary_tree.column("Net dividends (CZK)", anchor=tk.E, width=150)
        
        # Add scrollbar
        country_vsb = ttk.Scrollbar(country_summary_frame, orient="vertical", command=self.country_summary_tree.yview)
        country_vsb.grid(row=0, column=1, sticky='ns')
        self.country_summary_tree.configure(yscrollcommand=country_vsb.set)
        
        # Bind Ctrl+C for clipboard copy
        self.country_summary_tree.bind("<Control-c>", lambda e: self.copy_to_clipboard(e, self.root))
        self.country_summary_tree.bind("<Control-C>", lambda e: self.copy_to_clipboard(e, self.root))

        # --- Bottom Part: Total Summary Panel (Row 2) ---
        summary_frame = ttk.LabelFrame(parent_frame, text="Total Summary")
        summary_frame.grid(row=2, column=0, sticky="ew", pady=(5, 0), padx=2)
        
        # Configure grid for summary frame (4 columns: label, gross, tax, net)
        summary_frame.grid_columnconfigure(0, weight=0)  # Label column
        summary_frame.grid_columnconfigure(1, weight=1)  # Gross column
        summary_frame.grid_columnconfigure(2, weight=1)  # Tax column
        summary_frame.grid_columnconfigure(3, weight=1)  # Net column

        # Row 0: Column Headers
        ttk.Label(summary_frame, text="").grid(row=0, column=0, padx=10, pady=5, sticky="w")
        ttk.Label(summary_frame, text="Gross income (CZK)", font=('TkDefaultFont', 9, 'bold')).grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        ttk.Label(summary_frame, text="Withholding tax (CZK)", font=('TkDefaultFont', 9, 'bold')).grid(row=0, column=2, padx=5, pady=5, sticky="ew")
        ttk.Label(summary_frame, text="Net income (CZK)", font=('TkDefaultFont', 9, 'bold')).grid(row=0, column=3, padx=5, pady=5, sticky="ew")

        # Row 1: Dividend Income and Values
        ttk.Label(summary_frame, text="Dividend income:").grid(row=1, column=0, padx=10, pady=5, sticky="w")
        ttk.Entry(summary_frame, textvariable=self.dividend_gross_var, state='readonly', width=15, justify='right').grid(row=1, column=1, padx=5, pady=5, sticky="ew")
        ttk.Entry(summary_frame, textvariable=self.dividend_tax_var, state='readonly', width=15, justify='right').grid(row=1, column=2, padx=5, pady=5, sticky="ew")
        ttk.Entry(summary_frame, textvariable=self.dividend_net_var, state='readonly', width=15, justify='right').grid(row=1, column=3, padx=5, pady=5, sticky="ew")
    
    def update_view(self, start_timestamp, end_timestamp):
        """
        Fetch dividends data and update the view with hierarchical structure.
        
        Tax Calculation Methods:
        - JSON mode (default): Uses withholding tax rates from config/withholding_tax_rates.json
          Calculates gross and tax from the precise net amount using formulas:
          gross = net / (1 - rate)
          tax = net * rate / (1 - rate)
          This corrects rounding errors in the original CSV data.
        
        - CSV mode: Uses gross and tax values as imported from the CSV file.
          These may contain rounding errors but reflect the original data.
        
        Args:
            start_timestamp: Start of the date range (Unix timestamp)
            end_timestamp: End of the date range (Unix timestamp)
        """
        if not self.tree:
            return
        
        # Ensure DB connection exists and repository is initialized
        if not self.db.conn or not self.db.dividends_repo:
            self.clear_view()
            if self.country_summary_tree:
                for item in self.country_summary_tree.get_children():
                    self.country_summary_tree.delete(item)
            self.dividend_gross_var.set("0.00 CZK")
            self.dividend_tax_var.set("0.00 CZK")
            self.dividend_net_var.set("0.00 CZK")
            return
        
        try:
            # Clear existing data
            self.clear_view()
            if self.country_summary_tree:
                for item in self.country_summary_tree.get_children():
                    self.country_summary_tree.delete(item)
            
            # Fetch grouped summary data (parent rows)
            grouped_dividends = self.db.dividends_repo.get_summary_grouped_by_isin(start_timestamp, end_timestamp)
            
            # Dictionary to accumulate dividends by country
            country_summary = {}
            
            # Determine which calculation method to use
            use_json_rates = self.use_json_tax_rates.get()
            
            # Build hierarchical tree structure
            for group in grouped_dividends:
                isin_id = group[0]
                isin = group[1]
                name = group[3]
                ticker = group[2]
                
                # If using JSON rates, recalculate gross and tax from net
                if use_json_rates:
                    # Resolve country code (with override support)
                    country_code, source = self.country_resolver.get_country(isin)
                    
                    # Get net amount from database (this is the precise value)
                    total_net = group[6]
                    
                    if country_code:
                        calculated_gross = self.tax_rates_loader.calculate_gross_from_net(total_net, country_code)
                        calculated_tax = self.tax_rates_loader.calculate_tax_from_net(total_net, country_code)
                        
                        if calculated_gross is not None and calculated_tax is not None:
                            total_gross = calculated_gross
                            total_tax = calculated_tax
                        else:
                            # Fallback to CSV values if JSON rate not found
                            total_gross = group[4]
                            total_tax = group[5]
                    else:
                        # Fallback to CSV values if no country code
                        total_gross = group[4]
                        total_tax = group[5]
                else:
                    # Use values from CSV (stored in database)
                    total_gross = group[4]
                    total_tax = group[5]
                    total_net = group[6]
                
                # Resolve country code using CountryResolver (handles overrides)
                country_code, country_source = self.country_resolver.get_country(isin)
                
                # Accumulate by country
                if country_code not in country_summary:
                    country_summary[country_code] = {
                        'gross': 0.0,
                        'tax': 0.0,
                        'net': 0.0
                    }
                country_summary[country_code]['gross'] += total_gross
                country_summary[country_code]['tax'] += total_tax
                country_summary[country_code]['net'] += total_net
                
                # Insert parent row (grouped by ISIN) - Date column is empty
                parent_id = self.tree.insert('', tk.END, values=(
                    name,
                    ticker,
                    "",  # Empty date for parent rows
                    "",  # Empty price per share for parent
                    f"{total_gross:.2f}",
                    f"{total_tax:.2f}",
                    f"{total_net:.2f}"
                ))
                
                # Fetch individual dividend records for this ISIN (child rows)
                detail_records = self.db.dividends_repo.get_by_isin_and_date_range(isin_id, start_timestamp, end_timestamp)
                
                for record in detail_records:
                    timestamp = record[1]
                    price_per_share = record[4]
                    currency_of_price = record[5]
                    net_czk = record[7]  # Net is the precise value
                    
                    # Recalculate gross and tax if using JSON rates
                    if use_json_rates and country_code and country_code != "XX":
                        calculated_gross = self.tax_rates_loader.calculate_gross_from_net(net_czk, country_code)
                        calculated_tax = self.tax_rates_loader.calculate_tax_from_net(net_czk, country_code)
                        
                        if calculated_gross is not None and calculated_tax is not None:
                            gross_czk = calculated_gross
                            withholding_tax_czk = calculated_tax
                        else:
                            # Fallback to CSV values
                            gross_czk = record[6]
                            withholding_tax_czk = record[8]
                    else:
                        # Use CSV values
                        gross_czk = record[6]
                        withholding_tax_czk = record[8]

                    # Convert timestamp to display string
                    dt_obj = self.db.timestamp_to_datetime(timestamp)
                    date_str = dt_obj.strftime("%d.%m.%Y")

                    # Format price per share with currency
                    price_str = f"{price_per_share:.4f} {currency_of_price}"

                    # Insert child row under the parent
                    self.tree.insert(parent_id, tk.END, values=(
                        "",  # Empty name for child rows
                        "",  # Empty ticker for child rows
                        date_str,
                        price_str,
                        f"{gross_czk:.2f}",
                        f"{withholding_tax_czk:.2f}",
                        f"{net_czk:.2f}"
                    ))
            
            # Populate country summary table
            for country_code in sorted(country_summary.keys()):
                data = country_summary[country_code]
                gross = data['gross']
                tax = data['tax']
                net = data['net']
                
                # Calculate effective tax rate
                tax_rate = (tax / gross * 100) if gross > 0 else 0.0
                
                self.country_summary_tree.insert('', tk.END, values=(
                    country_code,
                    f"{gross:.2f}",
                    f"{tax_rate:.2f}",
                    f"{tax:.2f}",
                    f"{net:.2f}"
                ))
            
            # Insert totals row if there's data
            if country_summary:
                # Calculate totals for TOTAL row from country_summary
                row_total_gross = sum(data['gross'] for data in country_summary.values())
                row_total_tax = sum(data['tax'] for data in country_summary.values())
                row_total_net = sum(data['net'] for data in country_summary.values())
                row_total_tax_rate = (row_total_tax / row_total_gross * 100) if row_total_gross > 0 else 0.0
                
                self.country_summary_tree.insert('', tk.END, values=(
                    "TOTAL",
                    f"{row_total_gross:.2f}",
                    f"{row_total_tax_rate:.2f}",
                    f"{row_total_tax:.2f}",
                    f"{row_total_net:.2f}"
                ), tags=('total',))
                
                # Make the total row bold
                self.country_summary_tree.tag_configure('total', font=('TkDefaultFont', 9, 'bold'))
            
            # Update Summary Fields using database aggregation
            # Always get net total from database (most efficient)
            _, _, db_total_net = self.db.dividends_repo.get_summary_by_date_range(start_timestamp, end_timestamp)
            
            if use_json_rates:
                # JSON mode: Calculate gross and tax from aggregated net using weighted average rate
                total_gross_sum = 0.0
                total_tax_sum = 0.0
                
                # Get all ISINs to properly weight the calculation
                for group in grouped_dividends:
                    isin = group[1]
                    country_code, _ = self.country_resolver.get_country(isin)
                    
                    # Get the net for this ISIN
                    isin_net = group[6]
                    
                    if country_code and country_code != "XX":
                        calculated_gross = self.tax_rates_loader.calculate_gross_from_net(isin_net, country_code)
                        calculated_tax = self.tax_rates_loader.calculate_tax_from_net(isin_net, country_code)
                        
                        if calculated_gross is not None and calculated_tax is not None:
                            total_gross_sum += calculated_gross
                            total_tax_sum += calculated_tax
                        else:
                            # Fallback to CSV values
                            total_gross_sum += group[4]
                            total_tax_sum += group[5]
                    else:
                        # No country or unknown - use CSV values
                        total_gross_sum += group[4]
                        total_tax_sum += group[5]
                
                self.dividend_gross_var.set(f"{total_gross_sum:.2f} CZK")
                self.dividend_tax_var.set(f"{total_tax_sum:.2f} CZK")
                self.dividend_net_var.set(f"{db_total_net:.2f} CZK")
            else:
                # CSV mode: Get all totals from database aggregation
                db_total_gross, db_total_tax, db_total_net = self.db.dividends_repo.get_summary_by_date_range(start_timestamp, end_timestamp)
                self.dividend_gross_var.set(f"{db_total_gross:.2f} CZK")
                self.dividend_tax_var.set(f"{db_total_tax:.2f} CZK")
                self.dividend_net_var.set(f"{db_total_net:.2f} CZK")
                
        except Exception as e:
            # Log error but don't crash the application
            print(f"Error updating dividends view: {e}")
            self.dividend_gross_var.set("0.00 CZK")
            self.dividend_tax_var.set("0.00 CZK")
            self.dividend_net_var.set("0.00 CZK")
