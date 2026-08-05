# ShopEase — Billing & Pricing Rules (Knowledge Base)

## Purpose
Defines **correct bill amount generation**, including merchandise subtotal, discounts, **GST**, and **delivery charges**. These rules are critical for Checkout → Bill Amount Generation coverage.

## Formula (payable total)

```
merchandise_subtotal = Σ (unit_price_ex_gst × qty)     # per line, before discount
discount_amount      = f(promo, merchandise_subtotal)  # see promo rules
taxable_merchandise  = merchandise_subtotal − discount_amount
```

Discount is allocated **proportionally across lines** by pre-discount line share of merchandise_subtotal.

```
line_discount_i = discount_amount × (line_subtotal_i / merchandise_subtotal)
line_taxable_i  = line_subtotal_i − line_discount_i
line_gst_i      = round(line_taxable_i × gst_rate_i, 2)
gst_total       = Σ line_gst_i
```

```
if taxable_merchandise < 999:
    delivery_charges = 49.00
else:
    delivery_charges = 0.00
```

**GST is not applied on delivery charges.**

```
payable_total = taxable_merchandise + gst_total + delivery_charges
```

All intermediates and `payable_total` use banker’s rounding to 2 decimal places except where product rules specify half-up; **ShopEase v1 uses half-up to 2 decimals**.

---

## Worked example A — single item, no promo, paid delivery

- 1 × Classic Tee @ 799, GST 5%
- merchandise_subtotal = 799.00
- discount = 0
- taxable = 799.00
- GST = 799 × 0.05 = 39.95
- delivery = 49.00 (799 < 999)
- **payable_total = 799 + 39.95 + 49 = 887.95**

---

## Worked example B — SAVE10, free shipping threshold

- 1 × Wireless Earbuds @ 2499, GST 18%
- merchandise_subtotal = 2499.00
- SAVE10 → discount = 249.90
- taxable = 2249.10
- GST = 2249.10 × 0.18 = 404.84
- delivery = 0.00 (taxable ≥ 999)
- **payable_total = 2249.10 + 404.84 + 0 = 2653.94**

---

## Worked example C — multi-item, FLAT100, mixed GST

- 1 × Classic Tee @ 799 (5%) + 1 × Desk Lamp @ 1299 (12%)
- merchandise_subtotal = 2098.00
- FLAT100 → discount = 100.00 (min cart 500 satisfied)
- Tee share = 799/2098 → line_discount_tee = 38.08
- Lamp share = 1299/2098 → line_discount_lamp = 61.92
- Tee taxable = 760.92 → GST 5% = 38.05
- Lamp taxable = 1237.08 → GST 12% = 148.45
- gst_total = 186.50
- taxable_merchandise = 1998.00 → delivery = 0
- **payable_total = 1998.00 + 186.50 + 0 = 2184.50**

---

## Promo rules

| Code    | Rule                                                                 | Notes                          |
|---------|----------------------------------------------------------------------|--------------------------------|
| SAVE10  | 10% of merchandise_subtotal                                          | Before GST; not on delivery    |
| FLAT100 | INR 100 off merchandise_subtotal if merchandise_subtotal ≥ 500       | Reject if below min            |
| —       | Only **one** promo per order                                         | Stacking → Promo Stacking Rejected |
| —       | Expired / unknown codes → Expired Promo failure                      | Cart totals unchanged          |

Removing a discount recalculates GST and delivery from scratch.

---

## COD eligibility
Cash on Delivery allowed only when `payable_total ≤ 5000.00`.

## Incorrect Total Display (critical failure)
Any UI or API response where displayed payable total ≠ recomputed formula above is a **critical billing defect**. Regression tests must cover:
- Discount then remove discount
- Crossing free-shipping threshold by adding/removing items
- Mixed GST rates after proportional discount allocation
- Rounding on fractional GST (e.g. 5% of 799)
