import uuid

from . import db

PRODUCTS = {
    "credits_30": {
        "id": "credits_30", "name": "30 次次数包", "price_cent": 990,
        "credits": 30, "plan": None, "days": 0, "note": "不过期，适合低频",
    },
    "credits_300": {
        "id": "credits_300", "name": "托管月卡", "price_cent": 3900,
        "credits": 300, "plan": None, "days": 0, "note": "300 次 AI 提取，怕麻烦选这个",
    },
    "credits_3600": {
        "id": "credits_3600", "name": "托管年卡", "price_cent": 39900,
        "credits": 3600, "plan": None, "days": 0, "note": "3600 次，折合 0.11 元/次",
    },
    "byok_month": {
        "id": "byok_month", "name": "BYOK 月卡", "price_cent": 1900,
        "credits": 0, "plan": "pro", "days": 30, "note": "自带 Key，不限 AI 次数",
    },
    "byok_year": {
        "id": "byok_year", "name": "BYOK 年卡", "price_cent": 12800,
        "credits": 0, "plan": "pro", "days": 365, "note": "主推，折合 10.6 元/月",
    },
    "team_month": {
        "id": "team_month", "name": "团队版", "price_cent": 9900,
        "credits": 0, "plan": "team", "days": 30, "note": "5 人共享素材库",
    },
}


class BillingError(ValueError):
    pass


def product_list() -> list[dict]:
    out = []
    for p in PRODUCTS.values():
        item = dict(p)
        item["price_yuan"] = "%.2f" % (p["price_cent"] / 100)
        out.append(item)
    return out


def get_product(product_id: str) -> dict:
    p = PRODUCTS.get(product_id)
    if not p:
        raise BillingError("PRODUCT_NOT_FOUND")
    return p


def new_order_id() -> str:
    return "ord_" + uuid.uuid4().hex[:20]


def create_order(user_id: str, product_id: str) -> dict:
    p = get_product(product_id)
    order = db.create_order(new_order_id(), user_id, product_id, p["price_cent"])
    return {**order, "product": p}


def fulfill_order(order_id: str, channel: str, txn: str = "") -> dict:
    order = db.get_order(order_id)
    if not order:
        raise BillingError("ORDER_NOT_FOUND")
    if order["status"] == "paid":
        return order
    product = get_product(order["product_id"])
    if not db.mark_order_paid(order_id, channel, txn):
        return db.get_order(order_id) or order
    if product["credits"]:
        db.add_credits(order["user_id"], int(product["credits"]), "order:" + order_id)
    if product["plan"] and product["days"]:
        db.set_plan_until(order["user_id"], product["plan"], int(product["days"]))
    if int(order.get("amount_cent") or 0) > 0:
        db.reward_inviter(order["user_id"], 7)
    return db.get_order(order_id) or order


def redeem(user_id: str, code: str) -> dict:
    product_id = db.redeem_code(code, user_id)
    p = get_product(product_id)
    order = db.create_order(new_order_id(), user_id, product_id, 0)
    db.mark_order_paid(order["id"], "redeem", (code or "").strip().upper())
    if p["credits"]:
        db.add_credits(user_id, int(p["credits"]), "redeem:" + order["id"])
    if p["plan"] and p["days"]:
        db.set_plan_until(user_id, p["plan"], int(p["days"]))
    return {"order": db.get_order(order["id"]), "product": p}
