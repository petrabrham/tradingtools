"""
Interests view for displaying interest income data.

Shows interest transactions with summary by interest type.
"""

from tkinter import ttk, messagebox
import tkinter as tk
from datetime import datetime
from .base_view import BaseView
from db.repositories.interests import InterestType


class InterestsView(BaseView):
    """View for displaying interests data with type-based summary."""
    
    def __init__(self, db_manager, root_widget):
        """
        Initialize the interests view.
        
        Args:
            db_manager: DatabaseManager instance for data access
            root_widget: Root Tk widget for clipboard operations
        """
        super().__init__(db_manager)
        self.root_widget = root_widget
        
        # Summary variables (will be set by app)
        self.interest_on_cash_var = None
        self.share_lending_interest_var = None
        self.unknown_interest_var = None
    
    def set_summary_variables(self, interest_on_cash_var, share_lending_interest_var, unknown_interest_var):
        """
        Set the StringVar objects for summary display.
        
        Args:
            interest_on_cash_var: StringVar for cash interest total
            share_lending_interest_var: StringVar for lending interest total
            unknown_interest_var: StringVar for unknown interest total
        """
        self.interest_on_cash_var = interest_on_cash_var
        self.share_lending_interest_var = share_lending_interest_var
        self.unknown_interest_var = unknown_interest_var
    
    def create_view(self, parent_frame: ttk.Frame) -> None:
        """
        Create the interests view UI components.
        
        Args:
            parent_frame: The parent frame to create the view in
        """
        parent_frame.grid_columnconfigure(0, weight=1)
        parent_frame.grid_rowconfigure(0, weight=1)  # Treeview (expands)
        parent_frame.grid_rowconfigure(1, weight=0)  # Summary Panel (fixed height)

        # --- Top Part: Treeview for Interests (Row 0) ---
        treeview_frame = ttk.Frame(parent_frame)
        treeview_frame.grid(row=0, column=0, sticky="nsew")
        treeview_frame.grid_columnconfigure(0, weight=1)
        treeview_frame.grid_rowconfigure(0, weight=1)
        
        columns = ("Date Time", "Type", "Total (CZK)")
        tree = ttk.Treeview(treeview_frame, columns=columns, show='headings')
        tree.grid(row=0, column=0, sticky='nsew')
        self.tree = tree
        
        # Configure columns
        tree.heading("Date Time", text="Date Time")
        tree.column("Date Time", anchor=tk.W, width=150)
        
        tree.heading("Type", text="Type")
        tree.column("Type", anchor=tk.W, width=120)
        
        tree.heading("Total (CZK)", text="Total (CZK)")
        tree.column("Total (CZK)", anchor=tk.E, width=100)
        
        # Scrollbars
        vsb = ttk.Scrollbar(treeview_frame, orient="vertical", command=tree.yview)
        vsb.grid(row=0, column=1, sticky='ns')
        tree.configure(yscrollcommand=vsb.set)

        hsb = ttk.Scrollbar(treeview_frame, orient="horizontal", command=tree.xview)
        hsb.grid(row=1, column=0, sticky='ew')
        tree.configure(xscrollcommand=hsb.set)
        
        # Bind Ctrl+C for clipboard copy
        tree.bind("<Control-c>", lambda e: self.copy_to_clipboard(e, self.root_widget))
        tree.bind("<Control-C>", lambda e: self.copy_to_clipboard(e, self.root_widget))

        # --- Bottom Part: Summary Panel (Row 1) ---
        summary_frame = ttk.LabelFrame(parent_frame, text="Interests Summary")
        summary_frame.grid(row=1, column=0, sticky="ew", pady=(5, 0), padx=2)
        
        # Configure grid for summary frame
        summary_frame.grid_columnconfigure(0, weight=1)  # Label column
        summary_frame.grid_columnconfigure(1, weight=1)  # Entry column (align right)

        # Interest on Cash
        ttk.Label(summary_frame, text="Interest on cash:").grid(row=0, column=0, padx=10, pady=5, sticky="w")
        ttk.Entry(summary_frame, textvariable=self.interest_on_cash_var, state='readonly', width=20, justify='right').grid(row=0, column=1, padx=(0, 10), pady=5, sticky="e")

        # Share Lending Interest
        ttk.Label(summary_frame, text="Share lending interest:").grid(row=1, column=0, padx=10, pady=5, sticky="w")
        ttk.Entry(summary_frame, textvariable=self.share_lending_interest_var, state='readonly', width=20, justify='right').grid(row=1, column=1, padx=(0, 10), pady=5, sticky="e")

        # Unknown Interest
        ttk.Label(summary_frame, text="Unknown interest:").grid(row=2, column=0, padx=10, pady=5, sticky="w")
        ttk.Entry(summary_frame, textvariable=self.unknown_interest_var, state='readonly', width=20, justify='right').grid(row=2, column=1, padx=(0, 10), pady=5, sticky="e")
    
    def update_view(self, start_timestamp: int, end_timestamp: int) -> None:
        """
        Update the interests view with data for the given time range.
        
        Args:
            start_timestamp: Start of date range (Unix timestamp)
            end_timestamp: End of date range (Unix timestamp)
        """
        if not self.tree:
            return
        
        # Clear existing data
        self.clear_view()
        
        # Ensure DB connection exists and repository is initialized
        if not self.db.conn or not self.db.interests_repo:
            if self.interest_on_cash_var:
                self.interest_on_cash_var.set("0.00 CZK")
                self.share_lending_interest_var.set("0.00 CZK")
                self.unknown_interest_var.set("0.00 CZK")
            return

        try:
            # Fetch data from repository
            # Data format: (id, timestamp, type, id_string, total_czk)
            interest_records = self.db.interests_repo.get_by_date_range(start_timestamp, end_timestamp)
            
            # Process and display data
            for _, timestamp, type_int, _, total_czk in interest_records:
                # Convert timestamp back to display string
                dt_obj = self.db.timestamp_to_datetime(timestamp)
                timestamp_str = dt_obj.strftime("%d.%m.%Y %H:%M:%S")
                
                # Convert integer type back to human-readable string
                interest_type = InterestType(type_int)
                if interest_type == InterestType.CASH_INTEREST:
                    type_str = "Interest on cash"
                elif interest_type == InterestType.LENDING_INTEREST:
                    type_str = "Share lending interest"
                else:
                    type_str = "Unknown"

                # Insert into Treeview
                self.tree.insert('', tk.END, values=(
                    timestamp_str,
                    type_str,
                    f"{total_czk:.2f}"
                ))
            
            # Update Summary Fields
            if self.interest_on_cash_var:
                summary = self.db.interests_repo.get_total_interest_by_type(start_timestamp, end_timestamp)
                total_cash_interest = summary.get(InterestType.CASH_INTEREST, 0.0)
                self.interest_on_cash_var.set(f"{total_cash_interest:.2f} CZK")
                total_share_lending = summary.get(InterestType.LENDING_INTEREST, 0.0)
                self.share_lending_interest_var.set(f"{total_share_lending:.2f} CZK")
                total_unknown = summary.get(InterestType.UNKNOWN, 0.0)
                self.unknown_interest_var.set(f"{total_unknown:.2f} CZK")

        except ValueError as e:
            messagebox.showerror("Filter Error", f"Error parsing date: {e}. Check format (YYYY-MM-DD).")
        except Exception as e:
            messagebox.showerror("Database Error", f"Error loading interests from database: {e}")
