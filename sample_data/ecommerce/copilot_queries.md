# ShopEase Ecommerce — Suggested Copilot Queries

Use these after creating the project, importing the system flow, and ingesting knowledge-base documents.

## Primary (coverage + targeted regen)

```
Analyze the ShopEase Ecommerce flow. Generate comprehensive tests focused on authentication, cart mutations, discount stacking, GST and delivery bill amount generation, payment failure paths, historical bugs, and uncovered branches. Then identify coverage gaps and generate targeted tests for the highest-risk gaps.
```

## Bill amount / GST focus

```
Generate negative and boundary tests for Bill Amount Generation including mixed GST rates, SAVE10 and FLAT100, free shipping threshold at INR 999, and Incorrect Total Display. Use the billing and pricing rules from the knowledge base.
```

## Payment risk

```
Run exploratory analysis on Payment Methods. Prioritize Payment Gateway Timeout, Payment Decline, COD eligibility above INR 5000, and impact of changes to Place Order.
```

## Auth + logout

```
Generate security tests for Sign In covering Self Registration, Google OAuth Provider Failure, Account Lockout, Session Creation, and Log Out session invalidation before Checkout.
```

## Impact analysis

```
What components are impacted if Bill Amount Generation or GST Calculation changes?
```

## Regression

```
Given a change to Apply Discount promo stacking rules, recommend regression tests across Checkout, Bill Amount Generation, and historical bugs BUG-ECOM-011 and BUG-ECOM-021.
```

## Coverage gaps only

```
Identify coverage gaps in ShopEase Ecommerce. Focus on critical failure paths: Payment Gateway Timeout, Inventory Reservation Failure, Promo Stacking Rejected, and Incorrect Total Display.
```
