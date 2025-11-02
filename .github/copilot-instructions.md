# TradingTools AI Assistant Guide

This guide helps AI coding assistants understand the key aspects of the TradingTools project to provide more contextual and accurate assistance.

## Project Overview

TradingTools is a Python-based desktop application that provides tools for analyzing trading data. The application uses:
- Tkinter for the GUI framework
- Pandas for data manipulation and analysis
- CSV files as the primary data source

## Core Architecture

### Main Components

1. `TradingToolsApp` (in `app.py`): 
   - Main application class that initializes the GUI
   - Handles menu creation and event bindings
   - Manages the application lifecycle

### Key Patterns

1. **GUI Structure**
   - Uses Tkinter's object-oriented approach
   - Main window (`self.root`) contains a menubar and main frame
   - Components are arranged using the `pack` geometry manager

2. **File Handling**
   - CSV files are the primary data format
   - Uses `pandas.read_csv()` for data loading
   - File operations are wrapped in try-except blocks for error handling

## Development Setup

### Dependencies
Required Python packages:
- tkinter (usually comes with Python)
- pandas

### Running the Application
```powershell
python app.py
```

## Common Development Tasks

### Adding New Features
1. For new UI elements:
   - Add them to the main frame (`self.main_frame`)
   - Follow the existing pattern of creating methods for event handlers

2. For new data processing:
   - Add methods to the `TradingToolsApp` class
   - Use pandas DataFrame operations for data manipulation

### Error Handling
- Wrap file operations and data processing in try-except blocks
- Print error messages to console (currently using print statements)

### Debugging
1. VS Code Debugging:
   - Use the Python Debug Configuration
   - Set breakpoints in the code by clicking the left margin
   - Press F5 to start debugging
   - Key debug views:
     - Variables: Monitor local and class variables
     - Call Stack: Track execution flow
     - Debug Console: Evaluate expressions

2. Tkinter-Specific Debug Tips:
   - Add print statements in event handlers to trace UI interactions
   - Use `self.root.update()` to force GUI updates during debugging
   - Set breakpoints after GUI elements are created to inspect widget properties

3. Data Debugging:
   - Add `print(df.head())` and `print(df.info())` for DataFrame inspection
   - Use `print(df.shape)` to verify data dimensions
   - Set breakpoints after DataFrame operations to verify transformations

## Integration Points

### Data Input/Output
- Input: CSV files through file dialog
- Output: Currently only console output for debugging

## Future Considerations
The codebase is in early stages with opportunities for:
- Adding data visualization capabilities
- Implementing data export functionality
- Adding analysis tools
- Improving error handling with proper logging

---
Note: This is a baseline guide that should be updated as the project evolves and new patterns emerge.