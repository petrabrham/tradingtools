"""
Utility module for loading withholding tax rates from JSON configuration.
"""
import json
import os
from typing import Dict, Optional
from datetime import datetime


class TaxRatesLoader:
    """Loads and provides access to withholding tax rates from JSON config."""
    
    def __init__(self, config_path: Optional[str] = None):
        """Initialize the tax rates loader.
        
        Args:
            config_path: Path to the JSON config file. If None, uses default location.
        """
        if config_path is None:
            # Default to config/withholding_tax_rates.json relative to this file
            current_dir = os.path.dirname(os.path.abspath(__file__))
            config_path = os.path.join(current_dir, 'withholding_tax_rates.json')
        
        self.config_path = config_path
        self.rates_by_country = {}
        self._load_rates()
    
    def _load_rates(self):
        """Load tax rates from JSON file."""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Build a dictionary: country_code -> rate
            for entry in data.get('rates', []):
                country_code = entry.get('country_code')
                rate = entry.get('rate')
                if country_code and rate is not None:
                    self.rates_by_country[country_code] = rate / 100.0  # Convert percentage to decimal
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Warning: Could not load tax rates from {self.config_path}: {e}")
            # Continue with empty rates dictionary
    
    def get_rate(self, country_code: str) -> Optional[float]:
        """Get the withholding tax rate for a given country code.
        
        Args:
            country_code: ISO 3166-1 alpha-2 country code (e.g., 'US', 'GB')
        
        Returns:
            Tax rate as decimal (e.g., 0.15 for 15%) or None if not found
        """
        return self.rates_by_country.get(country_code.upper())
    
    def calculate_tax_from_net(self, net_amount: float, country_code: str) -> Optional[float]:
        """Calculate withholding tax from net amount using the formula:
        tax = net * rate / (1 - rate)
        
        Args:
            net_amount: The net dividend amount received
            country_code: ISO 3166-1 alpha-2 country code
        
        Returns:
            Calculated tax amount or None if rate not found
        """
        rate = self.get_rate(country_code)
        if rate is None:
            return None
        
        if rate >= 1.0:
            # Invalid rate (100% or more)
            return None
        
        # Formula: tax = net * rate / (1 - rate)
        tax = net_amount * rate / (1.0 - rate)
        return tax
    
    def calculate_gross_from_net(self, net_amount: float, country_code: str) -> Optional[float]:
        """Calculate gross amount from net using the formula:
        gross = net / (1 - rate)
        
        Args:
            net_amount: The net dividend amount received
            country_code: ISO 3166-1 alpha-2 country code
        
        Returns:
            Calculated gross amount or None if rate not found
        """
        rate = self.get_rate(country_code)
        if rate is None:
            return None
        
        if rate >= 1.0:
            # Invalid rate (100% or more)
            return None
        
        # Formula: gross = net / (1 - rate)
        gross = net_amount / (1.0 - rate)
        return gross
