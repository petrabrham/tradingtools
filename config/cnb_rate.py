"""CNB exchange rate fetcher.

This module provides access to Czech National Bank (CNB) exchange rates.
Rates are fetched directly from CNB's public API.
"""

import datetime
import urllib.request
import urllib.error
from typing import Dict, Optional
import re


class cnb_rate:
    """Fetch and cache exchange rates from CNB."""

    def __init__(self):
        # In-memory cache only: mapping date -> {currency -> rate}
        # Keys are datetime.date objects. Cache lives only for the process lifetime.
        self._daily_cache: Dict[datetime.date, Dict[str, float]] = {}
        self._annual_cache: Dict[int, Dict[str, float]] = {}  # year -> {currency -> rate}
        self._last_fetch_date: Optional[datetime.date] = None
        self._base_url = "https://www.cnb.cz/en/financial-markets/foreign-exchange-market/central-bank-exchange-rate-fixing/central-bank-exchange-rate-fixing"

    def _fetch_daily_rates(self, date: datetime.date) -> Dict[str, float]:
        """Fetch daily rates for given date from CNB website.
        
        Args:
            date: The date to fetch rates for
            
        Returns:
            Dict mapping currency codes to rates (amount of CZK per 1 unit)
            
        Raises:
            urllib.error.URLError: If the fetch fails
            ValueError: If the response format is invalid
        """
        # Format date as required by CNB API
        date_str = date.strftime("%d.%m.%Y")
        
        # Build URL with date parameter
        url = f"{self._base_url}/daily.txt?date={date_str}"
        
        try:
            with urllib.request.urlopen(url) as response:
                data = response.read().decode('utf-8')
        except urllib.error.URLError as e:
            raise urllib.error.URLError(f"Failed to fetch CNB rates for {date}: {e}") from e
            
        # Parse the response
        # Example format:
        # 03 Nov 2025 #213
        # country|currency|amount|code|rate
        # Australia|dollar|1|AUD|15.482
        # Brazil|real|1|BRL|4.673
        # Bulgaria|lev|1|BGN|12.842
        # ...
        
        try:
            lines = data.strip().split('\n')
            if len(lines) < 2:
                raise ValueError(f"Invalid CNB rate data format for {date}")
                
            rates = {}
            for line in lines[2:]:  # Skip header lines
                parts = line.strip().split('|')
                if len(parts) != 5:
                    continue
                    
                country, currency, amount, code, rate = parts
                try:
                    amount_val = float(amount)
                    rate_val = float(rate)
                    # Normalize to rate per 1 unit
                    rates[code] = rate_val / amount_val
                except ValueError:
                    continue  # Skip invalid numbers
                    
            return rates
            
        except Exception as e:
            raise ValueError(f"Failed to parse CNB rate data for {date}: {e}") from e

    def _fetch_annual_rates(self, year: int) -> Dict[str, float]:
        """Fetch annual rates for given year by averaging CNB daily rates.
        
        These approximate the unified rates ("jednotný kurz") published by GFŘ.
        According to Czech tax law, taxpayers can use either daily CNB rates or 
        the annual unified rate published by GFŘ.
        
        Args:
            year: The calendar year to fetch rates for
            
        Returns:
            Dict mapping currency codes to annual rates (amount of CZK per 1 unit)
            
        Raises:
            ValueError: If calculation fails
        """
        try:
            # Calculate arithmetic mean of CNB daily rates for the year
            start_date = datetime.date(year, 1, 1)
            end_date = datetime.date(year, 12, 31)
            
            currency_sums: Dict[str, list] = {}
            current_date = start_date
            
            while current_date <= end_date:
                try:
                    daily_rates = self._fetch_daily_rates(current_date)
                    for currency, rate in daily_rates.items():
                        if currency not in currency_sums:
                            currency_sums[currency] = []
                        currency_sums[currency].append(rate)
                except (urllib.error.URLError, ValueError):
                    # Skip days without data (weekends, holidays)
                    pass
                current_date += datetime.timedelta(days=1)
            
            # Calculate averages
            annual_rates = {}
            for currency, rates_list in currency_sums.items():
                if rates_list:
                    annual_rates[currency] = sum(rates_list) / len(rates_list)
            
            return annual_rates
            
        except Exception as e:
            raise ValueError(f"Failed to calculate annual rates for {year}: {e}") from e

    def annual_rate(self, currency: str, year: int) -> float:
        """Get the annual unified exchange rate for given currency and year.
        
        This approximates the "jednotný kurz" published by GFŘ for tax purposes.
        According to Czech tax law, taxpayers can choose to use either:
        1. Daily CNB rates (using daily_rate method)
        2. Annual unified rate from GFŘ (using this method)
        
        Args:
            currency: Three-letter currency code (e.g., 'EUR', 'USD')
            year: The calendar year to get rate for
            
        Returns:
            Exchange rate as float (amount of CZK per 1 unit of currency)
            
        Raises:
            ValueError: If currency is invalid or rate not available
        """
        currency = currency.upper()
        if not re.match(r'^[A-Z]{3}$', currency):
            raise ValueError("currency must be a three-letter code")
            
        # Special case - CZK always converts 1:1
        if currency == 'CZK':
            return 1.0
            
        # Check if we have cached data for this year
        if year not in self._annual_cache:
            try:
                self._annual_cache[year] = self._fetch_annual_rates(year)
            except (urllib.error.URLError, ValueError) as e:
                raise ValueError(f"Failed to get annual rate for {currency} in {year}: {e}") from e
                
        rates = self._annual_cache[year]
            
        if currency == 'GBX':
            # Calculate rate for GBX from GBP
            if 'GBP' not in rates:
                raise ValueError(f"No annual rate available for GBX in {year}")
            return rates['GBP'] / 100.0
        else:
            if currency not in rates:
                raise ValueError(f"No annual rate available for {currency} in {year}")
            return rates[currency]

    def daily_rate(self, currency: str, date: datetime.date | datetime.datetime) -> float:
        """Get the CNB exchange rate for given currency and date.
        
        Args:
            currency: Three-letter currency code (e.g., 'EUR', 'USD')
            date: The date to get rate for (if datetime, date part is used)
            
        Returns:
            Exchange rate as float (amount of CZK per 1 unit of currency)
            
        Raises:
            ValueError: If currency is invalid or rate not available
        """
        if isinstance(date, datetime.datetime):
            date = date.date()
            
        if not isinstance(date, datetime.date):
            raise ValueError("date must be datetime.date or datetime.datetime")
            
        currency = currency.upper()
        if not re.match(r'^[A-Z]{3}$', currency):
            raise ValueError("currency must be a three-letter code")
            
        # Special case - CZK always converts 1:1
        if currency == 'CZK':
            return 1.0
            
        # Check if we have cached data for this date
        if date not in self._daily_cache:
            try:
                # Fetch and cache in memory only
                self._daily_cache[date] = self._fetch_daily_rates(date)
            except (urllib.error.URLError, ValueError) as e:
                raise ValueError(f"Failed to get rate for {currency} on {date}: {e}") from e
                
        rates = self._daily_cache[date]
            
        if currency == 'GBX':
            # Calculate rate for GPX from GBP
            if 'GBP' not in rates:
                raise ValueError(f"No rate available for GBX on {date}")
            return rates['GBP'] / 100.0
        else:
            if currency not in rates:
                raise ValueError(f"No rate available for {currency} on {date}")
            return rates[currency]

    def clear_cache(self) -> None:
        """Clear the in-memory cache of fetched rates."""
        self._daily_cache.clear()
        self._annual_cache.clear()

