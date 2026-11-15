import unittest
from unittest.mock import Mock, patch

from tradingtools.views.pairs_view import PairsView


class TestManualPairingView(unittest.TestCase):
    def setUp(self):
        self.view = PairsView.__new__(PairsView)
        self.sales = Mock()
        self.lots = Mock()
        self.repo = Mock()
        self.trades = Mock()
        self.refresh = Mock()
        self.load_lots = Mock()
        self.load_pairings = Mock()
        self.select_pairings = Mock()
        self.changed = Mock()
        self.view.sales_tree = self.sales
        self.view.lots_tree = self.lots
        self.view.pairings_repo = self.repo
        self.view.trades_repo = self.trades
        self.view.logger = Mock()
        self.view.current_sale_id = 10
        self.view.current_start_timestamp = 100
        self.view.current_end_timestamp = 200
        self.view.refresh_view = self.refresh
        self.view._load_available_lots = self.load_lots
        self.view._load_current_pairings = self.load_pairings
        self.view._select_pairings_for_sale = self.select_pairings
        self.view._get_pairing_filter_flags = Mock(return_value=(False, False))
        self.view.on_pairings_changed = self.changed
        self.lots.selection.return_value = ("20",)
        self.lots.item.return_value = ("2020-01-01", "10", "10")
        self.sales.exists.return_value = True
        self.sales.item.return_value = (
            "Example", "EX", "2024-01-01", "10", "10", "1", "10", "Unpaired"
        )
        self.repo.create_manual_pairing.return_value = {"success": True}

    @patch("tradingtools.views.pairs_view.messagebox.showerror")
    @patch("tradingtools.views.pairs_view.messagebox.showinfo")
    @patch("tradingtools.views.pairs_view.simpledialog.askfloat", return_value=4.0)
    def test_success_keeps_sales_rows_and_selection_and_refreshes_dependent_tables(
        self, _askfloat, showinfo, showerror
    ):
        for selection in (("10",), ("10", "11")):
            for remaining, status, tag in (
                (6.0, "Partially Paired", ""),
                (0.0, "Fully Paired", "paired"),
            ):
                with self.subTest(selection=selection, remaining=remaining):
                    self.sales.reset_mock()
                    self.sales.selection.return_value = selection
                    self.trades.get_remaining_quantity.return_value = -remaining
                    self.view._pair_manually()
                    self.assertEqual(self.view.current_sale_id, 10)
                    self.assertEqual(self.sales.selection(), selection)
                    self.sales.set.assert_any_call("10", "Remaining", f"{remaining:.9f}")
                    self.sales.set.assert_any_call("10", "Status", status)
                    self.sales.item.assert_any_call("10", tags=(tag,))
                    self.load_lots.assert_called_with(10)
                    self.load_pairings.assert_called_with(100, 200)
                    self.select_pairings.assert_called_with(10)
        self.sales.delete.assert_not_called()
        self.sales.insert.assert_not_called()
        self.sales.selection_set.assert_not_called()
        self.sales.selection_remove.assert_not_called()
        self.refresh.assert_not_called()
        self.assertEqual(self.changed.call_count, 4)
        showinfo.assert_not_called()
        showerror.assert_not_called()

    @patch("tradingtools.views.pairs_view.messagebox.showerror")
    @patch("tradingtools.views.pairs_view.simpledialog.askfloat", return_value=4.0)
    def test_failed_pairing_reports_error_without_refreshing(self, _askfloat, showerror):
        self.repo.create_manual_pairing.return_value = {
            "success": False, "error": "Not enough shares"
        }
        self.view._pair_manually()
        showerror.assert_called_once_with(
            "Error", "Failed to create pairing:\nNot enough shares"
        )
        self.load_lots.assert_not_called()
        self.load_pairings.assert_not_called()
        self.sales.set.assert_not_called()
        self.changed.assert_not_called()

    @patch("tradingtools.views.pairs_view.simpledialog.askfloat", return_value=None)
    def test_cancel_leaves_tables_unchanged(self, _askfloat):
        self.view._pair_manually()
        self.repo.create_manual_pairing.assert_not_called()
        self.load_lots.assert_not_called()
        self.load_pairings.assert_not_called()
        self.sales.set.assert_not_called()
        self.changed.assert_not_called()


if __name__ == "__main__":
    unittest.main()
