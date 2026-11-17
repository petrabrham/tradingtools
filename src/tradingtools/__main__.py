import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Trading Tools")
    parser.add_argument(
        "--smoke-test", type=Path, metavar="REPORT",
        help="Run isolated offline checks and write a JSON report instead of opening the application.",
    )
    args = parser.parse_args()
    if args.smoke_test is not None:
        from tradingtools._smoke_test import run_smoke_test

        run_smoke_test(args.smoke_test)
    else:
        from tradingtools.app import main as run_application

        run_application()


if __name__ == "__main__":
    main()
