import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from tradingtools.db.dbmanager import DatabaseManager
from tradingtools.views.realized_income_view import RealizedIncomeView
from tradingtools.views.open_positions_view import OpenPositionsView
from tradingtools.views.pairs_view import PairsView


class TestViewDatabaseSwitch(unittest.TestCase):
    def setUp(self):
        with patch("tradingtools.db.dbmanager.setup_logger", return_value=Mock()):
            self.db = DatabaseManager()
        self.db.create_database(":memory:")
        self.addCleanup(self.db.close)
        self.realized = RealizedIncomeView(self.db, Mock())
        self.realized.tree = Mock()
        self.realized.tree.get_children.return_value = ()
        self.realized.realized_pnl_var = Mock()
        self.realized.total_buy_cost_var = Mock()
        self.realized.total_sell_proceeds_var = Mock()
        self.realized.unrealized_shares_var = Mock()
        self.realized.warning_label = Mock()
        self.positions = OpenPositionsView(self.db, Mock())
        self.positions.tree = Mock()
        self.positions.tree.get_children.return_value = ()
        self.pairs = PairsView(self.db, Mock())
        self.pairs._load_sales_in_interval = Mock()
        self.pairs._load_current_pairings = Mock()

    def test_release_then_create_refreshes_cached_and_nested_repositories(self):
        previous = self.db.conn
        self.db.release_database()
        self.db.create_database(":memory:")
        self.assertIsNot(self.db.conn, previous)
        with patch("tkinter.messagebox.showerror") as error:
            self.realized.update_view(0, 2_000_000_000)
            self.positions.update_view(0, 2_000_000_000)
            self.pairs.update_view(0, 2_000_000_000)
        error.assert_not_called()
        for repo in (
            self.realized.pairings_repo, self.realized.pairings_repo.trades_repo,
            self.positions.trades_repo, self.pairs.pairings_repo,
            self.pairs.pairings_repo.trades_repo, self.pairs.trades_repo,
        ):
            self.assertIs(repo.conn, self.db.conn)
            self.assertEqual(repo.conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0], 0)

    def test_opening_another_database_displays_its_positions(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.addCleanup(self.db.close)
        path = str(Path(directory.name) / "other.db")
        with patch("tkinter.messagebox.showerror") as error:
            self.db.create_database(path)
            connection = self.db.conn
            assert connection is not None
            connection.executescript(
                "INSERT INTO securities(isin,ticker,name) VALUES('US0000000001','NEW','New DB security');"
                "INSERT INTO trades(timestamp,isin_id,id_string,trade_type,number_of_shares,"
                "remaining_quantity,price_for_share,currency_of_price,total_czk) "
                "VALUES(100,1,'new-trade',1,2,2,5,'CZK',-10);"
            )
            self.db.open_database(path)
            with patch.object(self.positions.tree, "insert") as insert:
                self.realized.update_view(0, 2_000_000_000)
                self.positions.update_view(0, 2_000_000_000)
                self.pairs.update_view(0, 2_000_000_000)
            error.assert_not_called()
            values = insert.call_args.kwargs["values"]
            self.assertEqual(values[:4], ("US0000000001", "New DB security", "NEW", "2"))
            self.assertIs(self.pairs.pairings_repo.trades_repo.conn, self.db.conn)
            self.db.close()


if __name__ == "__main__":
    unittest.main()
