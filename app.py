import tkinter as tk
from tkinter import filedialog, messagebox
import pandas as pd
import sys
import os
from dbmanager import DatabaseManager

class TradingToolsApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Trading Tools")
        self.root.geometry("800x600")
        
        # Database manager (moved DB logic to separate module)
        self.db = DatabaseManager()

        # Menu container reference (used to enable/disable items)
        self.file_menu = None

        # Create menu
        self.create_menu()

        # Create main frame
        self.main_frame = tk.Frame(self.root)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

    def create_menu(self):
        menubar = tk.Menu(self.root)
        
        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="New", command=self.create_database)
        file_menu.add_command(label="Open", command=self.open_database)
        file_menu.add_command(label="Save", command=self.save_database)
        file_menu.add_command(label="Save As...", command=self.save_database_as)
        file_menu.add_separator()
        # Import CSV menu item (initially disabled)
        file_menu.add_command(
            label="Import CSV",
            command=self.open_csv_file,
            state='disabled'
        )
        # keep file_menu around so we can update menu states later
        self.file_menu = file_menu
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)
        
        self.root.config(menu=menubar)

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

            except Exception as e:
                messagebox.showerror("Error", f"Error importing CSV file: {str(e)}")

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
                # messagebox.showinfo("Success", "New database created successfully!")
            except Exception as e:
                messagebox.showerror("Error", f"Error creating database: {str(e)}")
                
    def update_title(self):
        """Update the window title with the current database name"""
        base_title = "Trading Tools"
        if self.db.current_db_path:
            db_name = os.path.basename(self.db.current_db_path)
            self.root.title(f"{base_title} - {db_name}")
        else:
            self.root.title(base_title)
            
    def update_menu_states(self):
        """Update menu items states based on database connection"""
        state = 'normal' if self.db.conn else 'disabled'
        if self.file_menu:
            try:
                # we can refer to the menu item by its label
                self.file_menu.entryconfig("Import CSV", state=state)
            except Exception:
                # fallback: do nothing if entryconfig fails
                pass

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
                # messagebox.showinfo("Success", "Database opened successfully!")
            except Exception as e:
                messagebox.showerror("Error", f"Error opening database: {str(e)}")

    def save_database(self):
        """Save the current database"""
        if not self.db.conn:
            messagebox.showwarning("Warning", "No database is currently open!")
            return

        try:
            self.db.save_database()
            # messagebox.showinfo("Success", "Database saved successfully!")
        except Exception as e:
            messagebox.showerror("Error", f"Error saving database: {str(e)}")

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

                messagebox.showinfo("Success", "Database saved successfully!")
            except Exception as e:
                messagebox.showerror("Error", f"Error saving database: {str(e)}")

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    app = TradingToolsApp()
    app.run()