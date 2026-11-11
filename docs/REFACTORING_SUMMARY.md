# Code Structure

The Tkinter application is coordinated by `app.py`. It creates the main window, manages the database lifecycle, and connects the filters and views.

## Main components

- `views/` contains the Trades, Dividends, Interests, Realized Income, Pairing, and Open Positions views. Shared view behavior is in `base_view.py`.
- `db/` contains `DatabaseManager` and repositories for trades, securities, dividends, interests, and pairings.
- `dialogs/` contains the exchange-rate-mode and annual-rate-import dialogs.
- `ui/` contains menu management, date filtering, and shared UI helpers.
- `config/` contains exchange-rate, withholding-tax, country-resolution, and time-test configuration.

The main window currently presents six tabs: Trades, Dividends, Interests, Realized Income, Pairing, and Open Positions.
