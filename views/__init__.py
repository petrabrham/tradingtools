"""
Views package for TradingTools application.

Contains view classes that handle UI creation and data display for different tabs.
"""

from .base_view import BaseView
from .trades_view import TradesView
from .interests_view import InterestsView

__all__ = ['BaseView', 'TradesView', 'InterestsView']
