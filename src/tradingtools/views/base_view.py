"""
Base view class for all TradingTools views.

Provides common interface and utilities for view implementations.
"""

from abc import ABC, abstractmethod
from tkinter import ttk
import tkinter as tk


class BaseView(ABC):
    """Abstract base class for all views in the application."""
    
    def __init__(self, db_manager):
        """
        Initialize the base view.
        
        Args:
            db_manager: DatabaseManager instance for data access
        """
        self.db = db_manager
        self.tree = None
    
    @abstractmethod
    def create_view(self, parent_frame: ttk.Frame) -> None:
        """
        Create the view UI components.
        
        Args:
            parent_frame: The parent frame to create the view in
        """
        pass
    
    @abstractmethod
    def update_view(self, start_timestamp: int, end_timestamp: int) -> None:
        """
        Update the view with data for the given time range.
        
        Args:
            start_timestamp: Start of date range (Unix timestamp)
            end_timestamp: End of date range (Unix timestamp)
        """
        pass
    
    def clear_view(self) -> None:
        """Clear all items from the tree view."""
        if self.tree:
            for item in self.tree.get_children():
                self.tree.delete(item)
    
    def copy_to_clipboard(self, event, root_widget) -> None:
        """
        Copy selected treeview rows to clipboard as tab-separated values.
        
        Args:
            event: The event that triggered the copy
            root_widget: The root Tk widget for clipboard access
        """
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
            headers = [widget.heading(col)['text'] for col in columns]
            lines.append('\t'.join(headers))
        
        # Add data rows
        for item_id in selection:
            values = widget.item(item_id)['values']
            lines.append('\t'.join(str(v) for v in values))
        
        # Copy to clipboard
        clipboard_text = '\n'.join(lines)
        root_widget.clipboard_clear()
        root_widget.clipboard_append(clipboard_text)
        
        print(f"Copied {len(selection)} row(s) to clipboard")
