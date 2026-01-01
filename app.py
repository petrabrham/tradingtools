import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import ttk  # Required for Treeview and Notebook
from tkcalendar import DateEntry
import pandas as pd
import sys
import os
from dbmanager import DatabaseManager
from datetime import datetime, timedelta
from db.repositories.interests import InterestType
from config.tax_rates_loader import TaxRatesLoader
from config.country_resolver import CountryResolver
from views.trades_view import TradesView
from views.interests_view import InterestsView
from views.realized_income_view import RealizedIncomeView
from views.dividends_view import DividendsView
from dialogs.exchange_rate_dialog import ExchangeRateDialog
from dialogs.import_rates_dialog import ImportRatesDialog
from ui.menu_manager import MenuManager

class TradingToolsApp:

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Trading Tools")
        self.root.geometry("1000x800")
        
        # Database manager (moved DB logic to separate module)
        self.db = DatabaseManager()

        # Tax rates loader for JSON-based calculations
        self.tax_rates_loader = TaxRatesLoader()
        
        # Country resolver for accurate country of origin detection
        self.country_resolver = CountryResolver()
        
        # Tax calculation method: True = use JSON rates, False = use CSV values
        self.use_json_tax_rates = tk.BooleanVar(value=True)

        # Menu manager
        self.menu_manager = MenuManager(self.root, self)
        self.menu_manager.create_menu()

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

        # Variables for Realized Income Summary
        self.realized_pnl_var = tk.StringVar(value="0.00 CZK")
        self.total_buy_cost_var = tk.StringVar(value="0.00 CZK")
        self.total_sell_proceeds_var = tk.StringVar(value="0.00 CZK")
        self.unrealized_shares_var = tk.StringVar(value="0")

        # Year filter state (Combobox created in create_widgets)
        self.year_combobox = None

        # Initialize views
        self.trades_view = TradesView(self.db, self.root)
        self.interests_view = InterestsView(self.db, self.root)
        self.realized_view = RealizedIncomeView(self.db, self.root)
        self.dividends_view = DividendsView(self.db, self.root, self.tax_rates_loader, self.country_resolver, self.use_json_tax_rates)

        self.create_widgets()

        # Initial state update
        self.menu_manager.update_states(self.db)
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
    def on_year_selected(self, event):
        if not self.year_combobox:
            return
        year_str = self.year_combobox.get()
        if not year_str:
            return
        year = int(year_str)
        # Set date_from_var and date_to_var to first and last day of year
        date_from = f"{year}-01-01"
        date_to = f"{year}-12-31"
        self.date_from_var.set(date_from)
        self.date_to_var.set(date_to)
        self.update_views()
    
    def on_tax_calculation_method_changed(self):
        """Handle change in tax calculation method - refresh dividends view."""
        self.update_dividends_view()

    def copy_treeview_to_clipboard(self, event):
        """Copy selected treeview rows to clipboard as tab-separated values."""
        widget = event.widget
        if not isinstance(widget, ttk.Treeview):
            return
        
        # Get selected items
        selection = widget.selection()
        if not selection:
            return
        
        # Build clipboard content
        lines = []
        
        # Add header row
        columns = widget['columns']
        if columns:
            # Include tree column if visible
            if widget['show'] == 'tree headings':
                header = [''] + [widget.heading(col)['text'] for col in columns]
            else:
                header = [widget.heading(col)['text'] for col in columns]
            lines.append('\t'.join(header))
        
        # Add data rows
        for item_id in selection:
            values = widget.item(item_id)['values']
            if values:
                lines.append('\t'.join(str(v) for v in values))
        
        # Copy to clipboard
        clipboard_text = '\n'.join(lines)
        self.root.clipboard_clear()
        self.root.clipboard_append(clipboard_text)
        
        # Show confirmation (optional)
        print(f"Copied {len(selection)} row(s) to clipboard")

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
                self.update_year_list()
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
        # Ask user to choose exchange rate mode using dialog
        rate_dialog = ExchangeRateDialog(self.root)
        selected_mode = rate_dialog.show()
        
        if selected_mode is None:
            return  # User closed dialog without choosing
        
        # Set the mode before creating database
        self.db.use_annual_rates = selected_mode
        
        file_path = filedialog.asksaveasfilename(
            defaultextension=".db",
            filetypes=[("SQLite Database", "*.db"), ("All files", "*.*")]
        )
        if file_path:
            try:
                # Delegate to DatabaseManager
                self.db.create_database(file_path)
                self.update_title()
                self.menu_manager.update_states(self.db)
                self.update_year_list()
                self.init_date_filters_from_db()
                self.update_filters()
                self.update_views()
                
                # Update UI to reflect loaded mode
                self.menu_manager.update_exchange_rate_display(self.db)
            except Exception as e:
                messagebox.showerror("Error", f"Error creating database: {str(e)}")

    def open_database(self):
        """Open an existing SQLite database"""
        file_path = filedialog.askopenfilename(
            filetypes=[("SQLite Database", "*.db"), ("All files", "*.*")]
        )
        if file_path:
            try:
                # Delegate to DatabaseManager (which loads exchange rate mode)
                self.db.open_database(file_path)
                self.update_title()
                self.menu_manager.update_states(self.db)
                self.update_year_list()
                self.init_date_filters_from_db()
                self.update_filters()
                self.update_views()
                
                # Update UI to reflect loaded mode
                self.menu_manager.update_exchange_rate_display(self.db)
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
            self.menu_manager.update_states(self.db)
            self.update_views()
            self.update_year_list()
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
                self.menu_manager.update_states(self.db)
                self.update_views()
            except Exception as e:
                messagebox.showerror("Error", f"Error saving database: {str(e)}")

    def import_annual_rates(self):
        """Import annual exchange rates from GFŘ text file"""
        if not self.db.conn:
            messagebox.showwarning("Warning", "Please create or open a database first!")
            return
        
        if not self.db.use_annual_rates:
            messagebox.showwarning(
                "Warning", 
                "This database uses daily CNB rates.\n\n"
                "Annual exchange rates can only be imported into databases\n"
                "configured for annual GFŘ rates."
            )
            return
        
        # Get available years
        available_years = self.db.get_available_annual_rate_years()
        
        # Show dialog
        import_dialog = ImportRatesDialog(self.root, available_years)
        year, file_path = import_dialog.show()
        
        if year and file_path:
            try:
                import_result = self.db.import_annual_rates_from_file(file_path, year)
                
                message = (
                    f"Import completed for year {year}:\n\n"
                    f"Imported: {import_result['imported']} rates\n"
                    f"Skipped: {import_result['skipped']} lines\n"
                )
                
                if import_result['errors']:
                    message += f"\nErrors: {len(import_result['errors'])}\n"
                    message += "\nFirst errors:\n"
                    for error in import_result['errors'][:5]:
                        message += f"  {error}\n"
                
                if import_result['imported'] > 0:
                    messagebox.showinfo("Import Successful", message)
                else:
                    messagebox.showwarning("Import Warning", message)
                    
            except Exception as e:
                messagebox.showerror("Import Error", f"Error importing annual rates:\n\n{str(e)}")

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
        top_frame.grid_columnconfigure(0, weight=0) # Year label
        top_frame.grid_columnconfigure(1, weight=0) # Year combo
        top_frame.grid_columnconfigure(2, weight=0) # Spacer
        top_frame.grid_columnconfigure(3, weight=0) # Date from label
        top_frame.grid_columnconfigure(4, weight=1) # Date from entry
        top_frame.grid_columnconfigure(5, weight=0) # Spacer
        top_frame.grid_columnconfigure(6, weight=0) # Date to label
        top_frame.grid_columnconfigure(7, weight=1) # Date to entry
        top_frame.grid_columnconfigure(8, weight=0) # Button

        # Year Combobox (leftmost)
        ttk.Label(top_frame, text="Year:").grid(row=0, column=0, padx=(10, 5), pady=5, sticky="w")
        self.year_combobox = ttk.Combobox(top_frame, state='readonly', width=10)
        self.year_combobox.grid(row=0, column=1, padx=5, pady=5, sticky="w")
        self.year_combobox.bind("<<ComboboxSelected>>", self.on_year_selected)

        ttk.Label(top_frame, text="  ").grid(row=0, column=2) # Spacer

        # Date 'From' Picker
        ttk.Label(top_frame, text="Date from:").grid(row=0, column=3, padx=(10, 5), pady=5, sticky="w")
        self.date_from_picker = DateEntry(top_frame, textvariable=self.date_from_var, 
                                          date_pattern='yyyy-mm-dd', width=12)
        self.date_from_picker.grid(row=0, column=4, padx=5, pady=5, sticky="ew")

        ttk.Label(top_frame, text="  ").grid(row=0, column=5) # Spacer

        # Date 'To' Picker
        ttk.Label(top_frame, text="Date to:").grid(row=0, column=6, padx=(10, 5), pady=5, sticky="w")
        self.date_to_picker = DateEntry(top_frame, textvariable=self.date_to_var,
                                        date_pattern='yyyy-mm-dd', width=12)
        self.date_to_picker.grid(row=0, column=7, padx=5, pady=5, sticky="ew")

        # Filter Button
        ttk.Button(top_frame, text="Use Filter", command=self.apply_filter).grid(row=0, column=8, padx=10, pady=5)

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
        self.trades_view.create_view(tab_trades)

        # --- 5. Tab 2: Dividends View ---
        tab_dividends = ttk.Frame(self.notebook)
        self.notebook.add(tab_dividends, text="Dividends")
        # Set summary variables before creating view
        self.dividends_view.set_summary_variables(
            self.dividend_gross_var,
            self.dividend_tax_var,
            self.dividend_net_var
        )
        self.dividends_view.create_view(tab_dividends)

        # --- 5. Tab 3: Interests View ---
        tab_interests = ttk.Frame(self.notebook)
        self.notebook.add(tab_interests, text="Interests")
        # Set summary variables before creating view
        self.interests_view.set_summary_variables(
            self.interest_on_cash_var,
            self.share_lending_interest_var,
            self.unknown_interest_var
        )
        self.interests_view.create_view(tab_interests)

        # --- 6. Tab 4: Realized Income View ---
        tab_realized = ttk.Frame(self.notebook)
        self.notebook.add(tab_realized, text="Realized Income")
        # Set summary variables before creating view
        self.realized_view.set_summary_variables(
            self.realized_pnl_var,
            self.total_buy_cost_var,
            self.total_sell_proceeds_var,
            self.unrealized_shares_var
        )
        self.realized_view.create_view(tab_realized)

    def update_trades_view(self):
        """Populate the trades tree with grouped parents and detailed child trades."""
        # Parse date range
        date_from_str = self.date_from_var.get().strip()
        date_to_str = self.date_to_var.get().strip()
        try:
            start_ts = DatabaseManager.timestr_to_timestamp(f"{date_from_str} 00:00:00")
            end_ts = DatabaseManager.timestr_to_timestamp(f"{date_to_str} 23:59:59")
        except Exception:
            # If parsing fails, attempt to load everything
            start_ts = 0
            end_ts = int(datetime.now().timestamp())
        
        # Delegate to the TradesView
        self.trades_view.update_view(start_ts, end_ts)

    # Backward-compatible alias for requested name with typos
    def update_trases_wiew(self):
        self.update_trades_view()

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

        # Bind Ctrl+C for clipboard copy
        tree.bind("<Control-c>", self.copy_treeview_to_clipboard)
        tree.bind("<Control-C>", self.copy_treeview_to_clipboard)

    ###########################################################
    # Data Update Logic
    ###########################################################

    def update_interests_view(self):
        """Update the interests view with current filter dates."""
        date_from_str = self.date_from_var.get()
        date_to_str = self.date_to_var.get()
        
        try:
            start_dt_str = f"{date_from_str} 00:00:00"
            end_dt_str = f"{date_to_str} 23:59:59"
            
            start_ts = self.db.timestr_to_timestamp(start_dt_str)
            end_ts = self.db.timestr_to_timestamp(end_dt_str)
        except Exception:
            # If parsing fails, attempt to load everything
            start_ts = 0
            end_ts = int(datetime.now().timestamp())
        
        # Delegate to the InterestsView
        self.interests_view.update_view(start_ts, end_ts)

    def update_dividends_view(self):
        """
        Fetches dividends data from the DB based on current date filters 
        and updates the Treeview with hierarchical structure (grouped by ISIN).
        """
        # Parse date range
        date_from_str = self.date_from_var.get()
        date_to_str = self.date_to_var.get()
        
        try:
            # Convert date strings to Unix timestamps for DB query
            start_dt_str = f"{date_from_str} 00:00:00"
            end_dt_str = f"{date_to_str} 23:59:59"
            
            start_ts = self.db.timestr_to_timestamp(start_dt_str)
            end_ts = self.db.timestr_to_timestamp(end_dt_str)
        except Exception:
            # If parsing fails, attempt to load everything
            start_ts = 0
            end_ts = int(datetime.now().timestamp())
        
        # Delegate to the DividendsView
        self.dividends_view.update_view(start_ts, end_ts)

    def update_filters(self):
        """Update filter variables based on current widget states."""
        # Currently, date_from_var and date_to_var are directly linked to Entry widgets
        # If additional processing is needed, it can be done here

        pass

    def update_realized_income_view(self):
        """
        Calculate and display realized income using FIFO matching.
        Shows P&L from closed positions (buys that have been sold).
        """
        # Parse date range
        date_from_str = self.date_from_var.get().strip()
        date_to_str = self.date_to_var.get().strip()
        try:
            start_ts = DatabaseManager.timestr_to_timestamp(f"{date_from_str} 00:00:00")
            end_ts = DatabaseManager.timestr_to_timestamp(f"{date_to_str} 23:59:59")
        except Exception:
            start_ts = 0
            end_ts = int(datetime.now().timestamp())
        
        # Delegate to view
        self.realized_view.update_view(start_ts, end_ts)

    def update_views(self):
        """Update all views with data from the database."""
        # This function calls specific update functions for each view
        self.update_interests_view()
        self.update_dividends_view()
        self.update_trades_view()
        self.update_realized_income_view()

    def update_year_list(self):
        """Update the year combobox with years from all tables in the DB."""
        if not self.db.conn:
            if self.year_combobox:
                self.year_combobox.configure(values=[])
                self.year_combobox.set('')
            return
        try:
            years = self.db.get_all_years_with_data()
            year_strings = [str(y) for y in years]
            self.year_combobox.configure(values=year_strings)
            if year_strings:
                self.year_combobox.set(year_strings[0])  # Select first year by default
        except Exception:
            if self.year_combobox:
                self.year_combobox.configure(values=[])
                self.year_combobox.set('')

    def init_date_filters_from_db(self):
        """Initialize date filters to the first available year from the database."""
        if not self.db.conn or not self.year_combobox:
            return
        year_str = self.year_combobox.get()
        if year_str:
            year = int(year_str)
            self.date_from_var.set(f"{year}-01-01")
            self.date_to_var.set(f"{year}-12-31")

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