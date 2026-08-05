# ShopEase Ecommerce — Product Requirements

## Overview
ShopEase is a simple ecommerce website for browsing a small catalog, managing a cart, applying discounts, completing checkout with billing and payment, and signing in or out.

Supported capabilities:
1. Sign in via self registration and Google OAuth (also email/password)
2. Product selection from a 4-SKU catalog
3. Add to cart / remove from cart / update quantity
4. Checkout
5. Apply discount codes
6. Billing form and payment methods
7. Log out
8. Correct bill amount generation including GST and delivery charges

---

## Sign In

### Self Registration
- New users register with email, password, full name, and phone.
- Email verification is mandatory before the first login with credentials.
- Duplicate email addresses must be rejected with a clear error (no account enumeration beyond “email already registered”).
- After verification, Profile Creation stores name, phone, and default shipping preference.

### Google OAuth
- Users may sign in with Google.
- Consent must be explicit; OAuth callback `state` must be validated (CSRF protection).
- Provider failures must show a recoverable error and must not create a ShopEase session.
- If a Google identity matches an existing verified email, Account Linking may attach the OAuth identity to that account after user confirmation.

### Email Password Login
- Valid credentials create an authenticated session.
- Invalid password returns a generic authentication error.
- After 5 consecutive invalid passwords, Account Lockout soft-locks the account for 30 minutes.

### Session Creation
- Session cookies must be Secure, HttpOnly, SameSite=Lax.
- Session TTL: 7 days idle timeout for web; logout immediately invalidates the server session.

### Log Out
- Log out clears the session.
- Authenticated cart remains associated with the user account.
- Guest cart in browser storage is not restored into another user’s session after logout.

---

## Product Catalog

### Browse Products
- Catalog lists all active SKUs with name, price (ex-GST), GST rate badge, and stock status.

### Product Selection
- User selects a product and quantity (default 1, min 1, max available stock).
- Out of Stock products show “Unavailable” and disable Add to Cart.

### Active products (v1 catalog)

| SKU     | Name             | Base price (INR, ex-GST) | GST rate | Initial stock |
|---------|------------------|--------------------------|----------|---------------|
| TEE-001 | Classic Tee      | 799                      | 5%       | 50            |
| AUD-014 | Wireless Earbuds | 2499                     | 18%      | 25            |
| HOM-220 | Desk Lamp        | 1299                     | 12%      | 40            |
| ACC-088 | Canvas Tote      | 499                      | 5%       | 100           |

---

## Shopping Cart

### Add to Cart
- Authenticated and guest users may add items.
- Adding the same SKU increments quantity (capped by stock).
- Success feedback must show updated cart count.

### Remove from Cart
- Removing a line item deletes it entirely.
- Cart total and bill preview must recalculate immediately.

### Update Quantity
- Quantity Below Minimum (< 1) is rejected; treat as remove or show validation error.
- Quantity Above Stock is rejected with remaining stock message.

### Empty Cart
- Checkout CTA is disabled when the cart has zero line items.
- Empty cart page offers a link back to Product Catalog.

---

## Checkout

### Review Cart
- Shows line items: name, qty, unit price (ex-GST), line GST, line total (incl. GST).
- Shows merchandise subtotal (ex-GST), discount, GST total, delivery, payable total.

### Apply Discount
See `billing_and_pricing_rules.md` for formulas. Supported codes:
- **SAVE10** — 10% off merchandise subtotal (ex-GST), before GST.
- **FLAT100** — flat INR 100 off merchandise subtotal; requires merchandise subtotal ≥ INR 500.
- Expired / invalid codes are rejected.
- **Promo stacking is rejected** — only one promo per order.
- User may Remove Discount and re-apply another code.

### Billing Form
- Required: full name, address line 1, city, state, PIN (6 digits), phone (+91 / 10-digit Indian mobile).
- Invalid Billing Fields block Place Order.
- Optional: “Delivery address same as billing”.

### Payment Methods
- **Credit / Debit Card** — via payment gateway; PCI data never stored on ShopEase servers.
- **UPI** — external UPI collect / intent flow.
- **Cash on Delivery** — allowed only when payable total ≤ INR 5000.
- Payment Decline: order not placed; cart retained; user may retry.
- Payment Gateway Timeout: critical failure — must not double-charge; order remains pending/cancelled with clear messaging.

### Place Order & Order Confirmation
- Place Order is enabled only when cart non-empty, billing valid, payment method selected, and totals match Bill Amount Generation rules.
- On success: Order Confirmation shows order ID, item summary, and payable total.
- Inventory Reservation Failure: stock insufficient at commit time — fail order, restore cart, show which SKUs failed.

---

## Security & Non-functionals
- Rate-limit login and promo validation endpoints.
- Idempotent Place Order keyed by client request ID to prevent duplicate orders on retry.
- All monetary amounts displayed and stored in INR with 2 decimal places.
