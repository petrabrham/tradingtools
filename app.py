import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import ttk  # Required for Treeview and Notebook
import pandas as pd
import sys
import os
from dbmanager import DatabaseManager
from datetime import datetime, timedelta
from db.repositories.interests import InterestType

class TradingToolsApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Trading Tools")
        self.root.geometry("1000x800")
        
        # Database manager (moved DB logic to separate module)
        self.db = DatabaseManager()

        # Menu container reference (used to enable/disable items)
        self.file_menu = None

        # Create menu
        self.create_menu()

        # Variables for date filters
        now = datetime.now()
        first_day_of_year = now.replace(month=1, day=1).strftime("%Y-%m-%d")
        self.date_from_var = tk.StringVar(value=first_day_of_year)
        self.date_to_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))

        # Variables for Interest Summary
        self.interest_on_cash_var = tk.StringVar(value="0.00 CZK")
        self.share_lending_interest_var = tk.StringVar(value="0.00 CZK")
        self.unknown_interest_var = tk.StringVar(value="0.00 CZK")

        # Variables for Dividend Summary
        self.dividend_gross_var = tk.StringVar(value="0.00 CZK")
        self.dividend_tax_var = tk.StringVar(value="0.00 CZK")
        self.dividend_net_var = tk.StringVar(value="0.00 CZK")

        self.create_widgets()

        # Initial state update
        self.update_menu_states()
        self.update_title()
        self.update_filters()
        self.update_views()

    ###########################################################
    # Title
    ###########################################################
    def update_title(self):
        """Update the window title with the current database name"""
        base_title = "Trading Tools"
        if self.db.current_db_path:
            db_name = os.path.basename(self.db.current_db_path)
            self.root.title(f"{base_title} - {db_name}")
        else:
            self.root.title(base_title)

    ###########################################################
    # Menu
    ###########################################################
    def create_menu(self):
        menubar = tk.Menu(self.root)
        
        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        self.file_menu = file_menu
        file_menu.add_command(label="New Database", command=self.create_database)
        file_menu.add_command(label="Connect Database", command=self.open_database)
        file_menu.add_command(label="Save Database Copy As...", command=self.save_database_as, state='disabled')
        file_menu.add_command(label="Release Database", command=self.release_database, state='disabled')
        file_menu.add_separator()
        file_menu.add_command(label="Import CSV", command=self.open_csv_file, state='disabled')
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)
        
        self.root.config(menu=menubar)

    def update_menu_states(self):
        """Update menu items states based on database connection"""
        if self.file_menu:
            try:
                if self.db.conn:
                    # DB is connected
                    self.file_menu.entryconfig("Import CSV", state='normal')
                    self.file_menu.entryconfig("Save Database Copy As...", state='normal')
                    self.file_menu.entryconfig("Release Database", state='normal')
                else:
                    # No DB connected
                    self.file_menu.entryconfig("Import CSV", state='disabled')
                    self.file_menu.entryconfig("Save Database Copy As...", state='disabled')
                    self.file_menu.entryconfig("Release Database", state='disabled')
            except Exception:
                # fallback: do nothing if entryconfig fails
                pass

    ###########################################################
    # Menu Command Handlers
    ###########################################################
    def open_csv_file(self):
        if not self.db.conn:
            messagebox.showwarning("Warning", "Please create or open a database first!")
            return

        file_path = filedialog.askopenfilename(
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if file_path:
            try:
                # Read CSV file
                df = pd.read_csv(file_path)

                self.db.logger.info(f"Importing CSV file: {file_path}")

                # Use DatabaseManager to import DataFrame
                meta = self.db.import_dataframe(df)
            except Exception as e:
                messagebox.showerror("Error", f"Error importing CSV file: {str(e)}")

            self.update_views()

            message = (
                f"Records imported: {meta['records']}\n"
                f"Read / Added counts:\n"
                f"  Buy:         {meta['read']['buy']} / {meta['added'].get('buy', 0)}\n"
                f"  Sell:        {meta['read']['sell']} / {meta['added'].get('sell', 0)}\n"
                f"  Interest:    {meta['read']['interest']} / {meta['added']['interest']}\n"
                f"  Dividend:    {meta['read']['dividend']} / {meta['added'].get('dividend', 0)}\n"
                f"  Other:       {meta['read']['insignificant']} / -\n"
                f"  Unknown:     {meta['read']['unknown']} / -"
            )
            messagebox.showinfo("Success", message)


    def create_database(self):
        """Create a new SQLite database"""
        file_path = filedialog.asksaveasfilename(
            defaultextension=".db",
            filetypes=[("SQLite Database", "*.db"), ("All files", "*.*")]
        )
        if file_path:
            try:
                # Delegate to DatabaseManager
                self.db.create_database(file_path)
                self.update_title()
                self.update_menu_states()
                self.update_views()
            except Exception as e:
                messagebox.showerror("Error", f"Error creating database: {str(e)}")

    def open_database(self):
        """Open an existing SQLite database"""
        file_path = filedialog.askopenfilename(
            filetypes=[("SQLite Database", "*.db"), ("All files", "*.*")]
        )
        if file_path:
            try:
                # Delegate to DatabaseManager
                self.db.open_database(file_path)
                self.update_title()
                self.update_menu_states()
                self.update_views()
            except Exception as e:
                messagebox.showerror("Error", f"Error opening database: {str(e)}")

    def release_database(self):
        """Release the current database"""
        if not self.db.conn:
            messagebox.showwarning("Warning", "No database is currently open!")
            return

        try:
            self.db.release_database()
            self.update_title()
            self.update_menu_states()
            self.update_views()
        except Exception as e:
            messagebox.showerror("Error", f"Error releasing database: {str(e)}")

    def save_database_as(self):
        """Save the current database to a new file"""
        if not self.db.conn:
            messagebox.showwarning("Warning", "No database is currently open!")
            return

        file_path = filedialog.asksaveasfilename(
            defaultextension=".db",
            filetypes=[("SQLite Database", "*.db"), ("All files", "*.*")]
        )
        if file_path:
            try:
                # Delegate to DatabaseManager
                self.db.save_database_as(file_path)
                self.update_title()
                self.update_menu_states()
                self.update_views()
            except Exception as e:
                messagebox.showerror("Error", f"Error saving database: {str(e)}")

    ###########################################################
    # Widgets
    ###########################################################
    def create_widgets(self):
        """Creates the main responsive layout with Date Pickers and Notebook."""
        
        # --- 1. Main Content Frame ---
        # This frame holds the top and bottom sections
        main_content_frame = tk.Frame(self.root)
        main_content_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Configure row weights for responsiveness
        # Row 0 (Top Frame) gets a small portion of height
        main_content_frame.grid_rowconfigure(0, weight=0)
        # Row 1 (Bottom Frame/Notebook) gets almost all available height
        main_content_frame.grid_rowconfigure(1, weight=1) 
        main_content_frame.grid_columnconfigure(0, weight=1)

        # --- 2. Top Frame: Date Pickers (Row 0) ---
        top_frame = ttk.LabelFrame(main_content_frame, text="Filter")
        top_frame.grid(row=0, column=0, sticky="ew", pady=5)
        
        # Configure column weights for the top frame
        top_frame.grid_columnconfigure(0, weight=0) # Labels
        top_frame.grid_columnconfigure(1, weight=1) # Entry 1
        top_frame.grid_columnconfigure(2, weight=0) # Spacer
        top_frame.grid_columnconfigure(3, weight=0) # Labels
        top_frame.grid_columnconfigure(4, weight=1) # Entry 2
        top_frame.grid_columnconfigure(5, weight=0) # Button

        # Date 'From' Picker
        ttk.Label(top_frame, text="Date ftom:").grid(row=0, column=0, padx=(10, 5), pady=5, sticky="w")
        self.date_from_var = tk.StringVar(value= (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d"))
        ttk.Entry(top_frame, textvariable=self.date_from_var).grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        ttk.Label(top_frame, text="  ").grid(row=0, column=2) # Spacer

        # Date 'To' Picker
        ttk.Label(top_frame, text="Date to:").grid(row=0, column=3, padx=(10, 5), pady=5, sticky="w")
        self.date_to_var = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        ttk.Entry(top_frame, textvariable=self.date_to_var).grid(row=0, column=4, padx=5, pady=5, sticky="ew")
        
        # Filter Button
        ttk.Button(top_frame, text="Use Filter", command=self.apply_filter).grid(row=0, column=5, padx=10, pady=5)

        # --- 3. Bottom Frame: Notebook (Row 1) ---
        bottom_frame = tk.Frame(main_content_frame)
        bottom_frame.grid(row=1, column=0, sticky="nsew") # Takes remaining space
        bottom_frame.grid_columnconfigure(0, weight=1)
        bottom_frame.grid_rowconfigure(0, weight=1)

        # Create the Notebook widget
        self.notebook = ttk.Notebook(bottom_frame)
        self.notebook.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)

        # --- 4. Tab 1: Trades View ---
        tab_trades = ttk.Frame(self.notebook)
        self.notebook.add(tab_trades, text="Trades")
        self.create_trades_view(tab_trades)

        # --- 5. Tab 2: Dividends View ---
        tab_dividends = ttk.Frame(self.notebook)
        self.notebook.add(tab_dividends, text="Dividends")
        self.create_dividends_view(tab_dividends)

        # --- 5. Tab 3: Interests View ---
        tab_interests = ttk.Frame(self.notebook)
        self.notebook.add(tab_interests, text="Interests")
        self.create_interests_view(tab_interests)

    def create_trades_view(self, parent_frame: ttk.Frame):
        """Creates a Treeview widget with scrollbars and sample data."""
        
        # Configure frame to hold Treeview and Scrollbars
        parent_frame.grid_columnconfigure(0, weight=1)
        parent_frame.grid_rowconfigure(0, weight=1)
        
        # Define Columns
        columns = ("ID", "Datum", "ISIN", "Akcie", "Počet", "Cena", "Měna")
        
        # Create Treeview
        tree = ttk.Treeview(parent_frame, columns=columns, show='headings')
        tree.grid(row=0, column=0, sticky='nsew')
        
        # Store a reference to the treeview
        setattr(self, "trades_tree", tree)
        
        # Configure Headings and Columns
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, anchor=tk.W, width=100)
            
        # Scrollbars
        vsb = ttk.Scrollbar(parent_frame, orient="vertical", command=tree.yview)
        vsb.grid(row=0, column=1, sticky='ns')
        tree.configure(yscrollcommand=vsb.set)

        hsb = ttk.Scrollbar(parent_frame, orient="horizontal", command=tree.xview)
        hsb.grid(row=1, column=0, sticky='ew')
        tree.configure(xscrollcommand=hsb.set)

    def create_dividends_view(self, parent_frame: ttk.Frame):
        """Creates a view for dividends data, split horizontally into Treeview and Summary."""

        parent_frame.grid_columnconfigure(0, weight=1)
        parent_frame.grid_rowconfigure(0, weight=1) # Treeview (expands) 
        parent_frame.grid_rowconfigure(1, weight=0) # Summary Panel (fixed height)

        # --- Top Part: Treeview for Dividends (Row 0) ---
        treeview_frame = ttk.Frame(parent_frame)
        treeview_frame.grid(row=0, column=0, sticky="nsew")
        
        # Configure frame for treeview and scrollbars
        treeview_frame.grid_columnconfigure(0, weight=1)
        treeview_frame.grid_rowconfigure(0, weight=1)
        
        # Create Treeview with tree structure visible (show='tree headings')
        dividend_columns = ("Name", "Ticker", "Date", "Price per Share", "Gross Income (CZK)", "Withholding Tax (CZK)")
        tree = ttk.Treeview(treeview_frame, columns=dividend_columns, show='tree headings')
        tree.grid(row=0, column=0, sticky='nsew')

        # Store reference
        self.dividends_tree = tree

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

        # Add scrollbars
        vsb = ttk.Scrollbar(treeview_frame, orient="vertical", command=tree.yview)
        vsb.grid(row=0, column=1, sticky='ns')
        tree.configure(yscrollcommand=vsb.set)

        hsb = ttk.Scrollbar(treeview_frame, orient="horizontal", command=tree.xview)
        hsb.grid(row=1, column=0, sticky='ew')
        tree.configure(xscrollcommand=hsb.set)

        # --- Bottom Part: Summary Panel (Row 1) ---
        summary_frame = ttk.LabelFrame(parent_frame, text="Summary")
        summary_frame.grid(row=1, column=0, sticky="ew", pady=(5, 0), padx=2)
        
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

    def create_interests_view(self, parent_frame: ttk.Frame):
        """Creates a view for interests data, split horizontally into Treeview and Summary."""

        parent_frame.grid_columnconfigure(0, weight=1)
        parent_frame.grid_rowconfigure(0, weight=1) # Treeview (expands) 
        parent_frame.grid_rowconfigure(1, weight=0) # Summary Panel (fixed height)

        # --- Top Part: Treeview for Interests (Row 0) ---
        treeview_frame = ttk.Frame(parent_frame)
        treeview_frame.grid(row=0, column=0, sticky="nsew")
        
        interest_columns = ("Date Time", "Type", "Total (CZK)")
        self.create_treeview(treeview_frame, "interests_tree", interest_columns)
        
        # Set specific column widths for the interests table
        self.interests_tree.column("Date Time", anchor=tk.W, width=150)
        self.interests_tree.column("Type", anchor=tk.W, width=120)
        self.interests_tree.column("Total (CZK)", anchor=tk.E, width=100)

        # --- Bottom Part: Summary Panel (Row 1) ---
        summary_frame = ttk.LabelFrame(parent_frame, text="Interests Summary")
        summary_frame.grid(row=1, column=0, sticky="ew", pady=(5, 0), padx=2)
        
        # Configure grid for summary frame (columns needed for 2 labels and 2 fields)
        summary_frame.grid_columnconfigure(0, weight=1) # Label column
        summary_frame.grid_columnconfigure(1, weight=1) # Entry column (align right)

        # Interest on Cash
        ttk.Label(summary_frame, text="Interest on cash:").grid(row=0, column=0, padx=10, pady=5, sticky="w")
        ttk.Entry(summary_frame, textvariable=self.interest_on_cash_var, state='readonly', width=20, justify='right').grid(row=0, column=1, padx=(0, 10), pady=5, sticky="e")

        # Share Lending Interest
        ttk.Label(summary_frame, text="Share lending interest:").grid(row=1, column=0, padx=10, pady=5, sticky="w")
        ttk.Entry(summary_frame, textvariable=self.share_lending_interest_var, state='readonly', width=20, justify='right').grid(row=1, column=1, padx=(0, 10), pady=5, sticky="e")

        # Unknown Interest
        ttk.Label(summary_frame, text="Unknown interest:").grid(row=2, column=0, padx=10, pady=5, sticky="w")
        ttk.Entry(summary_frame, textvariable=self.unknown_interest_var, state='readonly', width=20, justify='right').grid(row=2, column=1, padx=(0, 10), pady=5, sticky="e")


    def create_treeview(self, parent_frame: ttk.Frame, name: str, columns: tuple):
        """Creates a generic Treeview widget with scrollbars."""
        
        parent_frame.grid_columnconfigure(0, weight=1)
        parent_frame.grid_rowconfigure(0, weight=1)
        
        tree = ttk.Treeview(parent_frame, columns=columns, show='headings')
        tree.grid(row=0, column=0, sticky='nsew')
        
        setattr(self, name, tree)
        
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, anchor=tk.W, width=100)
            
        # Scrollbars
        vsb = ttk.Scrollbar(parent_frame, orient="vertical", command=tree.yview)
        vsb.grid(row=0, column=1, sticky='ns')
        tree.configure(yscrollcommand=vsb.set)

        hsb = ttk.Scrollbar(parent_frame, orient="horizontal", command=tree.xview)
        hsb.grid(row=1, column=0, sticky='ew')
        tree.configure(xscrollcommand=hsb.set)

    ###########################################################
    # Data Update Logic
    ###########################################################

    def update_interests_view(self):
        """
        Fetches interests data from the DB based on current date filters 
        and updates the Treeview and Summary fields.
        """
        # Ensure DB connection exists and repository is initialized
        if not self.db.conn or not self.db.interests_repo:
            self.interests_tree.delete(*self.interests_tree.get_children())
            self.interest_on_cash_var.set("0.00 CZK")
            self.share_lending_interest_var.set("0.00 CZK")
            self.unknown_interest_var.set("0.00 CZK")
            return

        date_from_str = self.date_from_var.get()
        date_to_str = self.date_to_var.get()
        
        try:
            # 1. Convert date strings to Unix timestamps for DB query
            # Note: We append time to ensure the full date range is covered
            start_dt_str = f"{date_from_str} 00:00:00"
            end_dt_str = f"{date_to_str} 23:59:59"
            
            start_ts = self.db.timestr_to_timestamp(start_dt_str)
            end_ts = self.db.timestr_to_timestamp(end_dt_str)
            
            # 2. Fetch data from repository
            # Data format: (id, timestamp, type, id_string, total_czk)
            interest_records = self.db.interests_repo.get_by_date_range(start_ts, end_ts)
            
            # 3. Process and display data
            self.interests_tree.delete(*self.interests_tree.get_children())

            for _, timestamp, type_int, _, total_czk in interest_records:
                # Convert timestamp back to display string
                dt_obj = self.db.timestamp_to_datetime(timestamp)
                timestamp_str = dt_obj.strftime("%d.%m.%Y %H:%M:%S")
                
                # Convert integer type back to human-readable string
                interest_type = InterestType(type_int)
                type_str = ""
                if interest_type == InterestType.CASH_INTEREST:
                    type_str = "Interest on cash"
                elif interest_type == InterestType.LENDING_INTEREST:
                    type_str = "Share lending interest"
                else:
                    type_str = "Unknown"

                # Insert into Treeview
                self.interests_tree.insert('', tk.END, values=(
                    timestamp_str,
                    type_str,
                    f"{total_czk:.2f}"
                ))
            
            # 4. Update Summary Fields
            summary = self.db.interests_repo.get_total_interest_by_type(start_ts, end_ts)
            total_cash_interest = summary.get(InterestType.CASH_INTEREST, 0.0)
            self.interest_on_cash_var.set(f"{total_cash_interest:.2f} CZK")
            total_share_lending = summary.get(InterestType.LENDING_INTEREST, 0.0)
            self.share_lending_interest_var.set(f"{total_share_lending:.2f} CZK")
            total_unknown = summary.get(InterestType.UNKNOWN, 0.0)
            self.unknown_interest_var.set(f"{total_unknown:.2f} CZK")

        except ValueError as e:
            messagebox.showerror("Chyba filtru", f"Chyba při parsování data: {e}. Zkontrolujte formát (YYYY-MM-DD).")
        except Exception as e:
            messagebox.showerror("Chyba databáze", f"Chyba při načítání úroků z databáze: {e}")

    def update_dividends_view(self):
        """
        Fetches dividends data from the DB based on current date filters 
        and updates the Treeview with hierarchical structure (grouped by ISIN).
        """
        # Ensure DB connection exists and repository is initialized
        if not self.db.conn or not self.db.dividends_repo:
            self.dividends_tree.delete(*self.dividends_tree.get_children())
            self.dividend_gross_var.set("0.00 CZK")
            self.dividend_tax_var.set("0.00 CZK")
            self.dividend_net_var.set("0.00 CZK")
            return

        date_from_str = self.date_from_var.get()
        date_to_str = self.date_to_var.get()
        
        try:
            # 1. Convert date strings to Unix timestamps for DB query
            start_dt_str = f"{date_from_str} 00:00:00"
            end_dt_str = f"{date_to_str} 23:59:59"
            
            start_ts = self.db.timestr_to_timestamp(start_dt_str)
            end_ts = self.db.timestr_to_timestamp(end_dt_str)
            
            # 2. Clear existing data
            self.dividends_tree.delete(*self.dividends_tree.get_children())
            
            # 3. Fetch grouped summary data (parent rows)
            # Data format: (isin_id, isin, ticker, name, total_gross_czk, total_tax_czk)
            grouped_dividends = self.db.dividends_repo.get_summary_grouped_by_isin(start_ts, end_ts)
            
            # 4. Build hierarchical tree structure
            for group in grouped_dividends:
                isin_id = group[0]
                name = group[3]
                ticker = group[2]
                total_gross = group[4]
                total_tax = group[5]
                
                # Insert parent row (grouped by ISIN) - Date column is empty
                parent_id = self.dividends_tree.insert('', tk.END, values=(
                    name,
                    ticker,
                    "",  # Empty date for parent rows
                    "",  # Empty price per share for parent
                    f"{total_gross:.2f}",
                    f"{total_tax:.2f}"
                ))
                
                # 5. Fetch individual dividend records for this ISIN (child rows)
                # Data format: (id, timestamp, isin_id, number_of_shares, price_for_share,
                #               currency_of_price, total_czk, withholding_tax_czk, isin, ticker, name)
                detail_records = self.db.dividends_repo.get_by_isin_and_date_range(isin_id, start_ts, end_ts)
                
                for record in detail_records:
                    timestamp = record[1]
                    price_per_share = record[4]
                    currency_of_price = record[5]
                    total_czk = record[6]
                    withholding_tax_czk = record[7]

                    # Convert timestamp to display string
                    dt_obj = self.db.timestamp_to_datetime(timestamp)
                    date_str = dt_obj.strftime("%d.%m.%Y")

                    # Format price per share with currency
                    price_str = f"{price_per_share:.4f} {currency_of_price}"

                    # Insert child row under the parent
                    self.dividends_tree.insert(parent_id, tk.END, values=(
                        "",  # Empty name for child rows
                        "",  # Empty ticker for child rows
                        date_str,
                        price_str,
                        f"{total_czk:.2f}",
                        f"{withholding_tax_czk:.2f}"
                    ))
            
            # 6. Update Summary Fields using separate query
            total_gross, total_tax, total_net = self.db.dividends_repo.get_summary_by_date_range(start_ts, end_ts)
            self.dividend_gross_var.set(f"{total_gross:.2f} CZK")
            self.dividend_tax_var.set(f"{total_tax:.2f} CZK")
            self.dividend_net_var.set(f"{total_net:.2f} CZK")

        except ValueError as e:
            messagebox.showerror("Filter Error", f"Error parsing date: {e}. Check format (YYYY-MM-DD).")
        except Exception as e:
            messagebox.showerror("Database Error", f"Error loading dividends from database: {e}")

    def update_filters(self):
        """Update filter variables based on current widget states."""
        # Currently, date_from_var and date_to_var are directly linked to Entry widgets
        # If additional processing is needed, it can be done here

        pass

    def update_views(self):
        """Update all views with data from the database."""
        # This function calls specific update functions for each view
        self.update_interests_view()
        self.update_dividends_view()
        # TODO: self.update_trades_view()
        pass

    ###########################################################
    # Widgets command handlers
    ###########################################################
    def apply_filter(self):
        """Handles the logic when the filter button is pressed."""
        # date_from = self.date_from_var.get()
        # date_to = self.date_to_var.get()

        # Calls update_views, which handles the filtering for all relevant tabs
        self.update_views()

    ###########################################################
    # Main Loop
    ###########################################################
    def run(self):
        self.root.mainloop()

###########################################################
# Application Entry Point
###########################################################
if __name__ == "__main__":
    app = TradingToolsApp()
    app.run()