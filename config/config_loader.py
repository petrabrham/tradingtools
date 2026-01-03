"""
Configuration loader for TradingTools application.

Provides centralized access to application configuration from config.json.
"""

import json
import os
from typing import Optional, Dict, Any
from pathlib import Path


class ConfigLoader:
    """Singleton configuration loader."""
    
    _instance: Optional['ConfigLoader'] = None
    _config: Optional[Dict[str, Any]] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._config is None:
            self._load_config()
    
    def _load_config(self):
        """Load configuration from config.json file."""
        # Get the directory where this file is located
        config_dir = Path(__file__).parent
        config_path = config_dir / 'config.json'
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                self._config = json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in configuration file: {e}")
    
    def get(self, *keys, default=None) -> Any:
        """Get configuration value by nested keys.
        
        Args:
            *keys: Nested keys to traverse (e.g., 'tax', 'czech_republic', 'time_test_exemption')
            default: Default value if key not found
            
        Returns:
            Configuration value or default
            
        Example:
            config.get('tax', 'czech_republic', 'capital_gains', 'default_rate')
        """
        value = self._config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value
    
    def reload(self):
        """Reload configuration from file."""
        self._config = None
        self._load_config()
    
    # Convenience methods for common configuration values
    
    def get_time_test_holding_period_years(self) -> int:
        """Get the required holding period in years for tax exemption (time test).
        
        Returns:
            Number of years required for capital gains tax exemption (default: 3)
        """
        return self.get('tax', 'czech_republic', 'time_test_exemption', 'holding_period_years', default=3)
    
    def get_capital_gains_tax_rate(self) -> float:
        """Get the default capital gains tax rate.
        
        Returns:
            Tax rate as decimal (e.g., 0.15 for 15%)
        """
        return self.get('tax', 'czech_republic', 'capital_gains', 'default_rate', default=0.15)
    
    def get_pairing_methods(self) -> list:
        """Get list of available pairing methods.
        
        Returns:
            List of method names (e.g., ['FIFO', 'LIFO', 'MaxLose', 'MaxProfit', 'Manual'])
        """
        return self.get('pairing', 'methods', default=['FIFO', 'LIFO', 'MaxLose', 'MaxProfit', 'Manual'])
    
    def get_default_pairing_method(self) -> str:
        """Get the default pairing method.
        
        Returns:
            Method name (default: 'FIFO')
        """
        return self.get('pairing', 'default_method', default='FIFO')


# Global instance for easy access
_config_loader = None

def get_config() -> ConfigLoader:
    """Get the global configuration loader instance.
    
    Returns:
        ConfigLoader instance
    """
    global _config_loader
    if _config_loader is None:
        _config_loader = ConfigLoader()
    return _config_loader


# Convenience functions for direct access
def get_time_test_holding_period_years() -> int:
    """Get the required holding period in years for tax exemption.
    
    Returns:
        Number of years (default: 3)
    """
    return get_config().get_time_test_holding_period_years()


def get_capital_gains_tax_rate() -> float:
    """Get the capital gains tax rate.
    
    Returns:
        Tax rate as decimal (default: 0.15)
    """
    return get_config().get_capital_gains_tax_rate()


def get_pairing_methods() -> list:
    """Get available pairing methods.
    
    Returns:
        List of method names
    """
    return get_config().get_pairing_methods()


def get_default_pairing_method() -> str:
    """Get the default pairing method.
    
    Returns:
        Method name (default: 'FIFO')
    """
    return get_config().get_default_pairing_method()
