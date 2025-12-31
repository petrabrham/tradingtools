"""
Utility module for resolving country of origin for securities.
Handles manual overrides and fallback to ISIN-based detection.
"""
import json
import os
from typing import Optional, Tuple


class CountryResolver:
    """Resolves country of origin for securities using overrides and ISIN fallback."""
    
    def __init__(self, overrides_path: Optional[str] = None):
        """Initialize the country resolver.
        
        Args:
            overrides_path: Path to the JSON overrides file. If None, uses default location.
        """
        if overrides_path is None:
            # Default to config/country_overrides.json relative to this file
            current_dir = os.path.dirname(os.path.abspath(__file__))
            overrides_path = os.path.join(current_dir, 'country_overrides.json')
        
        self.overrides_path = overrides_path
        self.overrides = {}
        self._load_overrides()
    
    def _load_overrides(self):
        """Load country overrides from JSON file."""
        try:
            with open(self.overrides_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Build a dictionary: ISIN -> country_code
            for isin, entry in data.get('overrides', {}).items():
                if isinstance(entry, dict):
                    country_code = entry.get('country_code')
                else:
                    # Simple format: "ISIN": "CC"
                    country_code = entry
                
                if country_code:
                    self.overrides[isin.upper()] = country_code.upper()
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Info: Could not load country overrides from {self.overrides_path}: {e}")
            # Continue with empty overrides dictionary
    
    def get_country(self, isin: str) -> Tuple[str, str]:
        """Get the country code for a given ISIN.
        
        Uses three-tier lookup:
        1. Check manual overrides (most reliable)
        2. Extract from ISIN (first 2 characters)
        3. Default to "XX" (unknown)
        
        Args:
            isin: The ISIN code
        
        Returns:
            Tuple of (country_code, source) where source is:
            - "override" if from manual mapping
            - "isin" if extracted from ISIN code
            - "unknown" if defaulted to XX
        """
        if not isin:
            return ("XX", "unknown")
        
        isin_upper = isin.upper()
        
        # First: Check manual overrides
        if isin_upper in self.overrides:
            return (self.overrides[isin_upper], "override")
        
        # Second: Extract from ISIN (first 2 characters)
        if len(isin) >= 2:
            country_code = isin[:2].upper()
            return (country_code, "isin")
        
        # Third: Default to unknown
        return ("XX", "unknown")
    
    def has_override(self, isin: str) -> bool:
        """Check if an ISIN has a manual override.
        
        Args:
            isin: The ISIN code
        
        Returns:
            True if override exists, False otherwise
        """
        return isin.upper() in self.overrides if isin else False
    
    def add_override(self, isin: str, country_code: str, name: Optional[str] = None, 
                     note: Optional[str] = None, save: bool = True):
        """Add or update a country override.
        
        Args:
            isin: The ISIN code
            country_code: ISO 3166-1 alpha-2 country code
            name: Optional security name for documentation
            note: Optional note explaining the override
            save: If True, save changes to JSON file immediately
        """
        isin_upper = isin.upper()
        country_upper = country_code.upper()
        
        # Update in-memory cache
        self.overrides[isin_upper] = country_upper
        
        if save:
            self._save_override(isin_upper, country_upper, name, note)
    
    def _save_override(self, isin: str, country_code: str, 
                       name: Optional[str] = None, note: Optional[str] = None):
        """Save an override to the JSON file."""
        try:
            # Load existing data
            try:
                with open(self.overrides_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except FileNotFoundError:
                # Create new structure if file doesn't exist
                data = {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "description": "Manual country of origin overrides for securities",
                    "metadata": {
                        "last_updated": "2025-12-31",
                        "purpose": "Correct country assignment for ADRs and cross-listings"
                    },
                    "overrides": {}
                }
            
            # Update override
            if 'overrides' not in data:
                data['overrides'] = {}
            
            entry = {"country_code": country_code}
            if name:
                entry["name"] = name
            if note:
                entry["note"] = note
            
            data['overrides'][isin] = entry
            
            # Save to file
            with open(self.overrides_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Warning: Could not save override to {self.overrides_path}: {e}")
    
    def remove_override(self, isin: str, save: bool = True):
        """Remove a country override.
        
        Args:
            isin: The ISIN code
            save: If True, save changes to JSON file immediately
        """
        isin_upper = isin.upper()
        
        # Remove from in-memory cache
        if isin_upper in self.overrides:
            del self.overrides[isin_upper]
        
        if save:
            self._remove_override_from_file(isin_upper)
    
    def _remove_override_from_file(self, isin: str):
        """Remove an override from the JSON file."""
        try:
            with open(self.overrides_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if 'overrides' in data and isin in data['overrides']:
                del data['overrides'][isin]
                
                with open(self.overrides_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Warning: Could not remove override from {self.overrides_path}: {e}")
    
    def get_all_overrides(self) -> dict:
        """Get all country overrides.
        
        Returns:
            Dictionary mapping ISIN -> country_code
        """
        return self.overrides.copy()
