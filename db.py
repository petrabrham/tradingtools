import sqlite3
import os
from typing import Optional, Tuple, Dict
import pandas as pd


class DatabaseManager:
    """Simple SQLite database manager.

    Responsibilities:
    - Manage a sqlite3 connection and current database path
    - Provide create/open/save/save-as operations
    - Import pandas DataFrame into the DB
    """

    def __init__(self) -> None:
        self.conn: Optional[sqlite3.Connection] = None
        self.current_db_path: Optional[str] = None

    def close(self) -> None:
        if self.conn:
            try:
                self.conn.close()
            finally:
                self.conn = None
                self.current_db_path = None

    def create_database(self, file_path: str) -> None:
        # close existing
        self.close()
        # create/connect
        self.conn = sqlite3.connect(file_path)
        self.current_db_path = file_path

    def open_database(self, file_path: str) -> None:
        # close existing
        self.close()
        self.conn = sqlite3.connect(file_path)
        self.current_db_path = file_path

    def save_database(self) -> None:
        if not self.conn:
            raise RuntimeError("No open database to save")
        self.conn.commit()

    def save_database_as(self, file_path: str) -> None:
        if not self.conn:
            raise RuntimeError("No open database to save")

        # Create new connection and copy contents using backup
        new_conn = sqlite3.connect(file_path)
        try:
            with new_conn:
                # Use the sqlite3 backup API
                self.conn.backup(new_conn)
        finally:
            # switch to the new connection
            self.close()
            self.conn = new_conn
            self.current_db_path = file_path

    def import_dataframe(self, table_name: str, df: pd.DataFrame) -> Dict[str, object]:
        """Import a pandas DataFrame into the open DB as table_name.

        Returns metadata dict: { 'table': str, 'records': int, 'columns': List[str] }
        """
        if not self.conn:
            raise RuntimeError("No open database to import into")

        # Write DataFrame to SQL (replace if exists)
        df.to_sql(table_name, self.conn, if_exists="replace", index=False)
        self.conn.commit()
        return {
            "table": table_name,
            "records": int(len(df)),
            "columns": list(df.columns),
        }
