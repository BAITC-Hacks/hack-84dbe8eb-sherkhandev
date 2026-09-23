"""Restricted, non-interactive importer for verified live product details.

Usage (from ``backend``):
    CATALOG_MODE=live python -m scripts.import_catalog --product-id 123

The importer has a hard cap and never changes the fixture database.
"""

from __future__ import annotations

import argparse
import asyncio
import json

from app.catalog import CatalogService
from app.config import Settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import a small, explicit set of EKT product details")
    parser.add_argument("--product-id", action="append", required=True, dest="product_ids", help="EKT product id; repeat at most 20 times")
    return parser.parse_args()


async def run() -> int:
    args = parse_args()
    if len(args.product_ids) > 20:
        raise SystemExit("at most 20 product ids may be imported in one run")
    settings = Settings.from_env()
    if settings.catalog_mode != "live":
        raise SystemExit("refusing live import unless CATALOG_MODE=live")
    service = CatalogService(settings.catalog_db_path, settings)
    await service.initialize()
    try:
        results = await service.import_live_products(args.product_ids)
        print(json.dumps([result.model_dump(mode="json") for result in results], ensure_ascii=False, indent=2))
        return 0 if all(result.ok for result in results) else 1
    finally:
        await service.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
