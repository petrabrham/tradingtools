import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import ttk  # Required for Treeview and Notebook
from tkcalendar import DateEntry
import os
from tradingtools.db.dbmanager import DatabaseManager
from datetime import datetime, timedelta
from tradingtools.db.repositories.interests import InterestType
from tradingtools.config.tax_rates_loader import TaxRatesLoader
from tradingtools.config.country_resolver import CountryResolver
from tradingtools.config.config_loader import get_config
from tradingtools.views.trades_view import TradesView
from tradingtools.views.interests_view import InterestsView
from tradingtools.views.realized_income_view import RealizedIncomeView
from tradingtools.views.dividends_view import DividendsView
from tradingtools.views.pairs_view import PairsView
from tradingtools.views.open_positions_view import OpenPositionsView
from tradingtools.dialogs.exchange_rate_dialog import ExchangeRateDialog
from tradingtools.dialogs.import_rates_dialog import ImportRatesDialog
from tradingtools.dialogs.csv_import_dialog import CSVImportDialog
from tradingtools.dialogs.trading212_dialog import (
    Trading212ConnectionDialog, Trading212RefreshDialog, Trading212WorkerDialog,
)
from tradingtools.dialogs.import_conflicts_dialog import ImportConflictsDialog
from tradingtools.import_diagnostics import ImportComparison
from tradingtools.trading212_sync import SyncResult, Trading212Connection, Trading212Sync, load_connection
from tradingtools.ui import MenuManager, FilterManager, copy_treeview_to_clipboard

class TradingToolsApp:

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Trading Tools")
        self.root.geometry("1000x800")
        
        # Database manager (moved DB logic to separate module)
        self.db = DatabaseManager()
        self.data_operation_active = False
        self.last_import_comparisons: list[ImportComparison] = []
        self._exit_after_operation = False

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
        self.pairs_view = PairsView(self.db, self.root)
        self.open_positions_view = OpenPositionsView(self.db, self.root)
        
        # Set callback to update realized income view when pairings change
        self.pairs_view.on_pairings_changed = self.update_realized_income_view

        # Filter manager
        self.filter_manager = FilterManager(self)

        self.create_widgets()

        # Initial state update
        self.menu_manager.update_states(self.db)
        self.update_title()
        self.filter_manager.update_filters()
        self.update_views()
        self.root.protocol("WM_DELETE_WINDOW", self.on_exit)
        self.restore_last_database()

    ###########################################################
    # Title
    ###########################################################
    def update_title(self):
        """Show the current database and its saved Trading212 account."""
        base_title = "Trading Tools"
        if self.db.current_db_path:
            db_name = os.path.basename(self.db.current_db_path)
            base_title += f" - {db_name}"
            connection = load_connection(self.db)
            if connection is not None:
                base_title += (
                    f" - Trading212 account {connection.account_id}"
                    f" ({connection.environment.capitalize()})"
                )
        self.root.title(base_title)

    ###########################################################
    # Menu
    ###########################################################
    def on_tax_calculation_method_changed(self):
        """Handle change in tax calculation method - refresh dividends view."""
        self.update_dividends_view()

    ###########################################################
    # Menu Command Handlers
    ###########################################################
    def open_csv_file(self):
        if self._operation_blocked():
            return
        if not self.db.conn:
            messagebox.showwarning("Warning", "Please create or open a database first!")
            return

        file_path = filedialog.askopenfilename(
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if file_path:
            self._begin_operation()
            self.last_import_comparisons = []
            try:
                if self.db.current_db_path is None:
                    raise RuntimeError("The open database has no file path")
                dialog = CSVImportDialog(self.root, self.db.current_db_path, file_path)
                try:
                    meta = dialog.show()
                finally:
                    self._exit_after_operation = self._exit_after_operation or dialog.exit_requested
                if meta is None:
                    return
                self.last_import_comparisons = meta.get("comparisons", [])
                self.filter_manager.update_year_list()
            except Exception as e:
                self.db.logger.exception("CSV import failed")
                if not self._exit_after_operation:
                    messagebox.showerror("Error", f"Error importing CSV file: {str(e)}")
                self.update_views()
                return
            finally:
                self._end_operation()

            if dialog.exit_requested:
                return
            self.update_views()

            message = (
                f"Records processed: {meta['processed']} / {meta['records']}\n"
                f"Read / Added counts:\n"
                f"  Buy:         {meta['read']['buy']} / {meta['added'].get('buy', 0)}\n"
                f"  Sell:        {meta['read']['sell']} / {meta['added'].get('sell', 0)}\n"
                f"  Interest:    {meta['read']['interest']} / {meta['added']['interest']}\n"
                f"  Dividend:    {meta['read']['dividend']} / {meta['added'].get('dividend', 0)}\n"
                f"  Fee:         {meta['read'].get('fee', 0)} / {meta['added'].get('fee', 0)}\n"
                f"  Other:       {meta['read']['insignificant']} / -\n"
                f"  Unknown:     {meta['read']['unknown']} / -\n"
                f"Duplicates: {sum(meta['duplicates'].values())}\n"
                f"Automatically normalized times: {meta.get('time_normalized', 0)} (included in duplicates)\n"
                f"Failed: {len(meta['errors'])}\n"
                f"Conflicts: {len(meta.get('conflicts', []))}"
            )
            if meta.get("time_backup"):
                message += f"\nBefore-normalization backup: {meta['time_backup']}"
            if meta["unknown_actions"]:
                message += "\nUnsupported actions:\n" + "\n".join(
                    f"  {action}: {count}" for action, count in meta["unknown_actions"].items()
                )
            if meta["errors"]:
                message += "\nFirst errors:\n" + "\n".join(
                    f"  Row {issue['row']} ({issue['action']}): {issue['message']}"
                    for issue in meta["errors"][:5]
                )
                message += "\nSee the log for all errors."
            if meta["status"] == "complete":
                messagebox.showinfo("Success", message)
            elif meta["status"] == "cancelled":
                messagebox.showwarning(
                    "Import cancelled", message + "\nAlready imported rows have been kept."
                )
            else:
                messagebox.showwarning("Import incomplete", message)
            if self.last_import_comparisons:
                self.show_import_conflicts()

    def _operation_blocked(self) -> bool:
        if getattr(self, "data_operation_active", False):
            messagebox.showwarning("Operation in progress", "Wait for the current import/synchronization to finish.")
            return True
        return False

    def _begin_operation(self) -> None:
        self.data_operation_active = True
        self.menu_manager.update_states(self.db)

    def _end_operation(self) -> None:
        self.data_operation_active = False
        self.menu_manager.update_states(self.db)
        if getattr(self, "_exit_after_operation", False):
            self._exit_after_operation = False
            self.on_exit()

    def show_import_conflicts(self) -> None:
        comparisons = getattr(self, "last_import_comparisons", [])
        if comparisons:
            ImportConflictsDialog(self.root, comparisons).show()

    def _setup_trading212(self) -> Trading212Connection | None:
        if self.db.current_db_path is None:
            raise RuntimeError("Open a database first")
        dialog = Trading212ConnectionDialog(self.root, self.db.current_db_path, load_connection(self.db))
        try:
            connection = dialog.show()
            if connection is not None:
                self.update_title()
            return connection
        finally:
            self._exit_after_operation = self._exit_after_operation or dialog.exit_requested

    def configure_trading212(self) -> None:
        if self._operation_blocked() or self.db.current_db_path is None:
            return
        self._begin_operation()
        try:
            self._setup_trading212()
        except Exception as error:
            self.db.logger.exception("Trading212 connection setup failed")
            messagebox.showerror("Trading212 connection", str(error))
        finally:
            self._end_operation()

    def refresh_trading212_years(self) -> None:
        self.read_trading212_transactions(select_refresh=True)

    def read_trading212_transactions(self, *, select_refresh: bool = False) -> None:
        if self._operation_blocked() or self.db.current_db_path is None:
            return
        self._begin_operation()
        self.last_import_comparisons = []
        outcome: SyncResult | None = None
        try:
            connection = load_connection(self.db)
            if connection is None or not get_config().get_trading212_archive_directory():
                connection = self._setup_trading212()
            if connection is None or self._exit_after_operation:
                return
            archive_directory = get_config().get_trading212_archive_directory()
            if not archive_directory:
                raise ValueError("Choose an archive directory on this computer in Trading212 connection settings")
            refresh: tuple[int, ...] = ()
            if select_refresh:
                options = Trading212RefreshDialog(self.root, connection.first_year)
                try:
                    selected = options.show()
                finally:
                    self._exit_after_operation = self._exit_after_operation or options.exit_requested
                if selected is None or self._exit_after_operation:
                    return
                refresh = selected
            database_path = self.db.current_db_path
            if database_path is None:
                raise RuntimeError("The database was closed")
            dialog = Trading212WorkerDialog(
                self.root, "Read transactions from Trading212",
                lambda cancel, notify: Trading212Sync(
                    database_path, connection, refresh_years=refresh,
                    archive_directory=archive_directory,
                    cancel_event=cancel, on_progress=notify,
                ).run(),
            )
            try:
                outcome = dialog.show()
            finally:
                self._exit_after_operation = self._exit_after_operation or dialog.exit_requested
            if outcome is not None:
                self.last_import_comparisons = outcome.comparisons
                self.filter_manager.update_year_list()
                self.update_views()
        except Exception as error:
            self.db.logger.exception("Trading212 GUI operation failed")
            if not self._exit_after_operation:
                messagebox.showerror("Trading212 synchronization", str(error))
        finally:
            exit_requested = self._exit_after_operation
            self._end_operation()
        if outcome is not None and not exit_requested:
            self._show_sync_result(outcome)

    def _show_sync_result(self, outcome: SyncResult) -> None:
        window = tk.Toplevel(self.root)
        window.title(f"Trading212 synchronization: {outcome.status}")
        frame = ttk.Frame(window, padding=10)
        frame.pack(fill="both", expand=True)
        text = tk.Text(frame, width=100, height=22, wrap="word")
        scrollbar = ttk.Scrollbar(frame, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        text.insert("1.0", outcome.summary())
        text.configure(state="disabled")
        if outcome.comparisons:
            ttk.Button(window, text="View conflicts (read only)", command=self.show_import_conflicts).pack(pady=5)
        ttk.Button(window, text="Close", command=window.destroy).pack(pady=5)
        window.transient(self.root)
        window.wait_visibility()
        window.grab_set()
        self.root.wait_window(window)
    def create_database(self):
        """Create a new SQLite database"""
        if self._operation_blocked():
            return
        self.last_import_comparisons = []
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
                self.filter_manager.update_year_list()
                self.filter_manager.init_date_filters_from_db()
                self.filter_manager.update_filters()
                self.update_views()
                
                # Update UI to reflect loaded mode
                self.menu_manager.update_exchange_rate_display(self.db)
            except Exception as e:
                messagebox.showerror("Error", f"Error creating database: {str(e)}")

    def open_database(self):
        """Open an existing SQLite database"""
        if self._operation_blocked():
            return
        self.last_import_comparisons = []
        file_path = filedialog.askopenfilename(
            filetypes=[("SQLite Database", "*.db"), ("All files", "*.*")]
        )
        if file_path:
            self._connect_database(file_path)

    def _connect_database(self, file_path: str) -> None:
        """Connect a selected or restored database and refresh the UI."""
        if self._operation_blocked():
            return
        self.last_import_comparisons = []
        try:
            self.db.open_database(file_path)
            self.update_title()
            self.menu_manager.update_states(self.db)
            self.filter_manager.update_year_list()
            self.filter_manager.init_date_filters_from_db()
            self.filter_manager.update_filters()
            self.update_views()
            self.menu_manager.update_exchange_rate_display(self.db)
        except Exception as e:
            self.db.close()
            self.update_title()
            self.menu_manager.update_states(self.db)
            self.db.logger.exception("Error opening database")
            messagebox.showerror("Error", f"Error opening database: {str(e)}")

    def restore_last_database(self) -> None:
        """Reconnect the last session's database only if its file still exists."""
        try:
            file_path = get_config().get_last_database_path()
            if file_path:
                if os.path.isfile(file_path):
                    self._connect_database(file_path)
                else:
                    self.db.logger.info("Last database file no longer exists: %s", file_path)
        except (OSError, ValueError) as e:
            self.db.logger.exception("Error restoring last database configuration")
            messagebox.showerror("Error", f"Error restoring last database: {str(e)}")

    def release_database(self):
        """Release the current database"""
        if self._operation_blocked():
            return
        self.last_import_comparisons = []
        if not self.db.conn:
            messagebox.showwarning("Warning", "No database is currently open!")
            return

        try:
            self.db.release_database()
            self.update_title()
            self.menu_manager.update_states(self.db)
            self.update_views()
            self.filter_manager.update_year_list()
        except Exception as e:
            messagebox.showerror("Error", f"Error releasing database: {str(e)}")

    def save_database_as(self):
        """Save the current database to a new file"""
        if self._operation_blocked():
            return
        self.last_import_comparisons = []
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
        if self._operation_blocked():
            return
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
            self._begin_operation()
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
            finally:
                self._end_operation()

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
        self.year_combobox.bind("<<ComboboxSelected>>", self.filter_manager.on_year_selected)

        ttk.Label(top_frame, text="  ").grid(row=0, column=2) # Spacer

        # Date 'From' Picker (store label and picker for hiding/disabling)
        self.date_from_label = ttk.Label(top_frame, text="Date from:")
        self.date_from_label.grid(row=0, column=3, padx=(10, 5), pady=5, sticky="w")
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
        
        # Bind notebook tab change event to handle filter visibility
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)

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

        # --- 7. Tab 5: Pairs View ---
        tab_pairs = ttk.Frame(self.notebook)
        self.notebook.add(tab_pairs, text="Pairing")
        self.pairs_view.create_view(tab_pairs)

        # --- 8. Tab 6: Open Positions View ---
        tab_open_positions = ttk.Frame(self.notebook)
        self.notebook.add(tab_open_positions, text="Open Positions")
        self.open_positions_view.create_view(tab_open_positions)

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
        tree.bind("<Control-c>", lambda e: copy_treeview_to_clipboard(e, self.root))
        tree.bind("<Control-C>", lambda e: copy_treeview_to_clipboard(e, self.root))

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

    def update_pairs_view(self):
        """
        Update the pairs view with current filter dates.
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
        self.pairs_view.update_view(start_ts, end_ts)

    def update_open_positions_view(self):
        """
        Update the open positions view.
        For open positions, only the 'to' date matters (positions as of that date).
        The 'from' date is ignored as we show all open positions from the beginning.
        """
        # Parse date range (only end_ts is used)
        date_to_str = self.date_to_var.get().strip()
        try:
            end_ts = DatabaseManager.timestr_to_timestamp(f"{date_to_str} 23:59:59")
        except Exception:
            end_ts = int(datetime.now().timestamp())
        
        # Delegate to view (start_ts is ignored by the view, but required by interface)
        self.open_positions_view.update_view(0, end_ts)

    def update_views(self):
        """Update all views with data from the database."""
        # This function calls specific update functions for each view
        self.update_interests_view()
        self.update_dividends_view()
        self.update_trades_view()
        self.update_realized_income_view()
        self.update_pairs_view()
        self.update_open_positions_view()

    ###########################################################
    # Widgets command handlers
    ###########################################################
    def on_tab_changed(self, event):
        """
        Handle notebook tab change event.
        Hides/disables the 'From' date filter when Open Positions tab is active.
        """
        # Get the currently selected tab index
        current_tab = self.notebook.index(self.notebook.select())
        
        # Tab 6 is Open Positions (0-indexed: Trades=0, Dividends=1, Interests=2, 
        # Realized Income=3, Pairing=4, Open Positions=5)
        if current_tab == 5:  # Open Positions tab
            # Disable the 'From' date picker and label
            self.date_from_label.config(foreground='gray')
            self.date_from_picker.config(state='disabled')
        else:
            # Enable the 'From' date picker and label for other tabs
            self.date_from_label.config(foreground='black')
            self.date_from_picker.config(state='normal')
    
    def apply_filter(self):
        """Handles the logic when the filter button is pressed."""
        # Check if the selected date range represents a full year
        date_from_str = self.date_from_var.get()
        date_to_str = self.date_to_var.get()
        
        try:
            date_from = datetime.strptime(date_from_str, "%Y-%m-%d")
            date_to = datetime.strptime(date_to_str, "%Y-%m-%d")
            
            # Check if it's a full year (Jan 1 to Dec 31 of the same year)
            if (date_from.month == 1 and date_from.day == 1 and
                date_to.month == 12 and date_to.day == 31 and
                date_from.year == date_to.year):
                # Set the year selector to this year
                self.year_combobox.set(str(date_from.year))
            else:
                # Clear the year selector
                self.year_combobox.set('')
        except (ValueError, AttributeError):
            # If parsing fails or year_combobox doesn't exist, just clear it
            if self.year_combobox:
                self.year_combobox.set('')

        # Calls update_views, which handles the filtering for all relevant tabs
        self.update_views()

    ###########################################################
    # Main Loop
    ###########################################################
    def on_exit(self) -> None:
        """Save the session database path before closing the connection."""
        if self._operation_blocked():
            return
        try:
            database_path = self.db.current_db_path if self.db.conn else None
            get_config().save_last_database_path(database_path)
            self.db.close()
        except Exception as e:
            self.db.logger.exception("Error saving application session")
            messagebox.showerror("Error", f"Error closing application: {str(e)}")
            return
        self.last_import_comparisons = []
        self.root.destroy()

    def run(self):
        self.root.mainloop()

###########################################################
# Application Entry Point
###########################################################
def main() -> None:
    TradingToolsApp().run()


if __name__ == "__main__":
    main()