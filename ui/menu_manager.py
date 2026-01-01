"""
Menu Manager - Handles menu bar creation and state management
"""
import tkinter as tk
from tkinter import ttk


class MenuManager:
    """Manages the application menu bar and its states."""
    
    def __init__(self, root, app):
        """
        Initialize the menu manager.
        
        Args:
            root: Root tk window
            app: Reference to main TradingToolsApp for callbacks and state
        """
        self.root = root
        self.app = app
        self.file_menu = None
        self.options_menu = None
        self.menubar = None
    
    def create_menu(self):
        """Create the application menu bar with File and Options menus."""
        self.menubar = tk.Menu(self.root)
        
        # File menu
        self.file_menu = tk.Menu(self.menubar, tearoff=0)
        self.file_menu.add_command(label="New Database", command=self.app.create_database)
        self.file_menu.add_command(label="Connect Database", command=self.app.open_database)
        self.file_menu.add_command(label="Save Database Copy As...", command=self.app.save_database_as, state='disabled')
        self.file_menu.add_command(label="Release Database", command=self.app.release_database, state='disabled')
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Import CSV", command=self.app.open_csv_file, state='disabled')
        self.file_menu.add_command(label="Import Annual Exchange Rates...", command=self.app.import_annual_rates, state='disabled')
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Exit", command=self.root.quit)
        self.menubar.add_cascade(label="File", menu=self.file_menu)
        
        # Options menu
        self.options_menu = tk.Menu(self.menubar, tearoff=0)
        self.options_menu.add_checkbutton(
            label="Calculate taxes from JSON config",
            variable=self.app.use_json_tax_rates,
            command=self.app.on_tax_calculation_method_changed
        )
        self.options_menu.add_separator()
        # Exchange rate mode is read-only - displayed but not changeable
        self.options_menu.add_command(
            label="Exchange rate mode: (no database)",
            state='disabled'
        )
        self.menubar.add_cascade(label="Options", menu=self.options_menu)
        
        self.root.config(menu=self.menubar)
    
    def update_states(self, db_manager):
        """
        Update menu items states based on database connection.
        
        Args:
            db_manager: DatabaseManager instance to check connection state
        """
        if not self.file_menu:
            return
        
        try:
            if db_manager.conn:
                # DB is connected
                self.file_menu.entryconfig("Import CSV", state='normal')
                self.file_menu.entryconfig("Save Database Copy As...", state='normal')
                self.file_menu.entryconfig("Release Database", state='normal')
                # Annual rates import only available for databases using annual rates
                if db_manager.use_annual_rates:
                    self.file_menu.entryconfig("Import Annual Exchange Rates...", state='normal')
                else:
                    self.file_menu.entryconfig("Import Annual Exchange Rates...", state='disabled')
            else:
                # No DB connected
                self.file_menu.entryconfig("Import CSV", state='disabled')
                self.file_menu.entryconfig("Save Database Copy As...", state='disabled')
                self.file_menu.entryconfig("Release Database", state='disabled')
                self.file_menu.entryconfig("Import Annual Exchange Rates...", state='disabled')
        except Exception:
            # fallback: do nothing if entryconfig fails
            pass
    
    def update_exchange_rate_display(self, db_manager):
        """
        Update the Options menu to show the current exchange rate mode (read-only).
        
        Args:
            db_manager: DatabaseManager instance to check rate mode
        """
        if not self.options_menu or not db_manager.conn:
            return
        
        rate_mode = "Annual GFŘ" if db_manager.use_annual_rates else "Daily CNB"
        
        # Find and update the exchange rate menu item (last item)
        menu_index = self.options_menu.index('end')
        self.options_menu.entryconfig(
            menu_index,
            label=f"Exchange rate mode: {rate_mode} (immutable)",
            state='disabled'
        )
