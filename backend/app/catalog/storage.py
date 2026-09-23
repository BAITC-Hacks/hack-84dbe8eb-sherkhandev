"""Small SQLite persistence helpers for catalog records.

Every operation opens and closes its own connection.  This is intentional:
the application can safely call these helpers through ``asyncio.to_thread``
without sharing a SQLite connection between event-loop and worker threads.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Callable, TypeVar


T = TypeVar("T")


SCHEMA = """
CREATE TABLE IF NOT EXISTS catalog_products (
    product_id TEXT PRIMARY KEY,
    product_json TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS catalog_stocks (
    product_id TEXT NOT NULL,
    warehouse_id TEXT NOT NULL,
    stock_json TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    PRIMARY KEY (product_id, warehouse_id)
);
CREATE TABLE IF NOT EXISTS catalog_warehouses (
    warehouse_id TEXT PRIMARY KEY,
    warehouse_json TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    provenance_json TEXT NOT NULL
);
"""


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def run(path: Path, callback: Callable[[sqlite3.Connection], T]) -> T:
    """Run one complete SQLite operation with a short-lived connection."""

    connection = _connect(path)
    try:
        return callback(connection)
    finally:
        connection.close()


def initialize(path: Path) -> None:
    def operation(connection: sqlite3.Connection) -> None:
        connection.executescript(SCHEMA)
        connection.commit()

    run(path, operation)


def replace_catalog(path: Path, records: dict[str, Any]) -> None:
    """Replace the local mode snapshot in one transaction."""

    def operation(connection: sqlite3.Connection) -> None:
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute("DELETE FROM catalog_products")
            connection.execute("DELETE FROM catalog_stocks")
            connection.execute("DELETE FROM catalog_warehouses")
            for warehouse in records.get("warehouses", []):
                connection.execute(
                    "INSERT INTO catalog_warehouses VALUES (?, ?, ?, ?)",
                    (
                        warehouse["warehouse_id"],
                        json.dumps(warehouse["value"], ensure_ascii=False),
                        json.dumps(warehouse.get("raw", warehouse["value"]), ensure_ascii=False),
                        json.dumps(warehouse.get("provenance", {}), ensure_ascii=False),
                    ),
                )
            for product in records.get("products", []):
                connection.execute(
                    "INSERT OR REPLACE INTO catalog_products VALUES (?, ?, ?, ?, ?)",
                    (
                        product["value"]["product_id"],
                        json.dumps(product["value"], ensure_ascii=False),
                        json.dumps(product.get("raw", product["value"]), ensure_ascii=False),
                        json.dumps(product.get("provenance", {}), ensure_ascii=False),
                        product["value"]["fetched_at"],
                    ),
                )
                for stock in product.get("stocks", []):
                    connection.execute(
                        "INSERT OR REPLACE INTO catalog_stocks VALUES (?, ?, ?, ?, ?)",
                        (
                            product["value"]["product_id"],
                            stock["value"]["warehouse_id"],
                            json.dumps(stock["value"], ensure_ascii=False),
                            json.dumps(stock.get("raw", stock["value"]), ensure_ascii=False),
                            json.dumps(stock.get("provenance", {}), ensure_ascii=False),
                        ),
                    )
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    run(path, operation)


def upsert_product(path: Path, product: dict[str, Any], raw: Any, provenance: dict[str, Any], stocks: list[dict[str, Any]], warehouses: list[dict[str, Any]] | None = None) -> None:
    def operation(connection: sqlite3.Connection) -> None:
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                "INSERT OR REPLACE INTO catalog_products VALUES (?, ?, ?, ?, ?)",
                (
                    product["product_id"],
                    json.dumps(product, ensure_ascii=False),
                    json.dumps(raw, ensure_ascii=False),
                    json.dumps(provenance, ensure_ascii=False),
                    product["fetched_at"],
                ),
            )
            for record in warehouses or []:
                value = record.get("value", record)
                connection.execute(
                    "INSERT OR REPLACE INTO catalog_warehouses VALUES (?, ?, ?, ?)",
                    (
                        value["warehouse_id"],
                        json.dumps(value, ensure_ascii=False),
                        json.dumps(record.get("raw", value), ensure_ascii=False),
                        json.dumps(record.get("provenance", provenance), ensure_ascii=False),
                    ),
                )
            for stock in stocks:
                value = stock.get("value", stock)
                connection.execute(
                    "INSERT OR REPLACE INTO catalog_stocks VALUES (?, ?, ?, ?, ?)",
                    (
                        value["product_id"],
                        value["warehouse_id"],
                        json.dumps(value, ensure_ascii=False),
                        json.dumps(raw, ensure_ascii=False),
                        json.dumps(provenance, ensure_ascii=False),
                    ),
                )
                warehouse = value.get("warehouse")
                if warehouse:
                    connection.execute(
                        "INSERT OR REPLACE INTO catalog_warehouses VALUES (?, ?, ?, ?)",
                        (
                            warehouse["warehouse_id"],
                            json.dumps(warehouse, ensure_ascii=False),
                            json.dumps(raw, ensure_ascii=False),
                            json.dumps(provenance, ensure_ascii=False),
                        ),
                    )
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    run(path, operation)


def read_rows(path: Path, sql: str, parameters: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    def operation(connection: sqlite3.Connection) -> list[dict[str, Any]]:
        rows = connection.execute(sql, parameters).fetchall()
        return [dict(row) for row in rows]

    return run(path, operation)
