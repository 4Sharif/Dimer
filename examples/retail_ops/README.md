# retail_ops

Multi-table retail example for harder Dimer testing.

## Files

- `customers.csv` — customer dimension (region, segment)
- `products.csv` — product dimension (category, list price)
- `orders.csv` — fact table (order date, revenue, status, channel)
- `products_catalog_export.csv` — alternate product extract (schema/type drift on purpose)
- `march_revenue_exploration.ipynb` — partial notebook with direction changes

## Suggested focus

Run Dimer with this folder as the workspace focus, not a single CSV.
