"""Deterministic Olist-inspired commerce and independent ETL simulation."""
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .provider import ARCHITECTURE, Snapshot

SEED = 40006
START = date(2023, 1, 1)
AS_OF = date(2024, 8, 15)
CHANNELS = ["Organic Search", "Paid Search", "Direct", "Marketplace", "Social", "Email"]
DEVICES = ["Mobile", "Desktop", "Tablet"]
# Each tuple describes a demo metro and its relative demand.
METROS = [
    ("São Paulo", "SP", "Southeast", 23), ("Campinas", "SP", "Southeast", 7),
    ("Rio de Janeiro", "RJ", "Southeast", 13), ("Belo Horizonte", "MG", "Southeast", 9),
    ("Vitória", "ES", "Southeast", 3), ("Curitiba", "PR", "South", 7),
    ("Porto Alegre", "RS", "South", 7), ("Florianópolis", "SC", "South", 5),
    ("Salvador", "BA", "Northeast", 6), ("Recife", "PE", "Northeast", 5),
    ("Fortaleza", "CE", "Northeast", 5), ("Natal", "RN", "Northeast", 2),
    ("João Pessoa", "PB", "Northeast", 2), ("Maceió", "AL", "Northeast", 2),
    ("Aracaju", "SE", "Northeast", 2), ("Teresina", "PI", "Northeast", 2),
    ("São Luís", "MA", "Northeast", 2), ("Brasília", "DF", "Central-West", 5),
    ("Goiânia", "GO", "Central-West", 4), ("Cuiabá", "MT", "Central-West", 2),
    ("Campo Grande", "MS", "Central-West", 2), ("Manaus", "AM", "North", 3),
    ("Belém", "PA", "North", 3), ("Rio Branco", "AC", "North", 1),
    ("Porto Velho", "RO", "North", 1), ("Boa Vista", "RR", "North", 1),
    ("Palmas", "TO", "North", 1), ("Macapá", "AP", "North", 1),
]
CATALOG = {
    "Electronics": ("Consumer Electronics", [("Portable speaker", 219), ("Wireless earbuds", 169),
                                             ("Smartwatch", 389), ("Power bank", 99)]),
    "Home & Living": ("Home Office", [("Ergonomic desk chair", 849), ("Desk lamp", 129),
                                      ("Laptop stand", 109), ("Desk organizer", 59)]),
    "Apparel": ("Fashion & Accessories", [("Canvas tote", 89), ("Trail sneakers", 219),
                                          ("Cotton polo", 119), ("Travel backpack", 159)]),
    "Sports": ("Outdoor & Fitness", [("Yoga mat", 109), ("Resistance kit", 89),
                                     ("Insulated bottle", 79), ("Dumbbell set", 259)]),
    "Kitchen": ("Kitchen & Cookware", [("Air fryer", 479), ("Coffee press", 119),
                                       ("Ceramic cookware", 299), ("Storage set", 89)]),
    "Beauty": ("Beauty & Personal Care", [("Facial care kit", 139), ("Hair dryer", 189),
                                          ("Body care set", 79), ("Electric shaver", 229)]),
    "Home & Decor": ("Decor & Bedding", [("Cotton bedding", 229), ("Woven throw", 149),
                                         ("Ceramic vase", 79), ("Cushion set", 119)]),
}


def generate_snapshot(seed: int = SEED) -> Snapshot:
    commerce_seed, etl_seed = np.random.SeedSequence(seed).spawn(2)
    rng = np.random.default_rng(commerce_seed)
    days = pd.date_range(START, AS_OF)
    growth = np.linspace(0.70, 1.30, len(days))
    season = 1 + 0.17 * np.sin(np.arange(len(days)) * 2 * np.pi / 75)
    weekend = np.where(days.dayofweek >= 5, 1.35, 1)
    order_days = days.repeat(rng.poisson(28 * growth * season * weekend))
    n = len(order_days)
    order_ids = [f"CP-{number:06d}" for number in range(1, n + 1)]
    metro_weights = np.array([metro[3] for metro in METROS])
    customer_metro = rng.choice(len(METROS), 9500, p=metro_weights / metro_weights.sum())
    customers = rng.integers(0, len(customer_metro), n)
    metros = pd.DataFrame(METROS, columns=["city", "state", "region", "weight"])
    location = metros.iloc[customer_metro[customers]].reset_index(drop=True)
    hours = rng.choice(24, n, p=np.array([
        2, 2, 1, 1, 1, 2, 3, 4, 5, 5, 6, 6, 7, 7, 7, 6, 6, 7, 8, 9, 9, 8, 6, 4
    ]) / 122)
    order_at = order_days + pd.to_timedelta(hours, unit="h") + pd.to_timedelta(rng.integers(0, 60, n), unit="m")
    cancelled = rng.random(n) < 0.038
    handling = rng.integers(12, 54, n)
    estimate = rng.integers(88, 177, n) + np.where(location["region"].eq("North"), 37, 0)
    variance = np.round(rng.normal(-19, 30, n) + (rng.random(n) < 0.11) * 48).astype(int)
    duration = np.maximum(18, estimate + variance)
    dispatched = order_at + pd.to_timedelta(handling, unit="h")
    expected = dispatched + pd.to_timedelta(estimate, unit="h")
    delivered_at = dispatched + pd.to_timedelta(duration, unit="h")
    review_at = delivered_at + pd.to_timedelta(rng.integers(4, 60, n), unit="h")
    cutoff = pd.Timestamp(AS_OF) + timedelta(days=1)
    delivered = (delivered_at < cutoff) & ~cancelled
    reviewed = delivered & (review_at < cutoff) & (rng.random(n) < 0.84)
    scores = np.clip(np.rint(
        4.85 - np.maximum(0, duration - estimate) / 32 - np.maximum(0, duration - 90) / 205
        + rng.normal(0, 0.72, n)
    ), 1, 5)
    orders = location[["city", "state", "region"]].assign(
        order_id=order_ids,
        customer_id=[f"BR-{customer:05d}" for customer in customers],
        date=order_days,
        ordered_at=order_at,
        status=np.select([cancelled, delivered], ["Cancelled", "Delivered"], default="In progress"),
        channel=rng.choice(CHANNELS, n, p=[.24, .15, .22, .18, .14, .07]),
        device=rng.choice(DEVICES, n, p=[.62, .31, .07]),
        carrier=rng.choice(["Correios", "Jadlog", "Loggi", "Total Express"], n, p=[.40, .22, .23, .15]),
        payment_method=rng.choice(["Credit card", "Pix", "Boleto", "Debit card"], n, p=[.56, .26, .13, .05]),
        shipping_cents=np.where(cancelled, 0, rng.integers(990, 4390, n)),
        dispatched_at=dispatched.where((dispatched < cutoff) & ~cancelled),
        estimated_at=expected.where(~cancelled),
        delivered_at=delivered_at.where(delivered),
        reviewed_at=review_at.where(reviewed),
        review_score=np.where(reviewed, scores, np.nan),
    )
    orders["review_note"] = np.select(
        [~reviewed, scores <= 2, scores == 3, scores == 4],
        ["", "The delivery took longer than I expected.", "The item was fine, but the wait was inconvenient.",
         "The item arrived in good condition."], default="Everything arrived as expected."
    )

    products = pd.DataFrame([
        (department, category, product, price)
        for department, (category, variants) in CATALOG.items()
        for product, price in variants
    ], columns=["department", "category", "product", "price"])
    products["sku"] = [f"SKU-{number:03d}" for number in range(1, len(products) + 1)]
    counts = rng.choice([1, 2, 3], n, p=[.73, .24, .03])
    weights = np.tile([.37, .29, .20, .14], len(CATALOG)) * np.repeat([19, 14, 20, 14, 12, 11, 10], 4)
    lines = products.iloc[rng.choice(len(products), counts.sum(), p=weights / weights.sum())].reset_index(drop=True)
    lines["order_id"] = np.repeat(order_ids, counts)
    lines["item_id"] = np.arange(1, len(lines) + 1)
    lines["quantity"] = rng.choice([1, 2, 3], len(lines), p=[.88, .105, .015])
    lines["unit_price_cents"] = np.rint(lines.pop("price") * 100 * rng.uniform(.85, 1.10, len(lines))).astype(int)
    lines["revenue_cents"] = lines["unit_price_cents"] * lines["quantity"]
    orders["revenue_cents"] = orders["order_id"].map(lines.groupby("order_id")["revenue_cents"].sum())
    orders.loc[cancelled, "revenue_cents"] = 0
    orders["payment_cents"] = orders["revenue_cents"] + orders["shipping_cents"]

    traffic = orders.assign(sessions=rng.integers(24, 88, n), conversions=1).groupby(
        ["date", "channel", "device"], as_index=False
    )[["sessions", "conversions"]].sum()
    product_traffic = lines[["order_id", "sku"]].drop_duplicates().merge(
        orders[["order_id", "date"]], on="order_id"
    )
    product_traffic["sessions"] = rng.integers(25, 99, len(product_traffic))
    product_traffic["conversions"] = 1
    product_traffic = product_traffic.groupby(["date", "sku"], as_index=False)[["sessions", "conversions"]].sum()
    runs, stages = generate_telemetry(np.random.default_rng(etl_seed))
    return Snapshot(START, AS_OF, orders, lines, traffic, product_traffic, runs, stages)


def generate_telemetry(rng: np.random.Generator) -> tuple[pd.DataFrame, pd.DataFrame]:
    stamps = pd.date_range(end=pd.Timestamp(AS_OF) + timedelta(hours=20), periods=540, freq="4h")
    runs = []
    stages = []
    for index, stamp in enumerate(stamps):
        affected = int(rng.integers(0, len(ARCHITECTURE)))
        outcome = "Failed" if index % 19 == 0 else "Warning" if index % 8 == 0 else "Success"
        target = ["Orders", "Catalog", "Customers", "Payments", "Shipments", "Reviews"][index % 6]
        run_id = stamp.strftime("run_%Y%m%d_%H%M")
        diagnostic = "Validation and publication checks completed."
        if outcome == "Warning":
            diagnostic = f"{ARCHITECTURE[affected][0]}: recovered after a simulated retry."
        if outcome == "Failed":
            diagnostic = f"{ARCHITECTURE[affected][0]}: simulated retry limit exceeded. Run stopped."
        total_duration = 0
        for stage, (name, _, _) in enumerate(ARCHITECTURE):
            status = "Success"
            if outcome == "Failed" and stage > affected:
                status = "Skipped"
            elif stage == affected:
                status = outcome
            duration = 0 if status == "Skipped" else int(rng.integers(3, 38))
            total_duration += duration
            stages.append((run_id, name, status, duration))
        raw_committed = outcome != "Failed" or affected > 2
        rows = int(rng.integers(3500, 58500)) if raw_committed else 0
        runs.append((run_id, stamp, target, outcome, total_duration, rows, diagnostic))
    return (
        pd.DataFrame(runs, columns=[
            "run_id", "started_at", "target", "status", "duration_seconds", "rows", "diagnostic"
        ]),
        pd.DataFrame(stages, columns=["run_id", "stage", "status", "duration_seconds"]),
    )
