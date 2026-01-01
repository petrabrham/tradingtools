"""
Exchange Rate Dialog - Mode selection for database creation
"""
import tkinter as tk


class ExchangeRateDialog:
    """Dialog for selecting exchange rate calculation method when creating a database."""
    
    def __init__(self, parent):
        """
        Initialize the exchange rate dialog.
        
        Args:
            parent: Parent tk window
        """
        self.parent = parent
        self.result = None
    
    def show(self):
        """
        Display the dialog and return the selected mode.
        
        Returns:
            True if user selected Annual GFŘ rates
            False if user selected Daily CNB rates
            None if user cancelled
        """
        dialog = tk.Toplevel(self.parent)
        dialog.title("Exchange Rate Mode")
        dialog.geometry("500x250")
        dialog.resizable(False, False)
        dialog.transient(self.parent)
        dialog.grab_set()
        
        # Center the dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (dialog.winfo_width() // 2)
        y = (dialog.winfo_screenheight() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")
        
        self.result = None
        
        tk.Label(
            dialog,
            text="Choose Exchange Rate Calculation Method",
            font=("Arial", 12, "bold")
        ).pack(pady=10)
        
        tk.Label(
            dialog,
            text="This setting is permanent and cannot be changed after database creation.",
            fg="red"
        ).pack(pady=5)
        
        tk.Label(
            dialog,
            text="\nDaily CNB rates: Precise daily exchange rates from Czech National Bank\n"
                 "Annual GFŘ rates: Unified yearly rates from General Financial Directorate\n\n"
                 "Note: Both methods are compliant with Czech tax law.",
            justify=tk.LEFT
        ).pack(pady=10, padx=20)
        
        def on_choice(use_annual):
            self.result = use_annual
            dialog.destroy()
        
        button_frame = tk.Frame(dialog)
        button_frame.pack(pady=20)
        
        tk.Button(
            button_frame,
            text="Daily CNB Rates",
            command=lambda: on_choice(False),
            width=20,
            bg="#4CAF50",
            fg="white"
        ).pack(side=tk.LEFT, padx=10)
        
        tk.Button(
            button_frame,
            text="Annual GFŘ Rates",
            command=lambda: on_choice(True),
            width=20,
            bg="#2196F3",
            fg="white"
        ).pack(side=tk.LEFT, padx=10)
        
        self.parent.wait_window(dialog)
        
        return self.result
