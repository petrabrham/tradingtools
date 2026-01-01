"""
UI Utilities - Common UI helper functions
"""
from tkinter import ttk


def copy_treeview_to_clipboard(event, root):
    """
    Copy selected treeview rows to clipboard as tab-separated values.
    
    Args:
        event: Event containing the widget
        root: Root tk window for clipboard access
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
    root.clipboard_clear()
    root.clipboard_append(clipboard_text)
    
    # Show confirmation (optional)
    print(f"Copied {len(selection)} row(s) to clipboard")
