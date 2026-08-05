# ShopEase Ecommerce — Dummy Project for QA Copilot

Sample inputs for creating a **new project** in QA Copilot (user workflow — not a built-in demo button).

## Project identity

| Field | Value |
|-------|--------|
| Suggested project name | **ShopEase Ecommerce Portal** |
| Root feature | **ShopEase Ecommerce** |
| Catalog | Classic Tee, Wireless Earbuds, Desk Lamp, Canvas Tote |

## Features covered

1. Sign in — self registration + Google OAuth (+ email/password, session, log out)
2. Product selection
3. 4 products with prices and GST rates
4. Add to cart / remove from cart / update quantity
5. Checkout
6. Apply discount (SAVE10, FLAT100; no stacking)
7. Billing form + payment methods (card, UPI, COD)
8. Log out
9. Correct bill amount — merchandise − discount + **GST** + **delivery**

## Files in this package

| File | Copilot use |
|------|-------------|
| `ecommerce_flow.json` | **System Flow → Import JSON** (simple nested import) |
| `ecommerce_flow_typed.json` | Richer typed import (preferred; failure paths + criticality) |
| `ecommerce_natural_language.txt` | **Natural language → graph** paste source |
| `ecommerce_requirements.md` | **Knowledge Base** — core PRD |
| `billing_and_pricing_rules.md` | **Knowledge Base** — GST, delivery, worked examples |
| `payment_and_security.md` | **Knowledge Base** — payments, timeout, logout |
| `qa_acceptance_criteria.md` | **Knowledge Base** — AC IDs for retrieval |
| `seed_tests.json` | Reference partial tests (happy paths only) |
| `seed_bugs.json` | Reference historical bugs |
| `copilot_queries.md` | Suggested Copilot prompts |

## How to load (create new project)

1. Click **New** / **Create project**.
2. Name: `ShopEase Ecommerce Portal`
3. Root feature: `ShopEase Ecommerce`
4. Open **System Flow**:
   - Prefer **Import JSON** with `ecommerce_flow_typed.json`, **or**
   - Paste `ecommerce_natural_language.txt` into **Natural language → graph** and extract.
5. Open **Knowledge Base** and ingest each markdown file (paste text + matching filename):
   - `ecommerce_requirements.md`
   - `billing_and_pricing_rules.md`
   - `payment_and_security.md`
   - `qa_acceptance_criteria.md`
6. Open **QA Copilot** and run a query from `copilot_queries.md`.

## Bill amount quick reference

```
payable = (subtotal − discount) + GST(per-line on discounted amounts) + delivery
delivery = 49 if taxable merchandise < 999 else 0
GST is not applied on delivery
```

See `billing_and_pricing_rules.md` for worked examples the Copilot can retrieve.
