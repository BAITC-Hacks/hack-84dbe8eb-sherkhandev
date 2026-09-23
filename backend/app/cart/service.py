from __future__ import annotations

import asyncio
import hashlib
import html
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.contracts import Cart, CartItem, ConfirmResult, ErrorInfo, PendingAction, PendingActionResult, ProductSnapshot, SessionContext, ToolResult


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ok(value: Any) -> ToolResult:
    return ToolResult(ok=True, data=value)


def _err(code: str, message: str, retryable: bool = False) -> ToolResult:
    return ToolResult(ok=False, error=ErrorInfo(code=code, message=message, retryable=retryable))


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class CartService:
    """SQLite-backed cart with all blocking work isolated in worker threads."""

    def __init__(self, db_path: str | Path, catalog: Any, settings: Any) -> None:
        self.db_path = Path(db_path)
        self.catalog = catalog
        self.settings = settings
        self._guard = asyncio.Lock()
        self._view_tokens: dict[str, str] = {}

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize_sync)

    async def close(self) -> None:
        return None

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.db_path, timeout=10)
        con.row_factory = sqlite3.Row
        return con

    def _initialize_sync(self) -> None:
        con = self._connect()
        try:
            con.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS carts (
                cart_id TEXT PRIMARY KEY, session_id TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS actions (
                action_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                cart_id TEXT NOT NULL, product_id TEXT NOT NULL, warehouse_id TEXT NOT NULL,
                product_name TEXT NOT NULL, quantity INTEGER NOT NULL, unit_price TEXT NOT NULL,
                added_amount TEXT NOT NULL, unit TEXT NOT NULL, quantity_step TEXT NOT NULL,
                stock_quantity TEXT NOT NULL, checked_at TEXT NOT NULL, expires_at TEXT NOT NULL,
                source_kind TEXT NOT NULL, status TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS actions_session_status ON actions(session_id, status);
            CREATE TABLE IF NOT EXISTS cart_items (
                line_id TEXT PRIMARY KEY, cart_id TEXT NOT NULL, product_id TEXT NOT NULL,
                warehouse_id TEXT NOT NULL, name TEXT NOT NULL, quantity INTEGER NOT NULL,
                unit_price TEXT NOT NULL, line_total TEXT NOT NULL, source_action_id TEXT UNIQUE NOT NULL
            );
            CREATE TABLE IF NOT EXISTS cart_views (
                token_hash TEXT PRIMARY KEY, cart_id TEXT NOT NULL, session_id TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );
            """)
            con.commit()
        finally:
            con.close()

    def _cart_id(self, session_id: str) -> str:
        return f"cart-{session_id}"

    def _ensure_cart(self, con: sqlite3.Connection, context: SessionContext) -> str:
        cart_id = self._cart_id(context.session_id)
        con.execute("INSERT OR IGNORE INTO carts(cart_id,session_id,created_at) VALUES(?,?,?)", (cart_id, context.session_id, _now().isoformat()))
        return cart_id

    def _action_dto(self, row: sqlite3.Row) -> PendingAction:
        return PendingAction(
            action_id=row["action_id"], product_id=row["product_id"], warehouse_id=row["warehouse_id"],
            product_name=row["product_name"], quantity_to_add=row["quantity"], unit_price=Decimal(row["unit_price"]),
            added_amount=Decimal(row["added_amount"]), currency="KZT", unit=row["unit"],
            quantity_step=Decimal(row["quantity_step"]), stock_quantity=Decimal(row["stock_quantity"]),
            checked_at=datetime.fromisoformat(row["checked_at"]), expires_at=datetime.fromisoformat(row["expires_at"]),
            source_kind=row["source_kind"],
        )

    def _cart_dto(self, con: sqlite3.Connection, cart_id: str, session_id: str, create_url: bool = True, commit_view: bool = True) -> Cart:
        rows = con.execute("SELECT * FROM cart_items WHERE cart_id=? ORDER BY rowid", (cart_id,)).fetchall()
        items = [CartItem(line_id=r["line_id"], product_id=r["product_id"], warehouse_id=r["warehouse_id"], name=r["name"], quantity=r["quantity"], unit_price_at_addition=Decimal(r["unit_price"]), line_total=Decimal(r["line_total"]), source_action_id=r["source_action_id"]) for r in rows]
        total = sum((item.line_total for item in items), Decimal("0"))
        now = _now()
        view = con.execute("SELECT token_hash,expires_at FROM cart_views WHERE cart_id=? AND session_id=? ORDER BY expires_at DESC LIMIT 1", (cart_id, session_id)).fetchone()
        cached_token = self._view_tokens.get(cart_id)
        if create_url and (view is None or datetime.fromisoformat(view["expires_at"]) <= now or cached_token is None):
            token = secrets.token_urlsafe(24)
            expires = now + timedelta(seconds=int(getattr(self.settings, "view_ttl_seconds", 1800)))
            con.execute("INSERT INTO cart_views(token_hash,cart_id,session_id,expires_at) VALUES(?,?,?,?)", (_hash(token), cart_id, session_id, expires.isoformat()))
            if commit_view:
                con.commit()
            self._view_tokens[cart_id] = token
            path = f"/cart/view/{token}"
        elif view is not None:
            path = f"/cart/view/{cached_token}"
        else:
            path = "/cart/view/"
        base = str(getattr(self.settings, "app_base_url", "")).rstrip("/")
        return Cart(cart_id=cart_id, items=items, total=total, data_mode=getattr(self.settings, "catalog_mode", "fixture"), cart_url=base + path)

    async def prepare_action(self, context: SessionContext, product_id: str, warehouse_id: str, quantity_to_add: int) -> ToolResult[PendingAction]:
        if isinstance(quantity_to_add, bool) or not isinstance(quantity_to_add, int) or quantity_to_add <= 0:
            return _err("INVALID_QUANTITY", "Quantity must be a positive integer")
        snap = await self.catalog.get_snapshot(product_id, warehouse_id, refresh=True)
        if not snap.ok:
            return snap
        result = self._validate_snapshot(snap.data, quantity_to_add)
        if result is not None:
            return result
        now = _now()
        action = PendingAction(
            action_id=secrets.token_urlsafe(18),
            product_id=product_id,
            warehouse_id=warehouse_id,
            product_name=snap.data.product.name,
            quantity_to_add=quantity_to_add,
            unit_price=snap.data.product.price,
            added_amount=snap.data.product.price * quantity_to_add,
            unit="pcs",
            quantity_step=snap.data.product.quantity_step,
            stock_quantity=snap.data.stock.quantity,
            checked_at=now,
            expires_at=now + timedelta(seconds=int(getattr(self.settings, "action_ttl_seconds", 300))),
            source_kind=snap.data.product.source_kind,
        )
        save_err = await asyncio.to_thread(self._save_pending_sync, context, action, snap.data.stock.quantity)
        if save_err is not None:
            return _err(save_err, "Insufficient stock for requested quantity")
        return _ok(action)

    @staticmethod
    def _validate_snapshot(snap: ProductSnapshot, quantity: int) -> ToolResult | None:
        p, s = snap.product, snap.stock
        if p.price is None:
            return _err("PRICE_UNKNOWN", "Product price is unknown")
        if p.unit is None or s.quantity is None or p.quantity_step is None:
            return _err("INVALID_SOURCE_DATA", "Sale unit, step, or stock is unknown")
        if p.unit != "pcs":
            return _err("UNSUPPORTED_SALE_UNIT", f"Unsupported sale unit: {p.unit}")
        if not p.quantity_step.is_finite() or p.quantity_step <= Decimal("0") or p.quantity_step % Decimal("1") != Decimal("0"):
            return _err("UNSUPPORTED_SALE_UNIT", "Quantity step must be a positive integer")
        step_int = int(p.quantity_step)
        if quantity % step_int != 0:
            return _err("INVALID_QUANTITY", f"Quantity must be a multiple of the sale step ({step_int})")
        if s.warehouse_eligible is not True:
            return _err("WAREHOUSE_NOT_ELIGIBLE", "Selected warehouse is not eligible for purchase")
        if s.quantity <= 0:
            return _err("INSUFFICIENT_STOCK", "Selected warehouse has no stock")
        return None

    def _save_pending_sync(self, context: SessionContext, action: PendingAction, fresh_stock: Decimal) -> str | None:
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            cart_id = self._ensure_cart(con, context)
            row = con.execute(
                "SELECT COALESCE(SUM(quantity),0) AS n FROM cart_items WHERE cart_id=? AND product_id=? AND warehouse_id=?",
                (cart_id, action.product_id, action.warehouse_id),
            ).fetchone()
            current_in_cart = Decimal(row["n"]) if row else Decimal("0")
            if current_in_cart + Decimal(action.quantity_to_add) > fresh_stock:
                con.rollback()
                return "INSUFFICIENT_STOCK"
            con.execute("UPDATE actions SET status='superseded' WHERE session_id=? AND status='pending'", (context.session_id,))
            con.execute(
                "INSERT INTO actions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    action.action_id,
                    context.session_id,
                    cart_id,
                    action.product_id,
                    action.warehouse_id,
                    action.product_name,
                    action.quantity_to_add,
                    str(action.unit_price),
                    str(action.added_amount),
                    action.unit,
                    str(action.quantity_step),
                    str(action.stock_quantity),
                    action.checked_at.isoformat(),
                    action.expires_at.isoformat(),
                    action.source_kind,
                    "pending",
                ),
            )
            con.commit()
            return None
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    async def get_pending_action(self, context: SessionContext) -> ToolResult[PendingActionResult]:
        row = await asyncio.to_thread(self._pending_sync, context.session_id)
        return _ok(PendingActionResult(action=self._action_dto(row) if row else None))

    def _pending_sync(self, session_id: str):
        con = self._connect()
        try:
            row = con.execute("SELECT * FROM actions WHERE session_id=? AND status='pending' ORDER BY checked_at DESC LIMIT 1", (session_id,)).fetchone()
            if row and datetime.fromisoformat(row["expires_at"]) <= _now():
                con.execute("UPDATE actions SET status='expired' WHERE action_id=?", (row["action_id"],)); con.commit(); return None
            return row
        finally: con.close()

    async def confirm_action(self, context: SessionContext, action_id: str) -> ToolResult[ConfirmResult]:
        row = await asyncio.to_thread(self._action_for_confirm, context.session_id, action_id)
        if row is None:
            return _err("ACTION_NOT_FOUND", "Action was not found")
        if row["status"] == "committed":
            cart = await asyncio.to_thread(self._get_cart_sync, context)
            return _ok(ConfirmResult(action_id=action_id, already_applied=True, cart=cart))
        if row["status"] in {"superseded", "invalidated"}:
            return _err("ACTION_SUPERSEDED", "This proposal was replaced or invalidated; request a new proposal")
        if row["status"] == "expired" or datetime.fromisoformat(row["expires_at"]) <= _now():
            await asyncio.to_thread(self._mark_status, action_id, "expired")
            return _err("ACTION_EXPIRED", "This proposal has expired")
        snap = await self.catalog.get_snapshot(row["product_id"], row["warehouse_id"], refresh=True)
        if not snap.ok:
            return snap
        changed = self._compare_action(row, snap.data)
        if changed:
            await asyncio.to_thread(self._mark_status, action_id, "invalidated")
            return _err(changed, "The product terms changed; request a new proposal")
        result = await asyncio.to_thread(self._commit_sync, context, row, snap.data)
        if isinstance(result, str):
            return _err(result, "The cart could not accept this proposal")
        cart, already_applied = result
        return _ok(ConfirmResult(action_id=action_id, already_applied=already_applied, cart=cart))

    def _action_for_confirm(self, session_id: str, action_id: str):
        con=self._connect()
        try:
            row=con.execute("SELECT * FROM actions WHERE action_id=? AND session_id=?", (action_id,session_id)).fetchone()
            return row
        finally: con.close()

    def _mark_status(self, action_id: str, status: str):
        con=self._connect(); con.execute("UPDATE actions SET status=? WHERE action_id=? AND status='pending'",(status,action_id)); con.commit(); con.close()

    @staticmethod
    def _compare_action(row, snap: ProductSnapshot) -> str | None:
        p,s=snap.product,snap.stock
        if p.price is None or p.price != Decimal(row["unit_price"]): return "PRICE_CHANGED"
        if p.unit != row["unit"] or p.quantity_step is None or p.quantity_step != Decimal(row["quantity_step"]): return "ACTION_TERMS_CHANGED"
        if s.quantity is None or s.warehouse_eligible is not True: return "ACTION_TERMS_CHANGED"
        return None

    def _commit_sync(self, context: SessionContext, row, snap: ProductSnapshot) -> tuple[Cart, bool] | str:
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            current = con.execute("SELECT * FROM actions WHERE action_id=? AND session_id=?", (row["action_id"], context.session_id)).fetchone()
            if current is None:
                return "ACTION_NOT_FOUND"
            if current["status"] == "committed":
                cart = self._cart_dto(con, current["cart_id"], context.session_id, create_url=True, commit_view=True)
                return cart, True
            if current["status"] != "pending":
                return "ACTION_SUPERSEDED" if current["status"] == "superseded" else "ACTION_EXPIRED"
            if datetime.fromisoformat(current["expires_at"]) <= _now():
                con.execute("UPDATE actions SET status='expired' WHERE action_id=?", (row["action_id"],))
                con.commit()
                return "ACTION_EXPIRED"
            existing = con.execute(
                "SELECT COALESCE(SUM(quantity),0) AS n FROM cart_items WHERE cart_id=? AND product_id=? AND warehouse_id=?",
                (current["cart_id"], current["product_id"], current["warehouse_id"]),
            ).fetchone()["n"]
            if Decimal(existing) + Decimal(current["quantity"]) > snap.stock.quantity:
                return "INSUFFICIENT_STOCK"
            line_id = secrets.token_urlsafe(12)
            con.execute(
                "INSERT INTO cart_items VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    line_id,
                    current["cart_id"],
                    current["product_id"],
                    current["warehouse_id"],
                    current["product_name"],
                    current["quantity"],
                    current["unit_price"],
                    current["added_amount"],
                    current["action_id"],
                ),
            )
            con.execute("UPDATE actions SET status='committed' WHERE action_id=?", (current["action_id"],))
            cart = self._cart_dto(con, current["cart_id"], context.session_id, create_url=True, commit_view=False)
            con.commit()
            return cart, False
        except sqlite3.IntegrityError:
            con.rollback()
            check = con.execute("SELECT * FROM actions WHERE action_id=? AND status='committed'", (row["action_id"],)).fetchone()
            if check:
                cart = self._cart_dto(con, check["cart_id"], context.session_id, create_url=True, commit_view=True)
                return cart, True
            return "ACTION_SUPERSEDED"
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    async def get_cart(self, context: SessionContext) -> ToolResult[Cart]:
        return _ok(await asyncio.to_thread(self._get_cart_sync, context))

    def _get_cart_sync(self, context):
        con=self._connect()
        try:
            cart_id=self._ensure_cart(con,context); con.commit(); return self._cart_dto(con,cart_id,context.session_id)
        finally: con.close()

    async def render_view(self, token: str) -> tuple[int, str]:
        return await asyncio.to_thread(self._render_view_sync, token)

    def _render_view_sync(self, token: str):
        con=self._connect()
        try:
            row=con.execute("SELECT c.cart_id,c.session_id,v.expires_at FROM cart_views v JOIN carts c ON c.cart_id=v.cart_id WHERE v.token_hash=?",(_hash(token),)).fetchone()
            if row is None or datetime.fromisoformat(row["expires_at"]) <= _now(): return 404, "<h1>Ссылка недействительна</h1>"
            cart=self._cart_dto(con,row["cart_id"],row["session_id"],create_url=False)
            items="".join(f"<li>{html.escape(i.name)} — {i.quantity} шт. — {html.escape(str(i.line_total))} KZT</li>" for i in cart.items) or "<li>Корзина пуста</li>"
            return 200, f"<!doctype html><meta charset='utf-8'><title>Корзина</title><h1>Демонстрационная корзина</h1><p>Режим: {html.escape(cart.data_mode)}</p><ul>{items}</ul><p>Итого: {html.escape(str(cart.total))} KZT</p><p>Ссылка только для просмотра.</p>"
        finally: con.close()
