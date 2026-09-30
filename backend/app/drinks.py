from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

CAIRO = ZoneInfo("Africa/Cairo")


class DrinkTabCreate(BaseModel):
    customer_name: str = Field(min_length=1, max_length=100)

    @field_validator("customer_name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = " ".join(value.strip().split())
        if not value:
            raise ValueError("Customer name is required")
        return value


class DrinkItemCreate(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(default=1, ge=1, le=100)


class DrinkCheckoutRequest(BaseModel):
    payment_method: str = Field(default="CASH", pattern=r"^(CASH|INSTAPAY|VISA)$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None = None) -> str:
    return (dt or _now()).isoformat()


def current_business_date() -> str:
    return _now().astimezone(CAIRO).strftime("%Y-%m-%d")


def _customer_key(name: str) -> str:
    return " ".join(name.casefold().strip().split())


def ensure_drinks_schema(engine) -> None:
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS drink_tabs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_date VARCHAR(10) NOT NULL,
                customer_name VARCHAR(100) NOT NULL,
                customer_key VARCHAR(100) NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'OPEN',
                invoice_number VARCHAR(40),
                payment_method VARCHAR(20),
                shift_id INTEGER,
                total_piasters INTEGER NOT NULL DEFAULT 0,
                opened_by_user_id INTEGER NOT NULL,
                closed_by_user_id INTEGER,
                opened_at VARCHAR(40) NOT NULL,
                closed_at VARCHAR(40),
                FOREIGN KEY(opened_by_user_id) REFERENCES users(id),
                FOREIGN KEY(closed_by_user_id) REFERENCES users(id),
                FOREIGN KEY(shift_id) REFERENCES shifts(id)
            )
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS drink_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tab_id INTEGER NOT NULL,
                product_id INTEGER,
                drink_name VARCHAR(100) NOT NULL,
                unit_price_piasters INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                added_by_user_id INTEGER NOT NULL,
                added_at VARCHAR(40) NOT NULL,
                FOREIGN KEY(tab_id) REFERENCES drink_tabs(id) ON DELETE CASCADE,
                FOREIGN KEY(product_id) REFERENCES products(id),
                FOREIGN KEY(added_by_user_id) REFERENCES users(id)
            )
            """
        )
        tab_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(drink_tabs)")}
        if "shift_id" not in tab_cols:
            conn.exec_driver_sql("ALTER TABLE drink_tabs ADD COLUMN shift_id INTEGER REFERENCES shifts(id)")
        item_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(drink_items)")}
        if "product_id" not in item_cols:
            # Nullable for v0.31b historical rows. New v0.31c rows always store it.
            conn.exec_driver_sql("ALTER TABLE drink_items ADD COLUMN product_id INTEGER REFERENCES products(id)")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_drink_tabs_status_date ON drink_tabs(status, business_date)")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_drink_items_tab ON drink_items(tab_id)")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_drink_items_product ON drink_items(product_id)")
        conn.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS uq_drink_open_customer ON drink_tabs(customer_key) WHERE status='OPEN'")
        conn.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS uq_drink_invoice_number ON drink_tabs(invoice_number) WHERE invoice_number IS NOT NULL")


def _item_rows(db: Session, tab_id: int) -> list[dict]:
    rows = db.execute(
        text("""
            SELECT id, product_id, drink_name, unit_price_piasters, quantity, added_by_user_id, added_at,
                   (unit_price_piasters * quantity) AS line_total_piasters
            FROM drink_items WHERE tab_id=:tab_id ORDER BY id
        """), {"tab_id": tab_id}
    ).mappings().all()
    return [dict(row) for row in rows]


def _tab_row(db: Session, tab_id: int):
    return db.execute(text("SELECT * FROM drink_tabs WHERE id=:id"), {"id": tab_id}).mappings().first()


def tab_snapshot(db: Session, tab_id: int) -> dict:
    row = _tab_row(db, tab_id)
    if not row:
        raise HTTPException(404, "Drink customer tab not found")
    items = _item_rows(db, tab_id)
    live_total = sum(int(x["line_total_piasters"] or 0) for x in items)
    data = dict(row)
    data["items"] = items
    data["total_piasters"] = int(data.get("total_piasters") or 0) if data["status"] == "PAID" else live_total
    return data


def create_or_get_tab(db: Session, customer_name: str, user_id: int) -> tuple[dict, bool]:
    name = " ".join(customer_name.strip().split())
    key = _customer_key(name)
    existing = db.execute(
        text("SELECT id FROM drink_tabs WHERE customer_key=:key AND status='OPEN' ORDER BY id DESC LIMIT 1"),
        {"key": key},
    ).scalar_one_or_none()
    if existing is not None:
        return tab_snapshot(db, int(existing)), False
    result = db.execute(
        text("""
            INSERT INTO drink_tabs (business_date, customer_name, customer_key, status, opened_by_user_id, opened_at)
            VALUES (:business_date, :customer_name, :customer_key, 'OPEN', :user_id, :opened_at)
        """),
        {"business_date": current_business_date(), "customer_name": name, "customer_key": key, "user_id": user_id, "opened_at": _iso()},
    )
    tab_id = int(result.lastrowid)
    db.commit()
    return tab_snapshot(db, tab_id), True


def add_item(db: Session, tab_id: int, product_id: int, quantity: int, user_id: int) -> dict:
    tab = _tab_row(db, tab_id)
    if not tab:
        raise HTTPException(404, "Drink customer tab not found")
    if tab["status"] != "OPEN":
        raise HTTPException(409, "Drink customer tab is already paid")

    # The Products page is the single source of truth for item name and price.
    # The browser never supplies a price, so a cashier cannot accidentally type
    # a different price in the drinks page.
    product = db.execute(
        text("SELECT id, name, price_piasters, is_active FROM products WHERE id=:id"),
        {"id": int(product_id)},
    ).mappings().first()
    if not product:
        raise HTTPException(404, "Product not found")
    if not bool(product["is_active"]):
        raise HTTPException(409, "Product is disabled")

    result = db.execute(
        text("""
            INSERT INTO drink_items
                (tab_id, product_id, drink_name, unit_price_piasters, quantity, added_by_user_id, added_at)
            VALUES
                (:tab_id, :product_id, :drink_name, :price, :quantity, :user_id, :added_at)
        """),
        {
            "tab_id": tab_id,
            "product_id": int(product["id"]),
            "drink_name": str(product["name"]),
            "price": int(product["price_piasters"]),
            "quantity": int(quantity),
            "user_id": user_id,
            "added_at": _iso(),
        },
    )
    item_id = int(result.lastrowid)
    db.commit()
    return {"item_id": item_id, "tab": tab_snapshot(db, tab_id)}


def delete_item(db: Session, tab_id: int, item_id: int) -> dict:
    tab = _tab_row(db, tab_id)
    if not tab:
        raise HTTPException(404, "Drink customer tab not found")
    if tab["status"] != "OPEN":
        raise HTTPException(409, "Paid drink invoice cannot be edited")
    result = db.execute(text("DELETE FROM drink_items WHERE id=:item_id AND tab_id=:tab_id"), {"item_id": item_id, "tab_id": tab_id})
    if result.rowcount != 1:
        raise HTTPException(404, "Drink item not found")
    db.commit()
    return tab_snapshot(db, tab_id)


def checkout_tab(db: Session, tab_id: int, payment_method: str, user_id: int, shift_id: int | None = None) -> dict:
    tab = _tab_row(db, tab_id)
    if not tab:
        raise HTTPException(404, "Drink customer tab not found")
    if tab["status"] != "OPEN":
        raise HTTPException(409, "Drink customer tab is already paid")
    items = _item_rows(db, tab_id)
    if not items:
        raise HTTPException(409, "Cannot checkout an empty drink tab")
    total = sum(int(x["line_total_piasters"] or 0) for x in items)
    business_date = str(tab["business_date"])
    seq = int(db.execute(
        text("SELECT COUNT(*) FROM drink_tabs WHERE business_date=:d AND status='PAID'"), {"d": business_date}
    ).scalar_one() or 0) + 1
    invoice = f"DRK-{business_date.replace('-', '')}-{seq:03d}"
    if db.execute(text("SELECT 1 FROM drink_tabs WHERE invoice_number=:n"), {"n": invoice}).first():
        invoice = f"DRK-{business_date.replace('-', '')}-{tab_id:04d}"
    db.execute(
        text("""
            UPDATE drink_tabs SET status='PAID', invoice_number=:invoice, payment_method=:method, shift_id=:shift_id,
                total_piasters=:total, closed_by_user_id=:user_id, closed_at=:closed_at
            WHERE id=:id AND status='OPEN'
        """),
        {"invoice": invoice, "method": payment_method, "shift_id": shift_id, "total": total, "user_id": user_id, "closed_at": _iso(), "id": tab_id},
    )
    db.commit()
    return tab_snapshot(db, tab_id)


def today_overview(db: Session) -> dict:
    today = current_business_date()
    open_ids = db.execute(text("SELECT id FROM drink_tabs WHERE status='OPEN' ORDER BY opened_at, id")).scalars().all()
    paid_ids = db.execute(
        text("SELECT id FROM drink_tabs WHERE status='PAID' AND business_date=:d ORDER BY closed_at DESC, id DESC"), {"d": today}
    ).scalars().all()
    open_tabs = [tab_snapshot(db, int(x)) for x in open_ids]
    paid_tabs = [tab_snapshot(db, int(x)) for x in paid_ids]
    return {
        "business_date": today,
        "open_tabs": open_tabs,
        "paid_tabs": paid_tabs,
        "summary": {
            "open_customers": len(open_tabs),
            "open_balance_piasters": sum(int(x["total_piasters"]) for x in open_tabs),
            "paid_customers_today": len(paid_tabs),
            "collected_today_piasters": sum(int(x["total_piasters"]) for x in paid_tabs),
        },
    }
