# Pairing (Párrování) Feature

## Overview

The Pairing feature provides cost-basis matching functionality for optimizing tax reporting on securities transactions. When selling securities, users can apply different matching methods to pair sales with specific purchase lots, potentially reducing tax liability.

## Business Context

### When to Use Pairing

- **Applicable when**: Multiple purchase lots are available to match against a sale
- **Example**: Buy 50 units, buy another 50 units later, sell 100 units → optimization possible
- **Adoption rate**: ~45% of portfolios can benefit from pairing
- **Impact**: Potential substantial tax savings depending on method chosen

### Czech Tax Benefit: 3-Year Time Test

In the Czech Republic, capital gains from securities are **tax-exempt** if the holding period exceeds 3 years:

- **Time test requirement**: Purchase date to sale date > 3 years
- **Tax benefit**: 0% tax vs. 15% capital gains tax
- **Example**: Buy shares on 2021-01-10, sell on 2024-01-11 → **tax exempt** (3 years + 1 day)
- **Strategic importance**: Prioritizing time-test-qualified lots can eliminate tax entirely
- **Typical savings**: 15% of realized gain for qualifying transactions

**Key considerations**:
- Time is calculated from purchase date to sale date (not settlement dates)
- Each lot has its own time test status based on its purchase date
- Mixing time-test and non-time-test lots in a sale may partially reduce tax
- Strategic pairing can maximize use of time-test-qualified lots

### Current Challenges

1. **Awareness**: Low awareness among investors and tax advisors
2. **Technical complexity**: Cross-year pairings, lot tracking, typically done in Excel
3. **Limited support**: Few tax advisors offer this service
4. **Data quality**: Broker-provided methods may have currency conversion issues

## Key Features

### Time Interval Processing

The system supports applying pairing methods to multiple sales within a specified time interval:

- **Use case**: Apply a consistent method to all sales in a tax year at once
- **Benefit**: Saves time compared to pairing each sale individually
- **Example**: "Apply FIFO to all sales from 2024-01-01 to 2024-12-31"
- **Flexibility**: Can specify any date range, not just full years
- **Security filtering**: Optionally apply method only to specific securities

**Workflow**:
1. Select time interval (start and end date)
2. Optionally filter by security
3. Choose matching method (FIFO, LIFO, MaxLose, MaxProfit)
4. Preview affected sales and estimated impact
5. Confirm and apply to all unpaired sales in interval

### Pairing Lock Feature

Pairings can be locked to prevent accidental modification after tax filing:

- **Purpose**: Protect pairings used in submitted tax returns
- **Lock scope**: Individual pairings or all pairings for a tax year
- **Protection**: Locked pairings cannot be edited or deleted
- **Unlock option**: Can be unlocked if needed (e.g., amended return)
- **Audit trail**: Records when locked, by whom, and reason

**Lock Indicators**:
- 🔒 Lock icon in pairing table
- Gray/disabled background for locked rows
- Tooltip showing lock reason and date
- Warning when attempting to modify locked pairing

**Typical workflow**:
1. Create pairings throughout the year
2. Review and optimize before tax filing
3. Submit tax return with selected pairings
4. Lock all pairings for the tax year with reason: "Tax Return 2024"
5. Pairings are now protected from accidental changes

## Application Structure

### Three-View Architecture

The Pairing feature is built around three interconnected views that provide comprehensive position and pairing management:

#### 1. Pairs View (`views/pairs_view.py`)
**Primary purpose**: Manage and create pairings between purchases and sales

**Key functionality**:
- Time interval selector for filtering sales by date range
- Display all sales (paired and unpaired) with pairing status
- Show available purchase lots for selected sale
- Create/modify/delete pairings (manual and automatic methods)
- Lock/unlock pairings for tax compliance
- Visual indicators for locked pairings
- Tax impact comparison between different methods

**Typical use cases**:
- Creating new pairings for recent sales
- Optimizing pairings before tax filing
- Reviewing and adjusting existing pairings
- Locking pairings after tax return submission

#### 2. Open Positions View (`views/open_positions_view.py`)
**Primary purpose**: Monitor current holdings and available lots

**Key functionality**:
- Display all securities with open (unsold) positions
- Show purchase lots that haven't been fully sold
- Calculate current value and unrealized gains/losses
- Display average cost basis per security
- Filter by security, date range, or quantity
- Show which lots are partially used in pairings
- Project tax impact of potential sales

**Key columns**:
- Security (ISIN, ticker, name)
- Purchase date
- Quantity remaining (original - sold)
- Cost basis per unit
- Current value
- Unrealized gain/loss
- Holding period (years/days)
- Time test status (⏰✓ qualified, ⏰✗ not yet, ⏰ [X days remaining])
- Status (fully available, partially paired)

**Typical use cases**:
- Planning future sales based on tax optimization
- Understanding current portfolio composition
- Identifying lots for strategic selling
- Viewing which lots are available for pairing
- **Identifying time-test-qualified lots for tax-free sales**
- **Monitoring when lots will reach 3-year holding period**

#### 3. Closed Positions View (`views/closed_positions_view.py`)
**Primary purpose**: Review completed transactions and realized gains/losses

**Key functionality**:
- Display all fully sold positions
- Show pairings between purchases and sales
- Calculate realized gains/losses
- Display cost basis and sale proceeds
- Filter by year, security, or pairing method
- Export data for tax reporting
- Show locked status of pairings

**Key columns**:
- Security (ISIN, ticker, name)
- Sale date
- Quantity sold
- Purchase date(s) (from pairing)
- Cost basis (from paired purchases)
- Sale proceeds
- Realized gain/loss
- Holding period (days/years)
- Time test status (⏰✓ tax-exempt / ⏰✗ taxable)
- Calculated tax rate (0% or 15% based on time_test_qualified)
- Pairing method used (FIFO, LIFO, etc.)
- Locked status 🔒

**Typical use cases**:
- Preparing tax returns
- Reviewing historical trading performance
- Verifying pairing accuracy
- Generating evidence trail for tax authorities
- Year-end tax planning and reporting

### View Integration

**Navigation flow**:
1. **Open Positions** → View available lots → Select for potential sale planning
2. **Pairs** → Create pairings for new sales → Apply methods
3. **Closed Positions** → Review realized gains → Lock for tax filing

**Data relationships**:
- Open Positions shows unpaired purchase quantity
- Pairs view consumes available lots from Open Positions
- Closed Positions displays results of completed pairings
- All three views updated in real-time when pairings change

### Note on Realized Income View

The existing **Realized Income View** (`views/realized_income_view.py`) may be deprecated or merged into the Closed Positions View, as the new Closed Positions View provides:
- More detailed pairing information
- Method tracking
- Lock status
- Better tax reporting capabilities

**Decision pending**: Evaluate if Realized Income View should be:
- Removed entirely (functionality moved to Closed Positions)
- Kept for legacy/different use case
- Merged with Closed Positions as tabbed interface

## Matching Methods

### 1. FIFO (First-In, First-Out)
- **Logic**: Use the oldest purchased units for earliest sales
- **Tax impact**: Usually higher tax base in rising markets
- **Status**: Administrative standard, most common
- **Best for**: Simplicity, regulatory compliance

### 2. LIFO (Last-In, First-Out)
- **Logic**: Use the most recently purchased units for sales
- **Tax impact**: Lower tax base (higher cost of goods sold)
- **Benefit**: Reduces time-test concerns on older lots
- **Best for**: Rising markets, reducing short-term gains

### 3. MaxLose (Maximal Loss)
- **Logic**: Match with the most expensive remaining lot
- **Tax impact**: Minimizes realized profit (lowest tax base)
- **Best for**: Aggressive tax minimization, offsetting other gains

### 4. MaxProfit (Maximal Profit)
- **Logic**: Match with the cheapest remaining lot
- **Tax impact**: Maximizes realized profit (highest tax base)
- **Best for**: Utilizing losses, specific tax planning scenarios

### 5. TimeTest Filter ⭐ **Czech Republic Specific** - Combinable with All Methods

TimeTest is **not a standalone method** but a **constraint/filter** that can be combined with any of the four primary methods:

- **Logic**: Apply the selected method (FIFO, LIFO, MaxLose, MaxProfit) but **restrict to time-test-qualified lots only** (held 3+ years)
- **Tax impact**: Maximizes use of tax-exempt lots (0% tax)
- **Benefit**: Prioritizes tax-free sales while maintaining the logic of your chosen method
- **Fallback**: If time-test lots are insufficient to cover the full sale, a secondary method is applied to the remaining quantity

#### Combined Method Examples:

**MaxProfit + TimeTest (Fallback: MaxLose)**
- First pass: Apply MaxProfit logic to time-test-qualified lots only
- If 100 shares sold, but only 70 time-qualified shares available:
  - Pair 70 shares using MaxProfit from time-qualified lots → 0% tax
  - Pair remaining 30 shares using MaxLose from non-qualified lots → minimize taxable gain

**LIFO + TimeTest (Fallback: FIFO)**
- First pass: Apply LIFO logic to time-test-qualified lots only  
- Remaining quantity: Apply FIFO to non-qualified lots

**FIFO + TimeTest (Fallback: MaxLose)**
- First pass: Apply FIFO logic to time-test-qualified lots only
- Remaining quantity: Apply MaxLose to minimize taxable gain

**MaxLose + TimeTest (Fallback: MaxLose)**
- First pass: Apply MaxLose logic to time-test-qualified lots only
- Remaining quantity: Apply MaxLose to non-qualified lots (consistent logic)

#### UI Implementation:

**Pairing Selection Dialog**:
1. **Primary Method** (dropdown): FIFO / LIFO / MaxLose / MaxProfit
2. **Apply TimeTest Filter** (checkbox): ☑ Restrict to 3+ year lots first
3. **Fallback Method** (dropdown, enabled if TimeTest checked): FIFO / LIFO / MaxLose / MaxProfit

**Visual indicator in UI**: 
- Lots meeting time test show ⏰✓ icon
- Green background for time-qualified lots
- Method badges: "MaxProfit+TT → MaxLose" in pairing details (derived from sale-level tracking)

**Note**: Individual pairing records store only the basic method used (FIFO, LIFO, MaxLose, MaxProfit). The TimeTest filter application and fallback method selection are tracked at the sale transaction level for reporting purposes.

## Technical Implementation

### Database Schema

#### New Table: `pairings`

```sql
CREATE TABLE pairings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_trade_id INTEGER NOT NULL,
    purchase_trade_id INTEGER NOT NULL,
    quantity REAL NOT NULL,
    method TEXT NOT NULL,  -- 'FIFO', 'LIFO', 'MaxLose', 'MaxProfit', 'Manual'
    time_test_qualified BOOLEAN DEFAULT 0,  -- Whether this specific pairing meets 3-year time test
    holding_period_days INTEGER,  -- Calculated holding period in days
    locked BOOLEAN DEFAULT 0,  -- Lock pairs used in tax returns
    locked_reason TEXT,  -- Why locked (e.g., "Tax Return 2024")
    notes TEXT,
    FOREIGN KEY (sale_trade_id) REFERENCES trades(id),
    FOREIGN KEY (purchase_trade_id) REFERENCES trades(id)
);

CREATE INDEX idx_pairings_sale ON pairings(sale_trade_id);
CREATE INDEX idx_pairings_purchase ON pairings(purchase_trade_id);
CREATE INDEX idx_pairings_time_test ON pairings(time_test_qualified);
CREATE INDEX idx_pairings_method ON pairings(method);
```

**Schema Design Notes**:
- **Simplified structure**: Each pairing record contains only essential fields
- **Method field**: Stores the actual method used for this specific pairing (FIFO, LIFO, MaxLose, MaxProfit)
- **TimeTest combinations**: When TimeTest filter is used, the sale will have multiple pairings:
  - Some with `time_test_qualified=1` using primary method
  - Others with `time_test_qualified=0` using fallback method
- **Deriving combinations**: The effective method combination (e.g., "MaxProfit+TT → MaxLose") can be derived by:
  1. Grouping all pairings for a sale_trade_id
  2. Checking if any have `time_test_qualified=1` (TimeTest was used)
  3. Identifying the methods used for time-qualified vs non-qualified lots
- **Tax rate calculation**: Not stored; calculated on-the-fly as `0.15 if time_test_qualified=0 else 0.0`

#### Additional Fields Consideration

**Fields that could be added for enhanced functionality**:
- `remaining_quantity`: Track remaining unpaired quantity for partial matches
- `cost_basis`: Calculated cost basis for this pairing
- `realized_gain_loss`: Calculated gain/loss for this pairing
- `currency`: Base currency for calculations

**Fields already in main schema**:
- `time_test_qualified`: Boolean indicating if 3-year holding period met
- `holding_period_days`: Number of days between purchase and sale

**Note**: The `method` field in the schema stores only the primary method (FIFO, LIFO, MaxLose, MaxProfit). TimeTest filter application and fallback methods are tracked at the sale level or in a separate configuration table if needed for reporting.

### Repository Layer

#### New File: `db/repositories/pairings.py`

```python
from db.base import BaseRepository
from typing import List, Dict, Optional
from datetime import datetime

class PairingsRepository(BaseRepository):
    """Repository for managing trade pairings."""
    
    def create_pairing(self, sale_trade_id: int, purchase_trade_id: int, 
                       quantity: float, method: str, notes: Optional[str] = None) -> int:
        """Create a new pairing between a sale and purchase."""
        pass
    
    def get_pairings_for_sale(self, sale_trade_id: int) -> List[Dict]:
        """Get all pairings for a specific sale transaction."""
        pass
    
    def get_pairings_for_purchase(self, purchase_trade_id: int) -> List[Dict]:
        """Get all pairings using a specific purchase lot."""
        pass
    
    def delete_pairing(self, pairing_id: int) -> bool:
        """Delete a specific pairing (only if not locked)."""
        pass
    
    def lock_pairing(self, pairing_id: int, reason: str) -> bool:
        """Lock a pairing to prevent modification (e.g., after tax filing)."""
        pass
    
    def unlock_pairing(self, pairing_id: int) -> bool:
        """Unlock a pairing to allow modification."""
        pass
    
    def lock_pairings_by_year(self, year: int, reason: str) -> int:
        """Lock all pairings for a specific tax year."""
        pass
    
    def is_pairing_locked(self, pairing_id: int) -> bool:
        """Check if a pairing is locked."""
        pass
    
    def calculate_available_lots(self, security_id: int, before_date: str) -> List[Dict]:
        """Calculate available purchase lots for a security before a given date."""
        pass
    
    def apply_method(self, sale_trade_id: int, method: str, 
                     use_time_test_filter: bool = False, 
                     fallback_method: Optional[str] = None) -> List[Dict]:
        """Apply a specific matching method to a sale transaction.
        
        Args:
            sale_trade_id: ID of the sale transaction
            method: Primary method ('FIFO', 'LIFO', 'MaxLose', 'MaxProfit')
            use_time_test_filter: If True, restrict first pass to time-qualified lots only
            fallback_method: Method to use for non-time-qualified remainder (if use_time_test_filter=True)
            
        Note:
            Creates multiple pairing records with individual methods. The combination
            (e.g., "MaxProfit+TT → MaxLose") is reconstructed from the pairings' 
            time_test_qualified flags and their methods.
        """
        pass
    
    def apply_method_to_interval(self, start_date: str, end_date: str, 
                                  method: str, 
                                  security_id: Optional[int] = None,
                                  use_time_test_filter: bool = False,
                                  fallback_method: Optional[str] = None) -> List[Dict]:
        """Apply a matching method to all sales in a time interval."""
        pass
    
    def check_time_test(self, purchase_date: str, sale_date: str) -> bool:
        """Check if a purchase-sale pair meets 3-year time test."""
        pass
    
    def get_time_test_qualified_lots(self, security_id: int, sale_date: str) -> List[Dict]:
        """Get all purchase lots that meet time test for a given sale date."""
        pass
    
    def get_non_time_test_qualified_lots(self, security_id: int, sale_date: str) -> List[Dict]:
        """Get all purchase lots that do NOT meet time test for a given sale date."""
        pass
    
    def calculate_holding_period(self, purchase_date: str, sale_date: str) -> int:
        """Calculate holding period in days between purchase and sale."""
        pass
    
    def apply_method_with_timetest(self, sale_trade_id: int, primary_method: str, 
                                    fallback_method: str) -> Dict:
        """Apply method with TimeTest filter: primary method on time-qualified lots,
        fallback method on remaining lots.
        
        Returns dict with details of both passes.
        """
        pass
    
    def get_tax_savings_summary(self, sale_trade_id: int, method: str,
                                 use_time_test: bool = False,
                                 fallback_method: Optional[str] = None) -> Dict:
        """Calculate potential tax savings from different method combinations."""
        pass
    
    def get_unpaired_sales(self, start_date: str, end_date: str) -> List[Dict]:
        """Get all sales without pairings in a time interval."""
        pass
    
    def get_pairing_summary(self, year: int) -> List[Dict]:
        """Get summary of all pairings for a tax year.
        
        Returns summary including derived method combinations based on:
        - Grouping pairings by sale_trade_id
        - Identifying which pairings have time_test_qualified=True
        - Determining effective method combination (e.g., "MaxProfit+TT → MaxLose")
        """
        pass
```

### View Layer

#### View 1: Pairs View - `views/pairs_view.py`

```python
from views.base_view import BaseView
from db.repositories.pairings import PairingsRepository
from db.repositories.trades import TradesRepository

class PairsView(BaseView):
    """View for managing trade pairings between purchases and sales."""
    
    def __init__(self, parent):
        super().__init__(parent)
        self.pairings_repo = PairingsRepository()
        self.trades_repo = TradesRepository()
        self.setup_ui()
    
    def setup_ui(self):
        """Setup the pairs view UI."""
        # Top section: Time interval selector (start date, end date)
        # Filter section: Security filter, pairing status filter
        # Main section (left): Sales list with pairing status
        # Main section (right top): Available purchase lots for selected sale
        # Main section (right bottom): Current pairings for selected sale
        # Bottom section: Action buttons and method selector
        pass
    
    def load_sales_in_interval(self, start_date: str, end_date: str, 
                                security_id: Optional[int] = None):
        """Load all sale transactions in time interval."""
        pass
    
    def load_available_lots(self, security_id: int, sale_date: str):
        """Load available purchase lots for pairing with selected sale."""
        # Display time test status (⏰✓ for qualified, ⏰✗ for not qualified)
        # Show holding period in years/days
        # Highlight time-test-qualified lots with green background
        pass
    
    def load_current_pairings(self, sale_trade_id: int):
        """Load existing pairings for selected sale."""
        pass
    
    def apply_automatic_method(self, method: str, use_timetest: bool = False, 
                                fallback_method: Optional[str] = None):
        """Apply FIFO, LIFO, MaxLose, or MaxProfit to selected sale.
        
        Args:
            method: Primary method to apply
            use_timetest: If True, restrict to time-qualified lots first
            fallback_method: Method for remaining quantity if use_timetest=True
        """
        pass
    
    def apply_method_to_interval(self, method: str, start_date: str, end_date: str,
                                  use_timetest: bool = False,
                                  fallback_method: Optional[str] = None):
        """Apply a matching method to all unpaired sales in interval."""
        pass
    
    def show_method_selection_dialog(self, sale_trade_id: int):
        """Show dialog for selecting pairing method with TimeTest filter option.
        
        Dialog includes:
        - Primary method dropdown (FIFO, LIFO, MaxLose, MaxProfit)
        - TimeTest filter checkbox
        - Fallback method dropdown (enabled if TimeTest checked)
        - Preview of tax impact
        """
        pass
    
    def create_manual_pairing(self, sale_id: int, purchase_id: int, quantity: float):
        """Create a manual pairing between specific lots."""
        pass
    
    def delete_pairing(self, pairing_id: int):
        """Delete a pairing (only if unlocked)."""
        pass
    
    def lock_pairing(self, pairing_id: int, reason: str):
        """Lock a pairing to prevent modification."""
        pass
    
    def unlock_pairing(self, pairing_id: int):
        """Unlock a pairing to allow modification."""
        pass
    
    def lock_year_pairings(self, year: int, reason: str):
        """Lock all pairings for a tax year."""
        pass
    
    def show_pairing_impact_comparison(self, sale_trade_id: int):
        """Display tax impact comparison of different methods for a sale."""
        # Include TimeTest method showing potential 0% tax benefit
        # Highlight time-test savings vs. other methods
        pass
    
    def refresh_view(self):
        """Refresh all data in the view after changes."""
        pass
```

#### View 2: Open Positions View - `views/open_positions_view.py`

```python
from views.base_view import BaseView
from db.repositories.trades import TradesRepository
from db.repositories.pairings import PairingsRepository
from typing import List, Dict, Optional

class OpenPositionsView(BaseView):
    """View for displaying current open (unsold) positions and available lots."""
    
    def __init__(self, parent):
        super().__init__(parent)
        self.trades_repo = TradesRepository()
        self.pairings_repo = PairingsRepository()
        self.setup_ui()
    
    def setup_ui(self):
        """Setup the open positions view UI."""
        # Top section: Filters (security, date range, minimum quantity)
        # Main section: Table of open positions
        # Bottom section: Summary statistics (total value, total cost, unrealized P&L)
        pass
    
    def load_open_positions(self, security_id: Optional[int] = None) -> List[Dict]:
        """Load all open positions (purchases not fully sold)."""
        # Calculate: original quantity - quantity used in pairings
        pass
    
    def calculate_remaining_quantity(self, purchase_trade_id: int) -> float:
        """Calculate remaining quantity available for pairing."""
        pass
    
    def calculate_unrealized_pnl(self, purchase_trade_id: int, current_price: float) -> Dict:
        """Calculate unrealized gain/loss for an open position."""
        pass
    
    def get_position_summary(self) -> Dict:
        """Get summary statistics for all open positions."""
        pass
    
    def filter_positions(self, **filters):
        """Filter positions by various criteria."""
        pass
    
    def export_open_positions(self, format: str = 'csv'):
        """Export open positions to file."""
        pass
    
    def show_position_detail(self, purchase_trade_id: int):
        """Show detailed information about a specific position."""
        pass
```

#### View 3: Closed Positions View - `views/closed_positions_view.py`

```python
from views.base_view import BaseView
from db.repositories.pairings import PairingsRepository
from db.repositories.trades import TradesRepository
from typing import List, Dict, Optional

class ClosedPositionsView(BaseView):
    """View for displaying closed positions with realized gains/losses."""
    
    def __init__(self, parent):
        super().__init__(parent)
        self.pairings_repo = PairingsRepository()
        self.trades_repo = TradesRepository()
        self.setup_ui()
    
    def setup_ui(self):
        """Setup the closed positions view UI."""
        # Top section: Filters (year, security, method, locked status)
        # Main section: Table of closed positions with pairing details
        # Bottom section: Summary (total realized P&L, tax liability)
        pass
    
    def load_closed_positions(self, year: Optional[int] = None, 
                              security_id: Optional[int] = None) -> List[Dict]:
        """Load all closed positions (fully paired sales)."""
        pass
    
    def calculate_realized_pnl(self, sale_trade_id: int) -> Dict:
        """Calculate realized gain/loss for a sale based on pairings."""
        pass
    
    def get_pairing_details(self, sale_trade_id: int) -> List[Dict]:
        """Get detailed pairing information for a sale."""
        pass
    
    def get_tax_summary(self, year: int) -> Dict:
        """Get tax summary for a year (total gains, losses, tax owed)."""
        pass
    
    def filter_by_method(self, method: str):
        """Filter closed positions by pairing method."""
        pass
    
    def filter_by_locked_status(self, locked: bool):
        """Filter closed positions by lock status."""
        pass
    
    def export_for_tax_filing(self, year: int, format: str = 'csv'):
        """Export closed positions formatted for tax filing."""
        pass
    
    def show_position_detail(self, sale_trade_id: int):
        """Show detailed breakdown of a closed position."""
        pass
```

### UI Components

#### Menu Addition

Add to `ui/menu_manager.py`:

```python
def create_pairing_menu(self):
    """Create Pairing menu."""
    pairing_menu = tk.Menu(self.menubar, tearoff=0)
    self.menubar.add_cascade(label="Pairing", menu=pairing_menu)
    
    # View navigation
    pairing_menu.add_command(label="Pairs", 
                             command=self.show_pairs_view)
    pairing_menu.add_command(label="Open Positions", 
                             command=self.show_open_positions_view)
    pairing_menu.add_command(label="Closed Positions", 
                             command=self.show_closed_positions_view)
    pairing_menu.add_separator()
    
    # Single transaction methods
    pairing_menu.add_command(label="Apply Method (with dialog)...", 
                             command=self.show_method_selection_dialog)
    pairing_menu.add_separator()
    pairing_menu.add_command(label="Apply FIFO", 
                             command=lambda: self.apply_method('FIFO'))
    pairing_menu.add_command(label="Apply LIFO", 
                             command=lambda: self.apply_method('LIFO'))
    pairing_menu.add_command(label="Apply MaxLose", 
                             command=lambda: self.apply_method('MaxLose'))
    pairing_menu.add_command(label="Apply MaxProfit", 
                             command=lambda: self.apply_method('MaxProfit'))
    pairing_menu.add_separator()
    
    # Quick TimeTest combinations (Czech-optimized)
    timetest_menu = tk.Menu(pairing_menu, tearoff=0)
    pairing_menu.add_cascade(label="⭐ Quick TimeTest Combos (CZ)", menu=timetest_menu)
    timetest_menu.add_command(label="MaxProfit+TT → MaxLose", 
                              command=lambda: self.apply_method('MaxProfit', True, 'MaxLose'))
    timetest_menu.add_command(label="LIFO+TT → FIFO", 
                              command=lambda: self.apply_method('LIFO', True, 'FIFO'))
    timetest_menu.add_command(label="MaxLose+TT → MaxLose", 
                              command=lambda: self.apply_method('MaxLose', True, 'MaxLose'))
    timetest_menu.add_command(label="FIFO+TT → MaxLose", 
                              command=lambda: self.apply_method('FIFO', True, 'MaxLose'))
    pairing_menu.add_separator()
    
    # Time interval methods
    interval_menu = tk.Menu(pairing_menu, tearoff=0)
    pairing_menu.add_cascade(label="Apply to Time Interval", menu=interval_menu)
    interval_menu.add_command(label="Interval with Dialog...", 
                              command=self.show_interval_method_dialog)
    interval_menu.add_separator()
    interval_menu.add_command(label="FIFO to Interval", 
                              command=lambda: self.apply_method_to_interval('FIFO'))
    interval_menu.add_command(label="LIFO to Interval", 
                              command=lambda: self.apply_method_to_interval('LIFO'))
    interval_menu.add_command(label="MaxLose to Interval", 
                              command=lambda: self.apply_method_to_interval('MaxLose'))
    interval_menu.add_command(label="MaxProfit to Interval", 
                              command=lambda: self.apply_method_to_interval('MaxProfit'))
    interval_menu.add_separator()
    interval_menu.add_command(label="⭐ MaxProfit+TT → MaxLose (Recommended)", 
                              command=lambda: self.apply_method_to_interval('MaxProfit', True, 'MaxLose'))
    pairing_menu.add_separator()
    
    # Locking functions
    lock_menu = tk.Menu(pairing_menu, tearoff=0)
    pairing_menu.add_cascade(label="Lock Pairings", menu=lock_menu)
    lock_menu.add_command(label="Lock Selected Pairing", 
                          command=self.lock_selected_pairing)
    lock_menu.add_command(label="Lock Year Pairings", 
                          command=self.lock_year_dialog)
    lock_menu.add_command(label="Unlock Selected Pairing", 
                          command=self.unlock_selected_pairing)
    pairing_menu.add_separator()
    
    pairing_menu.add_command(label="Pairing Report", 
                             command=self.show_pairing_report)
```

## Data Requirements

### Input Data Needed

1. **Complete trade history**: All buy and sell transactions
2. **Transaction dates**: Precise dates for time-ordered matching
3. **Quantities**: Exact quantities bought and sold
4. **Prices**: Purchase and sale prices (including fees)
5. **Security identification**: ISIN, ticker, or unique identifier
6. **Currency information**: For consistent calculations

### Evidence Trail Requirements

For Czech tax compliance, maintain:
- Which specific lots were paired to which sales
- Transaction dates and times
- Prices and fees for each matched pair
- Method used (FIFO, LIFO, etc.)
- Calculations showing cost basis and gain/loss

## Implementation Phases

### Phase 1: Database and Repository (Week 1)
- [ ] Create `pairings` table schema
- [ ] Implement `PairingsRepository` class
- [ ] Write unit tests for repository methods
- [ ] Test lot availability calculations
- [ ] **Implement logic to derive method combinations from grouped pairings** ⭐
- [ ] **Add helper methods to identify TimeTest usage from pairing patterns** ⭐

### Phase 2: Core Matching Logic (Week 2)
- [ ] Implement FIFO method
- [ ] Implement LIFO method
- [ ] Implement MaxLose method
- [ ] Implement MaxProfit method
- [ ] **Implement TimeTest filter logic (lot filtering by 3+ year holding)** ⭐
- [ ] **Implement two-pass pairing: TimeTest-filtered + Fallback method** ⭐
- [ ] Add holding period calculation (purchase to sale date)
- [ ] Add time test qualification check (> 3 years)
- [ ] Add validation for partial matches
- [ ] Handle cross-year pairings
- [ ] Implement time interval pairing logic
- [ ] Add pairing locking/unlocking functionality
- [ ] Validate locked pairings cannot be modified

### Phase 3: UI Development (Week 3-4)
- [ ] Create `PairsView` class with time interval selector
- [ ] Implement Pairs view layout (sales list, available lots, current pairings)
- [ ] **Add time test visual indicators (⏰✓/⏰✗ icons, green highlighting)** ⭐
- [ ] **Display holding period in years/days for each lot** ⭐
- [ ] **Create Method Selection Dialog with TimeTest filter checkbox and fallback dropdown** ⭐
- [ ] **Add quick TimeTest combo shortcuts in menu** ⭐
- [ ] Display method badges in pairing details (e.g., "MaxProfit+TT → MaxLose")
- [ ] Add lock/unlock pairing functionality with visual indicators
- [ ] Create `OpenPositionsView` class
- [ ] Implement Open Positions view (positions table, filters, summary)
- [ ] **Add time test status column and countdown to 3 years** ⭐
- [ ] Add remaining quantity calculations
- [ ] Create `ClosedPositionsView` class
- [ ] Implement Closed Positions view (closed trades table, pairing details)
- [ ] **Show time test status and applied tax rate (0% vs 15%)** ⭐
- [ ] Add tax summary calculations and export
- [ ] Integrate all three views into menu system
- [ ] Add visual styling for locked pairings (🔒 icon, gray background)
- [ ] Test view navigation and data synchronization

### Phase 4: Integration and Reporting (Week 5)
- [ ] Add Pairing menu to application with 3 view options
- [ ] Integrate with existing Trades view
- [ ] Ensure data synchronization between Pairs, Open Positions, and Closed Positions views
- [ ] Create pairing summary report
- [ ] Add tax impact comparison tool in Pairs view
- [ ] Implement export functionality for all three views
- [ ] Decide on Realized Income view: deprecate, merge, or keep
- [ ] Add navigation helpers between views

### Phase 5: Testing and Documentation (Week 6)
- [ ] Integration testing with real data
- [ ] User acceptance testing
- [ ] Performance testing with large datasets
- [ ] Complete user documentation
- [ ] Add help tooltips and guides

## Example Scenario

### Setup
- Security: AAPL
- Purchase 1: 2024-01-15, 50 shares @ $150 = $7,500
- Purchase 2: 2024-06-20, 50 shares @ $180 = $9,000
- Sale: 2024-11-10, 100 shares @ $200 = $20,000

### Method Comparison

| Method | Matched Lots | Cost Basis | Sale Price | Gain/Loss | Tax (15%) |
|--------|-------------|------------|------------|-----------|-----------|
| FIFO | P1(50) + P2(50) | $16,500 | $20,000 | +$3,500 | $525 |
| LIFO | P2(50) + P1(50) | $16,500 | $20,000 | +$3,500 | $525 |
| MaxLose | P2(100 partial) | $18,000 | $20,000 | +$2,000 | $300 |
| MaxProfit | P1(100 partial) | $15,000 | $20,000 | +$5,000 | $750 |

**Note**: In this example, FIFO and LIFO yield the same result because all shares are sold. The difference becomes significant in partial sales or when managing ongoing positions.

### More Complex Scenario

- Purchase 1: 2023-01-10, 30 shares @ $120 = $3,600
- Purchase 2: 2023-08-15, 40 shares @ $160 = $6,400
- Purchase 3: 2024-03-20, 50 shares @ $180 = $9,000
- Sale 1: 2024-06-15, 60 shares @ $200 = $12,000

| Method | Matched Lots | Cost Basis | Gain/Loss | Tax Savings vs FIFO |
|--------|-------------|------------|-----------|---------------------|
| FIFO | P1(30) + P2(30) | $8,400 | +$3,600 | — |
| LIFO | P3(60) | $10,800 | +$1,200 | $360 |
| MaxLose | P3(50) + P2(10) | $10,600 | +$1,400 | $330 |
| MaxProfit | P1(30) + P2(30) | $8,400 | +$3,600 | $0 |

**Potential savings**: Up to $360 in taxes by using LIFO instead of FIFO.

### Time Test Filter Scenario (Czech Republic Specific) ⭐

**Setup**:
- Security: VOO (Vanguard S&P 500 ETF)
- Purchase 1: 2020-03-15, 40 shares @ $220 = $8,800 (4.3 years ago) ✓ **Time test qualified**
- Purchase 2: 2021-02-10, 30 shares @ $350 = $10,500 (3.4 years ago) ✓ **Time test qualified**
- Purchase 3: 2023-06-20, 50 shares @ $400 = $20,000 (1.0 years ago) ✗ Time test not met
- Sale: 2024-06-15, 80 shares @ $450 = $36,000

**Available lots summary**:
- Time-qualified: 70 shares (P1: 40 @ $220, P2: 30 @ $350)
- Non-qualified: 50 shares (P3: 50 @ $400)

**Method Comparison with TimeTest Filter**:

| Method Configuration | Pass 1: Time-Qualified (70) | Pass 2: Remaining (10) | Total Cost Basis | Gain | Tax Owed |
|---------------------|----------------------------|------------------------|------------------|------|----------|
| **MaxProfit+TT → MaxLose** ⭐ | P1(40) + P2(30) cheapest<br>Cost: $8,800 + $10,500 | P3(10) most expensive<br>Cost: $4,000 | $23,300 | $12,700 | **$251**<br>(0% on $11,025<br>15% on $1,675) |
| **LIFO+TT → FIFO** | P2(30) + P1(40) most recent<br>Cost: $10,500 + $8,800 | P3(10) oldest remaining<br>Cost: $4,000 | $23,300 | $12,700 | **$251**<br>(same as above) |
| **MaxLose+TT → MaxLose** | P2(30) + P1(40) most expensive<br>Cost: $10,500 + $8,800 | P3(10) most expensive<br>Cost: $4,000 | $23,300 | $12,700 | **$251**<br>(same as above) |
| FIFO (no TimeTest) | P1(40) + P2(30) + P3(10)<br>All mixed | — | $23,300 | $12,700 | $1,905<br>(15% on all) |
| LIFO (no TimeTest) | P3(50) + P2(30)<br>All mixed | — | $30,500 | $5,500 | $469 |
| MaxProfit (no TimeTest) | P1(40) + P2(40)<br>All time-qualified! | — | $8,800 + $14,000 | $13,200 | **$0**<br>(lucky case) |

**Key Insights**:

1. **All TimeTest combinations save $1,654** vs. plain FIFO because they maximize tax-exempt usage
2. **MaxProfit+TT → MaxLose**: Prioritizes cheapest time-qualified lots (maximize gain but 0% tax), then minimizes gain on taxable remainder
3. **LIFO+TT → FIFO**: Uses most recent time-qualified lots first, then oldest from remainder
4. In this case, all 70 time-qualified shares are used regardless of method → same $251 tax
5. Plain **MaxProfit without TimeTest** happens to use only qualified lots → $0 tax (but this is coincidental, not guaranteed)

**Calculation for MaxProfit+TT → MaxLose**:
- **Pass 1** (MaxProfit on time-qualified): P1(40) + P2(30) = 70 shares
  - Cost: $8,800 + $10,500 = $19,300
  - Proceeds: 70 × $450 = $31,500
  - Gain: $12,200
  - Tax: $0 (time test exempt) ✓
- **Pass 2** (MaxLose on non-qualified): P3(10) = 10 shares  
  - Cost: 10 × $400 = $4,000
  - Proceeds: 10 × $450 = $4,500
  - Gain: $500
  - Tax: $500 × 15% = $75
- **Total tax: $75** (vs. $1,905 without TimeTest)

**Recommendation**: For Czech investors selling 80 shares with 70 time-qualified available, **any TimeTest combination saves ~96% on taxes**. Choose your primary/fallback based on preference.
| MaxProfit | P1(40) + P2(40) | $8,800 + $14,000 = $22,800 | $13,200 | P1✓ + P2✓ (all) | **0% (all exempt)** | **$0** |

**Key insights**:
1. **TimeTest method** prioritizes time-test-qualified lots → saves $1,654 vs. FIFO
2. **MaxProfit** happens to use only qualified lots → **$0 tax** (best outcome)
3. LIFO uses newer expensive lots (not time-test-qualified) → higher tax
4. Strategic selection of 70 time-qualified shares eliminates most tax

**Calculation details for TimeTest method**:
- P1: 40 shares, 4.3 years → **Tax exempt** (gain: $9,200, tax: $0)
- P2: 30 shares, 3.4 years → **Tax exempt** (gain: $3,000, tax: $0)  
- P3: 10 shares, 1.0 years → **Taxable** (gain: $500, tax: $75)
- **Total tax: $75** vs. $1,905 with FIFO → **$1,830 savings (96% reduction)**

**Recommendation**: For Czech investors, **TimeTest method should be the default** when time-qualified lots are available.

## Risk Considerations

### Technical Risks
1. **Data integrity**: Ensuring lots aren't double-used across multiple sales
2. **Cross-year tracking**: Maintaining accurate lot balances year-over-year
3. **Partial matches**: Correctly handling fractional lot usage
4. **Performance**: Scaling to large portfolios with thousands of transactions

### Compliance Risks
1. **Documentation**: Must maintain audit trail for tax authorities
2. **Consistency**: Once a method is chosen for a sale, it should be documented
3. **Broker discrepancies**: User's pairing may differ from broker's reporting
4. **Currency conversion**: Ensure consistency in multi-currency portfolios

## Success Criteria

### Pairs View
1. ✅ Users can view all sales in a time interval with pairing status
2. ✅ Users can view all available purchase lots for any sale
3. ✅ Users can apply automatic matching methods (FIFO, LIFO, MaxLose, MaxProfit)
4. ✅ **Users can combine any method with TimeTest filter to prioritize 3+ year lots** ⭐
5. ✅ **Users can select fallback method for non-time-qualified remainder** ⭐
6. ✅ **System displays time test status (⏰✓) and holding period for each lot** ⭐
7. ✅ **Method selection dialog with TimeTest checkbox and fallback dropdown** ⭐
8. ✅ Users can apply matching methods to all sales in a time interval
9. ✅ Users can create manual pairings for specific lots
10. ✅ System validates that lots aren't over-allocated
11. ✅ Users can see tax impact comparison before applying a method (including 0% tax benefit)
12. ✅ **Quick TimeTest combo shortcuts (e.g., MaxProfit+TT → MaxLose)** ⭐
13. ✅ Users can lock pairings used in tax returns to prevent accidental modification
14. ✅ Locked pairings display clear visual indicator (🔒) and cannot be edited/deleted
15. ✅ Users can lock all pairings for a tax year after filing

### Open Positions View
13. ✅ Users can view all current holdings with remaining quantities
14. ✅ System displays which lots are partially used in pairings
15. ✅ **System displays time test status for each open position** ⭐
16. ✅ **Users can see countdown to 3-year holding period for planning** ⭐
17. ✅ Users can see unrealized gains/losses for open positions
18. ✅ Users can filter positions by security, date, or quantity
19. ✅ **Users can filter to show only time-test-qualified lots** ⭐
20. ✅ Summary statistics show total portfolio value and unrealized P&L

### Closed Positions View
21. ✅ Users can view all closed positions with realized gains/losses
22. ✅ System shows detailed pairing information for each closed position
23. ✅ **System displays time test status and applied tax rate (0% or 15%)** ⭐
24. ✅ Users can filter by year, security, method, or lock status
25. ✅ **Users can filter by time test status (exempt vs. taxable)** ⭐
26. ✅ Tax summary calculates total gains, losses, and estimated tax liability
27. ✅ **Tax summary separately shows tax-exempt vs. taxable gains** ⭐
28. ✅ Export functionality provides data formatted for tax filing

### General
29. ✅ System generates complete evidence trail for tax reporting
30. ✅ Pairings persist across sessions and years
31. ✅ All three views synchronize data in real-time
32. ✅ Users can navigate seamlessly between the three views

## Future Enhancements

- **Wash sale detection**: Identify and flag potential wash sales
- **Optimization suggestions**: AI-powered recommendations for best method
- **Time test alerts**: Notify users when lots are approaching 3-year holding period ⭐
- **Sale timing optimizer**: Suggest optimal sale dates to maximize time-test benefits ⭐
- **Batch processing**: Apply methods to multiple sales at once
- **What-if analysis**: Simulate different scenarios before committing
- **Multi-year strategy**: Plan pairings across multiple tax years
- **Integration with tax forms**: Direct export to Czech tax return formats
- **Automatic TimeTest preference**: Default to TimeTest method for Czech users ⭐

## Questions for Clarification

1. ~~Should the system allow changing pairings after they're created?~~ **Resolved**: Yes, but with locking feature for tax-filed pairings
2. How should we handle stock splits or dividends that affect lot quantities?
3. Should we support specific lot identification beyond the four main methods?
4. What reports are needed for tax advisor or tax authority submission?
5. ~~Should we integrate with the Realized Income view to show paired transactions?~~ **Resolved**: New Closed Positions view replaces/extends Realized Income functionality
6. **NEW**: When applying methods to time interval, should we skip already-paired sales or override them?
7. **NEW**: Should locked pairings be completely immutable or allow unlocking with confirmation?
8. **NEW**: Should we send notifications/warnings before locking a full year?
9. **NEW**: Should time interval default to current tax year or require manual selection?
10. **NEW**: Should we track who locked a pairing (user identification)?
11. **NEW**: Should Realized Income view be deprecated, merged with Closed Positions, or kept separate?
12. **NEW**: Should TimeTest filter be enabled by default for Czech users in the method selection dialog? ⭐
13. **NEW**: What should be the recommended default fallback method (MaxLose for minimal taxable gain)? ⭐
14. **NEW**: Should the system send alerts when lots are approaching 3-year qualification? ⭐
15. **NEW**: For time test calculation, should we use trade date or settlement date? ⭐
16. **NEW**: Should we allow chaining more than 2 methods (e.g., Method1+TT → Method2 → Method3)? ⭐

---

**Document Status**: Draft for implementation planning  
**Created**: 2026-01-02  
**Last Updated**: 2026-01-02  
**Related Documents**: 
- [Refactoring Plan](REFACTORING_PLAN.md)
- [Phase 3 Progress](PHASE3_PROGRESS.md)
- [Database Design](../db/base.py)
