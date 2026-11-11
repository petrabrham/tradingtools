# Trade Pairing and Positions

## Current implementation

TradingTools can associate purchase trades with sale trades in the **Pairing** tab. Pairings are stored in the database and use the original trade records as their source.

The Pairing tab displays sales for the selected date range, available purchase lots for the selected sale, and existing pairings. It shows the holding period and time-test qualification for each available lot. Users can pair lots manually, apply an automatic method to selected sales, or apply a method to unpaired and partially paired sales in the displayed interval.

The **Open Positions** tab shows positions aggregated by security as of the selected end date. It includes remaining quantity, total cost in CZK, average price, and earliest/latest trade dates. It is not a lot-by-lot view.

## Matching methods

- **FIFO**: pairs the oldest available purchase lots first.
- **LIFO**: pairs the newest available purchase lots first.
- **MaxLose**: pairs lots with the highest stored unit price first.
- **MaxProfit**: pairs lots with the lowest stored unit price first.
- **Manual**: pairs a selected purchase with a sale, subject to availability and security/date validation.

Automatic methods fill the sale's remaining unpaired quantity. Batch pairing operates on unpaired and partially paired sales in the selected interval.

**Currency limitation:** MaxLose and MaxProfit order by the stored `price_for_share` value. The ordering does not normalize prices across currencies, so results for the same security traded in different currencies should be reviewed carefully.

## Time-test status

The repository calculates holding periods and a configurable time-test qualification, and the Pairing tab displays that information. The UI also displays a **Time Test Only** checkbox, but the current pairing handlers do not read it; selecting it does not restrict automatic matching. There is no primary/fallback method workflow in the current UI.

The qualification indicator is informational and is not, by itself, a tax determination. Verify applicable tax treatment independently.

## Pairing locks

Users can lock and unlock selected or displayed pairings and provide a lock reason. Locked pairings cannot be deleted until unlocked. The current UI does not provide a tax-year lock workflow or record who performed the lock and when.

## Current limits

- There is no separate **Closed Positions** view; the existing **Realized Income** tab remains separate from pairings.
- Open Positions is aggregated by security and does not display individual lots or unrealized gains based on current market prices.
- The UI does not provide tax-impact comparisons, tax reports, or export of pairing data.
- The Time Test Only checkbox is not connected to automatic pairing.
- MaxLose/MaxProfit comparisons do not normalize unit prices across currencies.

## Data model

The `pairings` table links a sale trade and a purchase trade and stores the paired quantity, method, holding-period days, time-test qualification, lock status/reason, and notes. Pairing data persists in the database and references the corresponding trades.
