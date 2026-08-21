"""Generate realistic Dimer example testbeds (run once; commit outputs)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
RNG = np.random.default_rng(42)


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def _write_dimerignore(folder: Path) -> None:
    (folder / ".dimerignore").write_text(
        "# Keep agent focus on data assets in this example workspace\n"
        "README.md\n"
        "_generate_*.py\n"
        ".DS_Store\n",
        encoding="utf-8",
    )


def build_retail_ops() -> Path:
    folder = ROOT / "retail_ops"
    folder.mkdir(parents=True, exist_ok=True)

    regions = ["North", "South", "East", "West"]
    segments = ["SMB", "Mid-Market", "Enterprise"]
    categories = {
        "SUB-BASIC": ("Subscription", 49.0),
        "SUB-PRO": ("Subscription", 129.0),
        "HW-SENSOR": ("Hardware", 220.0),
        "HW-GATEWAY": ("Hardware", 480.0),
        "SVC-IMPL": ("Services", 900.0),
        "SVC-TRAIN": ("Services", 650.0),
        "SUB-ENTERPRISE": ("Subscription", 399.0),
        "HW-BUNDLE": ("Hardware", 750.0),
        "SVC-RETAINER": ("Services", 1200.0),
        "SUB-ADDON": ("Subscription", 29.0),
        "HW-CABLE": ("Hardware", 35.0),
        "SVC-AUDIT": ("Services", 1500.0),
    }

    products = pd.DataFrame(
        [
            {
                "product_id": pid,
                "product_name": pid.replace("-", " ").title(),
                "category": cat,
                "list_price": price,
            }
            for pid, (cat, price) in categories.items()
        ]
    )

    customers = []
    for i in range(1, 281):
        region = regions[(i - 1) % 4]
        # West over-indexes Enterprise to make West subscription cuts matter
        if region == "West":
            segment = RNG.choice(segments, p=[0.25, 0.30, 0.45])
        else:
            segment = RNG.choice(segments, p=[0.45, 0.35, 0.20])
        customers.append(
            {
                "customer_id": f"C{i:04d}",
                "customer_name": f"Customer {i:04d}",
                "region": region,
                "segment": segment,
                "signup_date": pd.Timestamp("2022-01-01") + pd.Timedelta(days=int(RNG.integers(0, 700))),
                "account_owner": RNG.choice(["Alex", "Blake", "Casey", "Drew", "Eden"]),
            }
        )
    customers_df = pd.DataFrame(customers)

    # Build daily order volume Jan-Jun 2024 with planted March West Subscription shock
    rows = []
    order_id = 10000
    start = pd.Timestamp("2024-01-01")
    end = pd.Timestamp("2024-06-30")
    days = pd.date_range(start, end, freq="D")

    for day in days:
        month = day.month
        base = 8 if day.weekday() < 5 else 4
        # mild seasonality
        if month in (2, 4, 5):
            base += 2
        for _ in range(int(base + RNG.integers(0, 3))):
            cust = customers_df.sample(1, random_state=int(RNG.integers(0, 1_000_000))).iloc[0]
            product = products.sample(1, random_state=int(RNG.integers(0, 1_000_000))).iloc[0]
            qty = int(RNG.integers(1, 6))
            # discount noise
            revenue = float(product["list_price"] * qty * float(RNG.uniform(0.85, 1.05)))

            # Planted driver: March West Subscription volume and AOV collapse
            if month == 3 and cust["region"] == "West" and product["category"] == "Subscription":
                if RNG.random() < 0.55:
                    continue  # dropped demand
                qty = 1
                revenue = float(product["list_price"] * 0.55)  # heavy discounting

            # Mild growth elsewhere in March so "why drop" requires segmentation
            if month == 3 and cust["region"] != "West" and product["category"] == "Hardware":
                qty += 1
                revenue = float(product["list_price"] * qty)

            status = "completed"
            if RNG.random() < 0.03:
                status = "refunded"
                revenue = -abs(revenue) * float(RNG.uniform(0.4, 1.0))

            rows.append(
                {
                    "order_id": f"O{order_id}",
                    "order_date": day.strftime("%Y-%m-%d"),
                    "customer_id": cust["customer_id"],
                    "product_id": product["product_id"],
                    "quantity": qty,
                    "revenue": round(revenue, 2),
                    "status": status,
                    "channel": RNG.choice(["web", "sales_assisted", "partner"], p=[0.55, 0.30, 0.15]),
                }
            )
            order_id += 1

    orders = pd.DataFrame(rows)

    # Data-quality landmines
    # 1) missing revenue on a few completed rows
    miss_idx = orders.index[(orders["status"] == "completed")].to_numpy()
    for idx in RNG.choice(miss_idx, size=18, replace=False):
        orders.loc[idx, "revenue"] = np.nan

    # 2) orphan customer_id (join break)
    orphan_idx = int(RNG.choice(orders.index.to_numpy(), size=1)[0])
    orders.loc[orphan_idx, "customer_id"] = "C9999"

    # 3) unknown product_id
    bad_prod_idx = int(RNG.choice(orders.index.to_numpy(), size=1)[0])
    orders.loc[bad_prod_idx, "product_id"] = "SUB-UNKNOWN"

    # 4) duplicate order_id (same id, different line) — grain caveat
    dup_src = orders.iloc[100].copy()
    dup_src["product_id"] = "HW-CABLE"
    dup_src["quantity"] = 2
    dup_src["revenue"] = 70.0
    orders = pd.concat([orders, pd.DataFrame([dup_src])], ignore_index=True)

    # 5) alternate products extract with dtype drift for multi-dataset checks
    products_v2 = products.copy()
    products_v2["list_price"] = products_v2["list_price"].astype(str)  # type drift
    products_v2 = products_v2.rename(columns={"category": "product_category"})

    _write_csv(customers_df, folder / "customers.csv")
    _write_csv(products, folder / "products.csv")
    _write_csv(orders, folder / "orders.csv")
    _write_csv(products_v2, folder / "products_catalog_export.csv")

    # Notebook with direction change + out-of-order execution hint
    nb = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}
        },
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "# Retail ops exploration\n",
                    "\n",
                    "First pass on order revenue. Stakeholders asked about March performance.",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": 1,
                "metadata": {},
                "outputs": [
                    {
                        "output_type": "stream",
                        "name": "stdout",
                        "text": [f"orders={len(orders)}\n"],
                    }
                ],
                "source": [
                    "import pandas as pd\n",
                    "orders = pd.read_csv('orders.csv', parse_dates=['order_date'])\n",
                    "customers = pd.read_csv('customers.csv')\n",
                    "products = pd.read_csv('products.csv')\n",
                    "print(f'orders={len(orders)}')",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": 3,
                "metadata": {},
                "outputs": [
                    {
                        "output_type": "execute_result",
                        "metadata": {},
                        "execution_count": 3,
                        "data": {"text/plain": ["# monthly totals recomputed after join"]},
                    }
                ],
                "source": [
                    "orders['month'] = orders['order_date'].dt.to_period('M').astype(str)\n",
                    "monthly = orders.groupby('month')['revenue'].sum()\n",
                    "monthly",
                ],
            },
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "## Changed direction\n",
                    "\n",
                    "Monthly totals alone are ambiguous. Switching to region × category after joining customers/products.",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": 2,
                "metadata": {},
                "outputs": [
                    {
                        "output_type": "stream",
                        "name": "stdout",
                        "text": ["joined preview ready\n"],
                    }
                ],
                "source": [
                    "df = orders.merge(customers, on='customer_id', how='left').merge(products, on='product_id', how='left')\n",
                    "print('joined preview ready')\n",
                    "df.head()",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": 4,
                "metadata": {},
                "outputs": [
                    {
                        "output_type": "error",
                        "ename": "KeyError",
                        "evalue": "'region'",
                        "traceback": [
                            "KeyError: 'region'  # ran before join cell in an earlier session"
                        ],
                    }
                ],
                "source": [
                    "# Intentionally fragile: assumes join already happened\n",
                    "df[df['month'] == '2024-03'].groupby(['region', 'category'])['revenue'].sum()",
                ],
            },
        ],
    }
    (folder / "march_revenue_exploration.ipynb").write_text(json.dumps(nb, indent=1), encoding="utf-8")

    (folder / "README.md").write_text(
        """# retail_ops

Multi-table retail example for harder Dimer testing.

## Files

- `customers.csv` — customer dimension (region, segment)
- `products.csv` — product dimension (category, list price)
- `orders.csv` — fact table (order date, revenue, status, channel)
- `products_catalog_export.csv` — alternate product extract (schema/type drift on purpose)
- `march_revenue_exploration.ipynb` — partial notebook with direction changes

## Suggested focus

Run Dimer with this folder as the workspace focus, not a single CSV.
""",
        encoding="utf-8",
    )
    _write_dimerignore(folder)
    return folder


def build_saas_churn() -> Path:
    folder = ROOT / "saas_churn"
    folder.mkdir(parents=True, exist_ok=True)

    plans = ["Starter", "Pro", "Enterprise"]
    regions = ["NA", "EU", "APAC"]
    accounts = []
    for i in range(1, 1201):
        plan = RNG.choice(plans, p=[0.45, 0.40, 0.15])
        region = RNG.choice(regions, p=[0.5, 0.3, 0.2])
        seats = int(RNG.integers(1, 80 if plan != "Enterprise" else 250))
        # latent risk factors
        usage_slope = float(RNG.normal(-0.8 if plan == "Starter" else -0.2, 0.7))
        ticket_pressure = float(RNG.gamma(2.0, 1.2))
        # churn probability from latent factors (not from leaky columns)
        logit = -1.2 + (-0.9 * usage_slope) + (0.35 * ticket_pressure) + (0.4 if plan == "Starter" else -0.5 if plan == "Enterprise" else 0.0)
        prob = 1 / (1 + np.exp(-logit))
        churned = int(RNG.random() < prob)
        mrr = { "Starter": 39, "Pro": 119, "Enterprise": 499 }[plan] * max(1, seats // 5)
        accounts.append(
            {
                "account_id": f"A{i:04d}",
                "account_name": f"Acme Tenant {i:04d}",
                "plan": plan,
                "region": region,
                "seats": seats,
                "mrr": float(mrr),
                "contract_start": (pd.Timestamp("2023-01-01") + pd.Timedelta(days=int(RNG.integers(0, 500)))).strftime("%Y-%m-%d"),
                "churned": churned,
                # LEAKY columns — should trigger warnings / be excluded for honest ML
                "churn_reason_code": RNG.choice(["none", "price", "competitor", "low_usage", "support"]) if churned else "none",
                "days_to_observed_churn": int(RNG.integers(5, 120)) if churned else -1,
            }
        )
    accounts_df = pd.DataFrame(accounts)

    # monthly usage Jan-Jun 2024
    usage_rows = []
    months = pd.period_range("2024-01", "2024-06", freq="M")
    for _, acct in accounts_df.iterrows():
        base = float(RNG.uniform(40, 400))
        slope = -18 if acct["churned"] else float(RNG.uniform(-2, 8))
        for i, month in enumerate(months):
            active_users = max(1, int(base + slope * i + RNG.normal(0, 12)))
            events = int(active_users * float(RNG.uniform(8, 25)))
            usage_rows.append(
                {
                    "account_id": acct["account_id"],
                    "month": str(month),
                    "active_users": active_users,
                    "events": events,
                    "feature_adoption_score": round(float(np.clip(RNG.normal(0.55 if not acct["churned"] else 0.35, 0.15), 0, 1)), 3),
                }
            )
    usage_df = pd.DataFrame(usage_rows)

    # support tickets
    ticket_rows = []
    tid = 1
    for _, acct in accounts_df.iterrows():
        n_tickets = int(RNG.poisson(5 if acct["churned"] else 2))
        for _ in range(n_tickets):
            priority = RNG.choice(["P3", "P2", "P1"], p=[0.55, 0.30, 0.15] if not acct["churned"] else [0.25, 0.35, 0.40])
            created = pd.Timestamp("2024-01-01") + pd.Timedelta(days=int(RNG.integers(0, 180)))
            resolved = float(RNG.uniform(1, 72))
            if RNG.random() < 0.08:
                resolved = np.nan  # missingness
            ticket_rows.append(
                {
                    "ticket_id": f"T{tid:05d}",
                    "account_id": acct["account_id"],
                    "created_at": created.strftime("%Y-%m-%d"),
                    "priority": priority,
                    "category": RNG.choice(["billing", "bug", "how_to", "outage", "access"]),
                    "resolved_hours": None if pd.isna(resolved) else round(resolved, 1),
                }
            )
            tid += 1
    tickets_df = pd.DataFrame(ticket_rows)

    # DQ landmines
    # plan typo / inconsistent label
    typo_idx = accounts_df.sample(12, random_state=7).index
    accounts_df.loc[typo_idx, "plan"] = "Proo"
    # negative seats
    accounts_df.loc[accounts_df.sample(3, random_state=9).index, "seats"] = -2
    # orphan tickets
    if len(tickets_df):
        tickets_df.loc[tickets_df.sample(5, random_state=3).index, "account_id"] = "A9999"

    _write_csv(accounts_df, folder / "accounts.csv")
    _write_csv(usage_df, folder / "usage_monthly.csv")
    _write_csv(tickets_df, folder / "support_tickets.csv")

    (folder / "README.md").write_text(
        """# saas_churn

Multi-table SaaS example for join-heavy analysis and data-quality testing.

## Files

- `accounts.csv` — account dimension + churn label
- `usage_monthly.csv` — monthly product usage
- `support_tickets.csv` — support interactions

## Suggested focus

Use the folder as workspace focus. Compare churned and retained accounts across usage and support activity, and treat churn-reason fields as post-outcome data.
""",
        encoding="utf-8",
    )
    _write_dimerignore(folder)
    return folder


if __name__ == "__main__":
    retail = build_retail_ops()
    saas = build_saas_churn()
    print(f"wrote {retail}")
    print(f"wrote {saas}")
    for folder in (retail, saas):
        for p in sorted(folder.glob("*.csv")):
            df = pd.read_csv(p)
            print(f"  {p.name}: {len(df)} rows, {list(df.columns)}")
