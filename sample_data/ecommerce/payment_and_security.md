# ShopEase — Payment, Security & Session Rules

## Payment Methods

### Credit / Debit Card
- Processed via third-party payment gateway (external dependency).
- Card PAN/CVV never stored on ShopEase application servers.
- Successful authorization required before Order Confirmation.
- Payment Decline: show decline reason category (insufficient funds / bank decline / invalid card) without leaking gateway internals; retain cart.

### UPI
- External UPI intent / collect flow.
- User must complete payment within 10 minutes or the pending payment expires.
- On expiry, treat similarly to Payment Gateway Timeout (no charge, cart retained).

### Cash on Delivery (COD)
- Allowed only when payable total ≤ INR 5000.
- If user selects COD above threshold, block Place Order with message to choose another method or reduce cart.
- COD orders still require valid Billing Form and inventory reservation.

### Payment Gateway Timeout (critical)
- Must not create a confirmed paid order without confirmed capture/authorization.
- Must not leave the customer charged without an order ID.
- Idempotent retry using the same client request ID must not double-charge.
- User messaging: “Payment could not be confirmed. If money was deducted, it will be reversed in 3–5 business days. Your cart is saved.”

### Payment Decline
- Order not placed.
- Inventory reservation released.
- User may change payment method and retry.

---

## Inventory reservation
- Soft-reserve on Place Order start; hard-commit on payment success (or immediately for COD).
- Inventory Reservation Failure is a critical path: fail closed, restore cart quantities, list unavailable SKUs.

---

## Session & logout security
- Log Out invalidates server-side session immediately.
- Protected routes (order history, saved addresses) require authentication.
- Guest checkout is **not** in v1; user must Sign In (or Self Registration / Google OAuth) before Place Order.
- After Log Out, deep-linking to Checkout must redirect to Sign In and must not expose prior user’s billing form data.

---

## Historical risk notes (for QA)
- Double charge on payment retry after gateway timeout.
- GST recomputed incorrectly after promo remove.
- COD allowed above INR 5000 due to client-only validation.
- Google OAuth provider failure still created a partial session.
