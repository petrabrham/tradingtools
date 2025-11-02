import tkinter as tk
from tkinter import filedialog
import pandas as pd
import sys

class TradingToolsApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Trading Tools")
        self.root.geometry("800x600")
        
        # Create menu
        self.create_menu()
        
        # Create main frame
        self.main_frame = tk.Frame(self.root)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

    def create_menu(self):
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Import CSV", command=self.open_csv_file)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)
        self.root.config(menu=menubar)

    def open_csv_file(self):
        file_path = filedialog.askopenfilename(
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if file_path:
            try:
                df = pd.read_csv(file_path)
                # Add your data processing logic here
                print(f"Loaded CSV file: {file_path}")
                print(f"Data shape: {df.shape}")
            except Exception as e:
                print(f"Error loading file: {e}")

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    app = TradingToolsApp()
    app.run()