# TradingTools App Refactoring Plan

## Current State Analysis

**File:** `app.py`
- **Total Lines:** ~1,548 lines
- **Total Methods:** 35 methods
- **Main Issues:**
  - Single monolithic class handling all UI, business logic, and event handling
  - Mixed concerns: menu management, dialog creation, view creation, data updates
  - Difficult to maintain, test, and extend

## Refactoring Goals

1. **Separation of Concerns** - Split UI, business logic, and data handling
2. **Maintainability** - Smaller, focused modules easier to understand and modify
3. **Testability** - Isolated components that can be tested independently
4. **Reusability** - Common components can be shared across views
5. **Scalability** - Easy to add new views or features

---

## Phase 1: Create View Classes (High Priority)

### 1.1 Create Views Directory Structure
```
views/
├── __init__.py
├── base_view.py           # Abstract base class for all views
├── trades_view.py         # 88 lines → separate class
├── dividends_view.py      # 120 lines → separate class
├── interests_view.py      # 68 lines → separate class
└── realized_income_view.py # 91 lines → separate class
```

### 1.2 BaseView Abstract Class
**File:** `views/base_view.py`

**Responsibilities:**
- Define common interface for all views
- Handle common tree operations (copy to clipboard)
- Provide utility methods for formatting

**Methods:**
- `create_view(parent_frame)` - Abstract method
- `update_view(start_ts, end_ts)` - Abstract method
- `clear_view()` - Clear all data
- `copy_to_clipboard(event)` - Reusable clipboard handler

### 1.3 TradesView Class
**File:** `views/trades_view.py`

**Extracted from app.py:**
- `create_trades_view()` → `TradesView.create_view()`
- `update_trades_view()` → `TradesView.update_view()`

**Dependencies:**
- `DatabaseManager` (via constructor injection)
- `trades_repo` from database

**Estimated Reduction:** ~100 lines from app.py

### 1.4 DividendsView Class
**File:** `views/dividends_view.py`

**Extracted from app.py:**
- `create_dividends_view()` → `DividendsView.create_view()`
- `update_dividends_view()` → `DividendsView.update_view()`

**Additional Responsibilities:**
- Country summary table management
- Tax calculation logic (JSON vs CSV)

**Dependencies:**
- `DatabaseManager`
- `TaxRatesLoader`
- `CountryResolver`

**Estimated Reduction:** ~240 lines from app.py

### 1.5 InterestsView Class
**File:** `views/interests_view.py`

**Extracted from app.py:**
- `create_interests_view()` → `InterestsView.create_view()`
- `update_interests_view()` → `InterestsView.update_view()`

**Dependencies:**
- `DatabaseManager`
- `interests_repo` from database

**Estimated Reduction:** ~90 lines from app.py

### 1.6 RealizedIncomeView Class
**File:** `views/realized_income_view.py`

**Extracted from app.py:**
- `create_realized_income_view()` → `RealizedIncomeView.create_view()`
- `update_realized_income_view()` → `RealizedIncomeView.update_view()`

**Dependencies:**
- `DatabaseManager`
- `trades_repo` from database

**Estimated Reduction:** ~120 lines from app.py

**Phase 1 Total Reduction:** ~550 lines (35% reduction)

---

## Phase 2: Extract Dialog Classes (Medium Priority)

### 2.1 Create Dialogs Directory Structure
```
dialogs/
├── __init__.py
├── base_dialog.py
├── exchange_rate_dialog.py
└── import_rates_dialog.py
```

### 2.2 ExchangeRateDialog Class
**File:** `dialogs/exchange_rate_dialog.py`

**Extracted from app.py:**
- Exchange rate mode selection dialog from `create_database()`

**Methods:**
- `show()` → Returns selected mode (annual/daily or None)

**Estimated Reduction:** ~70 lines from app.py

### 2.3 ImportRatesDialog Class
**File:** `dialogs/import_rates_dialog.py`

**Extracted from app.py:**
- Annual rates import dialog from `import_annual_rates()`

**Methods:**
- `show()` → Returns (year, file_path) or (None, None)

**Estimated Reduction:** ~90 lines from app.py

**Phase 2 Total Reduction:** ~160 lines (10% reduction)

---

## Phase 3: Extract Menu Management (Medium Priority)

### 3.1 Create MenuManager Class
**File:** `ui/menu_manager.py`

**Extracted from app.py:**
- `create_menu()` → `MenuManager.create_menu()`
- `update_menu_states()` → `MenuManager.update_states()`
- `update_exchange_rate_display()` → `MenuManager.update_exchange_rate_display()`

**Dependencies:**
- Reference to main app for callbacks
- `DatabaseManager` for state checking

**Estimated Reduction:** ~90 lines from app.py

---

## Phase 4: Extract Utilities (Low Priority)

### 4.1 Create UI Utilities Module
**File:** `ui/ui_utils.py`

**Extracted from app.py:**
- `copy_treeview_to_clipboard()` → Standalone function
- Date formatting utilities
- Common tree configuration helpers

**Estimated Reduction:** ~40 lines from app.py

### 4.2 Create Filter Management Module
**File:** `ui/filter_manager.py`

**Extracted from app.py:**
- `update_filters()` 
- `init_date_filters_from_db()`
- `on_year_selected()`
- `update_year_list()`

**Estimated Reduction:** ~50 lines from app.py

**Phase 4 Total Reduction:** ~90 lines (6% reduction)

---

## Phase 5: Refactor Main App Class (Final Phase)

### 5.1 Simplified TradingToolsApp
**File:** `app.py` (refactored)

**New Structure:**
```python
class TradingToolsApp:
    def __init__(self):
        # Initialize core components
        self.root = tk.Tk()
        self.db = DatabaseManager()
        
        # Initialize managers
        self.menu_manager = MenuManager(self, self.db)
        self.filter_manager = FilterManager(self)
        
        # Initialize views
        self.trades_view = TradesView(self.db)
        self.dividends_view = DividendsView(self.db, ...)
        self.interests_view = InterestsView(self.db)
        self.realized_view = RealizedIncomeView(self.db)
        
        # Setup UI
        self.create_main_layout()
        
    def create_main_layout(self):
        # Create filter panel
        # Create notebook with views
        
    def update_all_views(self):
        # Delegate to each view
```

**Remaining Responsibilities:**
- Application initialization
- Main window management
- Coordinating views and managers
- Database connection lifecycle
- CSV import (could be extracted later)

**Estimated Final Size:** ~400-500 lines (67% reduction from original)

---

## Implementation Strategy

### Order of Implementation (Risk-Minimization Approach)

1. **Step 1: Create Base Infrastructure**
   - Create `views/` and `dialogs/` directories
   - Create `base_view.py` with abstract interface
   - No changes to app.py yet

2. **Step 2: Extract One View as Proof of Concept**
   - Start with `TradesView` (relatively simple)
   - Test thoroughly to validate approach
   - Refine patterns based on learnings

3. **Step 3: Extract Remaining Views**
   - `InterestsView` (simplest)
   - `RealizedIncomeView` 
   - `DividendsView` (most complex, do last)

4. **Step 4: Extract Dialogs**
   - Both dialogs are independent, can be done in parallel

5. **Step 5: Extract Menu Manager**
   - After views are stable

6. **Step 6: Extract Utilities**
   - Clean up remaining common code

7. **Step 7: Final Refactoring**
   - Review and optimize
   - Update documentation

### Testing Strategy

After each extraction:
1. Run the application manually
2. Test all functionality of extracted component
3. Test integration with remaining components
4. Verify no regressions in other areas

### Migration Benefits by Phase

| Phase | Lines Removed | % Reduction | Maintainability Gain |
|-------|--------------|-------------|---------------------|
| Phase 1 | ~550 lines | 35% | High - Views isolated |
| Phase 2 | ~160 lines | 10% | Medium - Dialogs reusable |
| Phase 3 | ~90 lines | 6% | Medium - Menu logic clear |
| Phase 4 | ~90 lines | 6% | Low - Utilities centralized |
| **Total** | **~890 lines** | **57%** | **High Overall** |

---

## New Directory Structure (Final State)

```
tradingtools/
├── app.py                     # ~400 lines (main app orchestration)
├── dbmanager.py              # Existing
├── logger_config.py          # Existing
├── cnb_rate.py              # Existing
├── config/                   # Existing
│   ├── country_resolver.py
│   ├── tax_rates_loader.py
│   └── ...
├── db/                       # Existing
│   └── repositories/
│       ├── trades.py
│       ├── dividends.py
│       └── ...
├── views/                    # NEW
│   ├── __init__.py
│   ├── base_view.py
│   ├── trades_view.py
│   ├── dividends_view.py
│   ├── interests_view.py
│   └── realized_income_view.py
├── dialogs/                  # NEW
│   ├── __init__.py
│   ├── base_dialog.py
│   ├── exchange_rate_dialog.py
│   └── import_rates_dialog.py
└── ui/                       # NEW
    ├── __init__.py
    ├── menu_manager.py
    ├── filter_manager.py
    └── ui_utils.py
```

---

## Risk Mitigation

### Potential Issues and Solutions

1. **State Management Complexity**
   - Risk: Views need access to shared state
   - Solution: Pass dependencies via constructor, use callbacks for updates

2. **Circular Dependencies**
   - Risk: Views reference app, app references views
   - Solution: Use dependency injection, avoid circular imports

3. **Event Handling**
   - Risk: Callbacks between components become complex
   - Solution: Use event coordinator pattern or simple callback registration

4. **Testing During Transition**
   - Risk: Mixed state where some code is refactored, some isn't
   - Solution: Maintain backward compatibility during each step

---

## Success Criteria

- [x] app.py reduced to under 500 lines
- [x] Each view is self-contained in its own module
- [x] All functionality works as before
- [x] Code is more maintainable and testable
- [x] Clear separation of concerns
- [x] Documentation updated

---

## Timeline Estimate

- **Phase 1:** 6-8 hours (views extraction)
- **Phase 2:** 2-3 hours (dialogs extraction)
- **Phase 3:** 2 hours (menu manager)
- **Phase 4:** 2 hours (utilities)
- **Phase 5:** 2 hours (final cleanup)

**Total Estimated Time:** 14-17 hours

---

## Next Steps

1. **Review this plan** - Get approval for approach
2. **Create base infrastructure** - Set up directories and base classes
3. **Start with TradesView** - Prove the concept
4. **Iterate through remaining phases**

---

## Notes

- This refactoring can be done incrementally without breaking the application
- Each phase delivers immediate value
- The approach is reversible if issues arise
- Consider adding unit tests during refactoring
- Update `.github/copilot-instructions.md` after refactoring
