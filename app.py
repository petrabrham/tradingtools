import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import ttk  # Required for Treeview and Notebook
import pandas as pd
import sys
import os
from dbmanager import DatabaseManager
from datetime import datetime, timedelta

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
        self.create_widgets()
        
        # Initial state update
        self.update_menu_states()
        self.update_title()
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
        self.create_interest_view(tab_interests)

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
        """Creates a view to dividends data."""
        # TODO: Implement dividends view
        pass

    def create_interests_view(self, parent_frame: ttk.Frame):
        """Creates a view to interests data."""
        # TODO: Implement interests view
        pass

    def update_views(self):
        """Update all views with data from the database."""
        pass

    ###########################################################
    # Widgets command handlers
    ###########################################################
    def apply_filter(self):
        """Handles the logic when the filter button is pressed."""
        date_from = self.date_from_var.get()
        date_to = self.date_to_var.get()

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