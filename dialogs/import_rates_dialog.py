"""
Import Rates Dialog - Year and file selection for annual rates import
"""
import tkinter as tk
from tkinter import filedialog, messagebox
from datetime import datetime
import os


class ImportRatesDialog:
    """Dialog for selecting year and file when importing annual exchange rates."""
    
    def __init__(self, parent, available_years=None):
        """
        Initialize the import rates dialog.
        
        Args:
            parent: Parent tk window
            available_years: List of years that already have rates in the database
        """
        self.parent = parent
        self.available_years = available_years or []
        self.result_year = None
        self.result_file_path = None
    
    def show(self):
        """
        Display the dialog and return the selected year and file.
        
        Returns:
            Tuple of (year, file_path) if user confirmed
            Tuple of (None, None) if user cancelled
        """
        dialog = tk.Toplevel(self.parent)
        dialog.title("Import Annual Exchange Rates")
        dialog.geometry("450x200")
        dialog.resizable(False, False)
        dialog.transient(self.parent)
        dialog.grab_set()
        
        # Center the dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (dialog.winfo_width() // 2)
        y = (dialog.winfo_screenheight() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")
        
        self.result_year = None
        self.result_file_path = None
        
        tk.Label(
            dialog,
            text="Select year and file to import",
            font=("Arial", 11, "bold")
        ).pack(pady=10)
        
        if self.available_years:
            tk.Label(
                dialog,
                text=f"Available years: {', '.join(map(str, self.available_years))}",
                fg="blue"
            ).pack(pady=5)
        
        # Year entry
        year_frame = tk.Frame(dialog)
        year_frame.pack(pady=10)
        
        tk.Label(year_frame, text="Year:").pack(side=tk.LEFT, padx=5)
        year_entry = tk.Entry(year_frame, width=10)
        year_entry.insert(0, str(datetime.now().year))
        year_entry.pack(side=tk.LEFT, padx=5)
        
        # File selection
        file_frame = tk.Frame(dialog)
        file_frame.pack(pady=10)
        
        tk.Label(file_frame, text="File:").pack(side=tk.LEFT, padx=5)
        file_label = tk.Label(file_frame, text="No file selected", width=30, anchor='w', relief='sunken')
        file_label.pack(side=tk.LEFT, padx=5)
        
        def browse_file():
            file_path = filedialog.askopenfilename(
                title="Select annual rates file",
                filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
            )
            if file_path:
                self.result_file_path = file_path
                file_label.config(text=os.path.basename(file_path))
        
        tk.Button(file_frame, text="Browse...", command=browse_file).pack(side=tk.LEFT, padx=5)
        
        def on_import():
            try:
                year = int(year_entry.get())
                if year < 1990 or year > 2100:
                    messagebox.showerror("Error", "Invalid year. Please enter a year between 1990 and 2100.")
                    return
                self.result_year = year
                
                if not self.result_file_path:
                    messagebox.showerror("Error", "Please select a file to import.")
                    return
                
                dialog.destroy()
            except ValueError:
                messagebox.showerror("Error", "Invalid year. Please enter a valid number.")
        
        def on_cancel():
            self.result_year = None
            self.result_file_path = None
            dialog.destroy()
        
        button_frame = tk.Frame(dialog)
        button_frame.pack(pady=15)
        
        tk.Button(button_frame, text="Import", command=on_import, width=10, bg="#4CAF50", fg="white").pack(side=tk.LEFT, padx=10)
        tk.Button(button_frame, text="Cancel", command=on_cancel, width=10).pack(side=tk.LEFT, padx=10)
        
        self.parent.wait_window(dialog)
        
        return (self.result_year, self.result_file_path)
