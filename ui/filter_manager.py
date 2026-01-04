"""
Filter Manager - Handles date filtering and year selection
"""
from datetime import datetime


class FilterManager:
    """Manages date filters and year selection for the application."""
    
    def __init__(self, app):
        """
        Initialize the filter manager.
        
        Args:
            app: Reference to main TradingToolsApp for accessing state and callbacks
        """
        self.app = app
    
    def on_year_selected(self, event):
        """
        Handle year selection from combobox.
        Sets date filters to the first and last day of the selected year.
        
        Args:
            event: Event from the combobox selection
        """
        if not self.app.year_combobox:
            return
        year_str = self.app.year_combobox.get()
        if not year_str:
            # If year is cleared, don't change date filters
            return
        try:
            year = int(year_str)
        except ValueError:
            return
            
        # Set date_from_var and date_to_var to first and last day of year
        date_from = f"{year}-01-01"
        date_to = f"{year}-12-31"
        self.app.date_from_var.set(date_from)
        self.app.date_to_var.set(date_to)
        self.app.update_views()
    
    def update_year_list(self):
        """Update the year combobox with years from all tables in the DB."""
        if not self.app.db.conn:
            if self.app.year_combobox:
                self.app.year_combobox.configure(values=[])
                self.app.year_combobox.set('')
            return
        try:
            years = self.app.db.get_all_years_with_data()
            year_strings = [str(y) for y in years]
            self.app.year_combobox.configure(values=year_strings)
            if year_strings:
                self.app.year_combobox.set(year_strings[0])  # Select first year by default
        except Exception:
            if self.app.year_combobox:
                self.app.year_combobox.configure(values=[])
                self.app.year_combobox.set('')
    
    def init_date_filters_from_db(self):
        """Initialize date filters to the first available year from the database."""
        if not self.app.db.conn or not self.app.year_combobox:
            return
        year_str = self.app.year_combobox.get()
        if year_str:
            year = int(year_str)
            self.app.date_from_var.set(f"{year}-01-01")
            self.app.date_to_var.set(f"{year}-12-31")
    
    def update_filters(self):
        """Update filter variables based on current widget states."""
        # Currently, date_from_var and date_to_var are directly linked to Entry widgets
        # If additional processing is needed, it can be done here
        pass
