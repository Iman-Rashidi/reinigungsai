"""Command-line entry point for manual or scheduled discovery runs."""
from __future__ import annotations

import argparse
import json

from .service import run_discovery


def main() -> None:
    parser = argparse.ArgumentParser(description="ReinigungsRadar multi-source opportunity discovery")
    parser.add_argument("--city", default="NRW")
    parser.add_argument(
        "--category",
        default="Alle",
        choices=["Alle", "Reinigung", "Sicherheit", "Facility Management", "Bau / Handwerk"],
    )
    parser.add_argument("--days-back", type=int, default=7)
    parser.add_argument("--no-tavily", action="store_true")
    args = parser.parse_args()
    result = run_discovery(
        city=args.city,
        category=args.category,
        days_back=args.days_back,
        include_tavily=not args.no_tavily,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
