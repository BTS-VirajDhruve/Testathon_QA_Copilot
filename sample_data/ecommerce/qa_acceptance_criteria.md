# ShopEase — QA Notes & Acceptance Criteria

## Acceptance highlights for Copilot / test design

### Auth
- AC-AUTH-01: Self registration requires email verification before credential login.
- AC-AUTH-02: Google OAuth provider failure never creates a session.
- AC-AUTH-03: Five invalid passwords trigger Account Lockout for 30 minutes.
- AC-AUTH-04: Log Out clears session; Checkout redirects to Sign In.

### Catalog & cart
- AC-CAT-01: Exactly four active products listed with correct base prices and GST badges.
- AC-CART-01: Add to Cart increments quantity for same SKU up to stock.
- AC-CART-02: Remove from Cart recalculates Review Cart totals.
- AC-CART-03: Empty Cart disables Checkout.

### Discounts
- AC-DISC-01: SAVE10 applies 10% on merchandise subtotal only.
- AC-DISC-02: FLAT100 requires merchandise subtotal ≥ 500.
- AC-DISC-03: Two promos cannot stack; second application rejected.
- AC-DISC-04: Expired promo leaves totals unchanged.

### Billing & payment
- AC-BILL-01: Invalid PIN or phone blocks Place Order.
- AC-PAY-01: COD rejected when payable_total > 5000.
- AC-PAY-02: Payment Gateway Timeout does not confirm order or double-charge.
- AC-PAY-03: Payment Decline retains cart for retry.

### Bill amount generation (critical)
- AC-AMT-01: Payable total matches formula in billing_and_pricing_rules.md for mixed GST carts.
- AC-AMT-02: Delivery = 49 when taxable merchandise < 999; else 0.
- AC-AMT-03: No GST on delivery charges.
- AC-AMT-04: After Remove Discount, GST and delivery recomputed correctly.

### Order
- AC-ORD-01: Order Confirmation shows order ID and payable total matching Review Cart.
- AC-ORD-02: Inventory Reservation Failure restores cart and lists failing SKUs.
