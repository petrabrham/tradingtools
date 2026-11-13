"""Test script for database aggregation improvements"""

def main() -> None:
    try:
        from tradingtools.db.repositories.dividends import DividendsRepository
        from tradingtools.db.base import BaseRepository

        print("Successfully imported repository classes")
    except ImportError as error:
        print(f"Could not import repository classes: {error}")
        return

    test_query = """
SELECT 
    UPPER(SUBSTR(s.isin, 1, 2)) as country_code, 
    COALESCE(SUM(d.gross_czk), 0.0) as total_gross, 
    COALESCE(SUM(d.withholding_tax_czk), 0.0) as total_tax, 
    COALESCE(SUM(d.net_czk), 0.0) as total_net 
FROM dividends d 
JOIN securities s ON d.isin_id = s.id 
WHERE d.timestamp >= ? AND d.timestamp <= ? 
GROUP BY country_code 
ORDER BY country_code
"""

    print("\nNew SQL Query for Country Aggregation:")
    print("=" * 60)
    print(test_query)
    print("=" * 60)

    print("\nExplanation:")
    print("- UPPER(SUBSTR(s.isin, 1, 2)): Extract first 2 chars of ISIN as country")
    print("- GROUP BY country_code: Aggregate by country")
    print("- COALESCE(SUM(...)): Sum with null-safe handling")
    print("- Returns: (country_code, total_gross, total_tax, total_net)")

    print("\nBenefits:")
    print("Database performs aggregation (more efficiently)")
    print("Reduces data transfer from DB to Python")
    print("Leverages SQL's optimized GROUP BY")
    print("Separates database work from application logic")

    print("\nUsage in CSV mode:")
    print("  db_total_gross, db_total_tax, db_total_net = \\")
    print("      self.db.dividends_repo.get_summary_by_date_range(start_ts, end_ts)")
    print("  # Uses existing method for overall totals")

    print("\nUsage in JSON mode:")
    print("  # Still uses Python accumulation since taxes are recalculated")
    print("  # from JSON rates and cannot be pre-aggregated in the database")


if __name__ == "__main__":
    main()
