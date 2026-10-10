# Gaming Café MIS — Milestone 2: Booking, Wallet and Payments

**Status:** Draft for review · **Date:** 2026-10-11 · **Builds on:** `first_milestone.md`

## 1. Goal

Customers book gaming PCs on the café's website and pay from a prepaid wallet. Every booking, including walk-ins at the counter, goes through the website. Staff never create bookings; they top up wallets for cash payers and are alerted when a booking's time is up.

**Success looks like:**
- A customer signs in with Google, tops up through Razorpay, picks seats on a live seat map and is booked in under a minute on a phone.
- Two customers can never hold the same PC at the same time, and no wallet can be overspent.
- Staff see on the dashboard, within 10 s, when a booking ends.
- The site has a distinctive Cyberpunk 2077-style look, and every action is obvious.

## 2. Decisions

| Topic | Decision |
|---|---|
| Who books | Customers only, through the website. Walk-ins book on their own phone at the counter. No staff-created bookings. |
| Money in | Razorpay online top-up, and cash at the counter credited by staff in admin. |
| Wallet unit | Rupees, stored in paise. |
| Pricing | One hourly rate for all PCs, pro-rated by length. |
| Offers | Top-up packs ("pay ₹500, get ₹100 bonus"), created and switched on/off by admin at any time, with an optional expiry date. |
| Seat choice | Customer picks specific PCs on a seat grid. One booking can cover several PCs (friends need no accounts). |
| Times | Future bookings start on step boundaries (default 30 min, configurable to 15). "Start now" starts at the current minute. Length in steps, minimum 60 min. |
| Cancellation | Per PC, free until a cutoff (default 120 min) before start, refunded to the wallet only. No refund after the cutoff or for no-shows. |
| Session end | Booking end time triggers a "Time up" alert on the staff dashboard. Staff remove the customer by hand. PCs are never locked. |
| PC status | Matters only for "Start now": a PC that is In Use with no booking is not offered. Future slots ignore status. A paid booking holds its slot whatever the PC's status. |
| Sign-in | Customers: Google only. Staff: username and password. |
| Architecture | Extend the existing Django project with one new app, `booking`. |
| Look | Cyberpunk 2077 vibe: dark base, neon accents, bold type, smooth motion (section 8). |

## 3. Architecture

- One new Django app, **`booking`**, next to `status/`. It holds customers, wallet, offers, top-up orders and bookings. Same project, database and deploy as Milestone 1.
- **Google sign-in:** `django-allauth[socialaccount]` with only the Google provider enabled. Local password sign-up is disabled for customers.
- **Razorpay:** no SDK. Creating an order is one HTTPS call to the Orders API (Python `urllib`), and signatures are verified with `hmac` + `hashlib`.
- **Pages:** Django templates with plain JavaScript, as in Milestone 1. Animations use **Motion** (the vanilla-JavaScript library from the Framer Motion team), vendored as one static file — no npm, no build step. Page-to-page transitions use the browser's **View Transitions** API (progressive enhancement).
- **URLs** on `app.<domain>`:

| Path | Who | What |
|---|---|---|
| `/` | Public | Home: live seat map, rate, offers |
| `/book/` | Customer | Booking flow |
| `/me/bookings/` | Customer | My bookings: cancel, add time |
| `/me/wallet/` | Customer | Balance, top up, history |
| `/accounts/…` | Public | Google sign-in (allauth) |
| `/payments/razorpay/webhook` | Razorpay | Signed webhook, CSRF-exempt |
| `/terms/`, `/privacy/`, `/refunds/`, `/contact/` | Public | Policy pages |
| `/staff/` | Staff | Status dashboard (moved from `/`) |
| `/staff/login/` | Staff | Staff login (moved from `/accounts/login/`) |
| `/admin/` | Staff | Django admin |
| `/api/v1/heartbeat`, `/healthz` | Agents, monitor | Unchanged |

## 4. Data model

**`CafeSettings`** (existing single row) gains:

| Field | Default |
|---|---|
| `hourly_rate_paise` | 10000 (₹100) |
| `booking_step_min` | 30 (choices: 15, 30) |
| `min_booking_min` | 60 |
| `cancel_cutoff_min` | 120 |
| `opens_at`, `closes_at` | 10:00, 23:00. `closes_at` earlier than `opens_at` means the café closes after midnight. |
| `advance_days` | 7 |

**`Customer`**: `user` (one-to-one with Django `User`, created by Google sign-in; name and email come from Google), `phone` (asked once after first sign-in; Indian mobile, `^[6-9]\d{9}$`, not verified), `created_at`.

**`Booking`**: one PC for one time range.
- `customer`, `pc`, `period` (`DateTimeRangeField`, half-open `[start, end)`), `group` (UUID shared by PCs booked together), `created_at`, `cancelled_at` (null), `cleared_at` (null), `cleared_by` (staff user, null).
- **Exclusion constraint:** no two rows with the same `pc` and overlapping `period` where `cancelled_at IS NULL` (`ExclusionConstraint` using GiST; needs the `btree_gist` extension, added by migration).
- What a booking cost is not stored on the row; it is the sum of its wallet entries (booking debits, extension debits).

**`WalletEntry`**: append-only ledger; rows are never edited or deleted.
- `customer`, `amount_paise` (signed), `kind` ∈ {`topup_online`, `topup_cash`, `bonus`, `booking`, `extension`, `refund`, `correction`}, `booking` (null), `razorpay_payment_id` (null, **unique**), `staff` (user who made a cash top-up or correction, null), `note` (required for `correction`), `at`.
- **Balance** = sum of the customer's `amount_paise`.

**`Offer`**: `name`, `pay_paise`, `bonus_paise`, `is_active`, `valid_until` (null). Applies only when a top-up's amount equals `pay_paise` exactly. The website shows it as hours at the current rate ("Pay ₹500, get 6 hrs").

**`TopUpOrder`**: `razorpay_order_id` (unique), `customer`, `amount_paise`, `bonus_paise` (snapshot of the offer at order creation, 0 if none), `offer` (null), `created_at`, `paid_at` (null).

`PC` and `StateChange` are unchanged.

## 5. Booking rules

All rules live in `booking/rules.py` as pure functions taking the current time and settings, so they are easy to test. Only the server clock is used (`Asia/Kolkata`).

**Price** = `hourly_rate_paise × minutes ÷ 60`, rounded half-up to the paise. A rate change applies only to new bookings and extensions.

**A booking request is valid when:**
1. Length is a whole number of steps and at least `min_booking_min`.
2. Start is on a step boundary, or is "Start now" (the current minute).
3. Start is not in the past and not more than `advance_days` ahead.
4. Start and end fall inside one opening period (handling periods that cross midnight).
5. Every chosen PC is active and **Free** (below).
6. The wallet balance covers the total.

**A PC is Free for a period when** no non-cancelled booking overlaps it **and**, for "Start now" only, its live status (`status.state.compute_state`) is not In Use. Idle and Off count as free. Future periods ignore status.

**Booking:** in one database transaction: lock the customer row (`select_for_update`), check the balance, insert one `Booking` per PC (shared `group`), insert one `booking` wallet debit per PC. If the exclusion constraint fires, the transaction rolls back and the customer sees *"PC07 was just booked by someone else. Pick another seat."*

**"Free until":** for "Start now", the grid shows the start of the next booking on each PC and caps the length to fit.

**Add time:** a current or upcoming booking can be extended by whole steps, while it hasn't ended, if the PC is free afterwards and the new end is within the opening period. It is charged at the current rate as an `extension` debit linked to the booking. The exclusion constraint guards it too.

**Cancel:** per PC, allowed while `now ≤ start − cancel_cutoff_min`. Sets `cancelled_at` and writes one `refund` entry equal to everything paid for that booking (booking plus extension debits). Staff can cancel with a refund from admin at any time, ignoring the cutoff.

**Inactive PCs** (`is_active = False`) are not shown on the grid. Existing bookings on them remain; staff resolve them by admin cancel or correction.

**Time up:** a booking whose end has passed, is not cancelled and has no `cleared_at` is "time up" and shows on the staff dashboard until staff click **Cleared** (sets `cleared_at`, `cleared_by`). Bookings that ended more than 6 hours ago are no longer shown.

## 6. Money

**Online top-up (Razorpay):**
1. On the Wallet page the customer picks an active offer or enters an amount (₹100 to ₹10,000).
2. The server works out the amount and bonus, creates a Razorpay order, and stores a `TopUpOrder`.
3. Razorpay Checkout opens (UPI, cards, netbanking, wallets). Orders use automatic capture.
4. The wallet is credited by whichever arrives first:
   - the browser's success callback, after verifying `HMAC_SHA256(order_id|payment_id, key_secret)`;
   - the `payment.captured` webhook, after verifying the `X-Razorpay-Signature` header with the webhook secret.
   Crediting writes a `topup_online` entry (with `razorpay_payment_id`) and, if `bonus_paise > 0`, a `bonus` entry, and sets `paid_at`, all in one transaction. The unique payment ID makes a second credit impossible.
5. The amount credited is the order's stored amount, never a value sent by the browser.

**Cash top-up:** in admin, Customer → **Add cash top-up**: amount and optional active offer. Writes `topup_cash` (and `bonus`) entries recording the staff user.

**Corrections:** admin can add a `correction` entry (positive or negative) with a required note, for cash refunds or fixes.

**Refunds** go to the wallet only. The system never sends money back through Razorpay. Wallet balances don't expire. Razorpay's fee is paid by the café; customers are credited the full amount paid.

**Secrets:** `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`, plus the Google OAuth client ID and secret, live in `deploy/.env`. Development uses Razorpay test mode.

## 7. Pages

**Customer website** (mobile first):
- **Home:** live seat map with "N of 30 PCs free right now" and **Start now**; hourly rate; active offers; **Sign in with Google**. The public map shows only Free or Taken, never customer names.
- **Phone prompt:** shown once after the first sign-in.
- **Book:** one page in three sections: 1 When (date, start or "Start now", length), 2 Seats (grid of Free/Taken PCs, tap to select), 3 a pinned bottom bar with the selection, total and balance before/after, and the button **"Book 2 PCs for ₹300"**. Insufficient balance turns the button into **"Top up to book"**.
- **Confirmation:** a "ticket" with PCs, time and the new balance.
- **My bookings:** current, upcoming, past. **Cancel** per PC (shows the refund amount and the cutoff time), **Add time**.
- **Wallet:** balance shown as "₹600 (≈ 6 hrs)", **Top up**, full history.
- **Policy pages:** Terms, Privacy Policy, Cancellation & Refund Policy, Contact. Drafted in plain language for the owner to approve; not legal advice.

**Staff dashboard** (`/staff/`, staff only):
- Each tile adds its booking: "Rahul, until 16:00", or "Next: 14:00" when the PC is free now.
- Time up: the tile flashes "Time up: Rahul" with a sound until staff click **Cleared**.
- Browsers block sound until the page has been clicked, so the page shows an **Enable sound** button after each load.

**Admin** additions: Customers (balance, history, Add cash top-up, Correction), Offers, Bookings (search by customer/PC/date, cancel with refund), new Café settings fields. Wallet entries are read-only.

## 8. Look and feel

**Concept: "Night City floor plan".** The one bold element is the seat map, drawn as a neon HUD of the café floor; it is also the home page hero. Everything else stays quiet and readable.

**Colour** — each colour has one meaning everywhere:

| Token | Hex | Meaning |
|---|---|---|
| Night | `#0E0B1A` | Page background |
| Panel | `#1A1530` | Raised surfaces |
| Signal yellow | `#FCEE0A` | Your selection, primary button. Never decoration. |
| Neon cyan | `#00E5FF` | Free / available |
| Hot magenta | `#FF2A6D` | Taken, errors, time up |
| Ghost white | `#EDEAF7` | Text |

Colour is never the only signal: seats also say "Free" or "Taken", and every state has a text label.

**Type:** Chakra Petch for headlines and numbers (prices, times); Barlow for body text, 16 px minimum on phones. Uppercase only for display headlines; buttons and body in sentence case.

**Shape:** chamfered (angle-cut) corners via `clip-path`, not rounded cards. Neon glow only on the selected or focused element.

**Motion** (only in response to the user, except one moment on load):
- Page transitions: 200 ms slide via View Transitions.
- Seat tap: spring into yellow with a brief scan-line flicker.
- Total and balance: numbers roll to the new value.
- Booking confirmed: the ticket glitches in (the signature moment).
- Home load: the headline glitches in once.
- No scroll-triggered fade-ups, no continuous glitching.
- `prefers-reduced-motion`: all animation off.

**Copy:** buttons say exactly what happens ("Book 2 PCs for ₹300", "Top up ₹500"); errors say what went wrong and what to do; sentence case, plain words.

**Staff dashboard:** adopts the Night/Panel background and fonts; keeps its existing In Use / Idle / Off colours.

**Quality floor:** responsive from 360 px to desktop, visible keyboard focus, WCAG AA contrast, no WebGL or heavy effects.

## 9. Security

- Amounts, prices and bonuses are computed only on the server.
- Every Razorpay callback and webhook is signature-checked with `hmac.compare_digest`; unsigned or mismatched requests get `400` and credit nothing.
- Wallet debits run under a row lock on the customer, inside a transaction.
- Customers can read and change only their own bookings and wallet.
- Dashboard and admin require `is_staff`. Today the dashboard accepts any logged-in user; this must change before customers can sign in.
- CSRF protection on all forms; only the webhook is exempt.
- A Cloudflare rate-limit rule covers `/book/`, wallet top-up and the webhook.
- Secrets only in `deploy/.env`.

## 10. Testing

| Area | Tests |
|---|---|
| `rules.py` | Price and rounding, step sizes (15/30), minimum length, opening hours including after midnight, advance limit, "Start now" status rule, "free until", cancel cutoff boundary, extension rules |
| Database | Overlapping non-cancelled bookings on one PC raise `IntegrityError`; a cancelled booking frees the slot |
| Booking view | Multi-PC booking debits the right total; partial cancel refunds only that PC (including extensions); insufficient balance is refused; one PC taken makes the whole request fail cleanly |
| Wallet | Concurrent spends cannot overdraw; the same payment ID credits once (callback then webhook, and the reverse); bad signatures rejected; expired or inactive offer gives no bonus |
| Access | Customers get no dashboard/admin and no other customer's data; anonymous users are sent to sign in |
| Staff dashboard | Time-up shows after end, disappears when Cleared, hides after 6 h |
| Manual | Razorpay test-mode top-up end to end (UPI and card test credentials); Google sign-in on a phone; Lighthouse accessibility check on Home and Book |

## 11. Prerequisites

- Milestone 1 cloud deploy (domain, Oracle VM, named tunnel): Razorpay webhooks and the production Google sign-in need a public HTTPS address.
- Google Cloud OAuth client, with redirect URIs for `http://localhost:8000` (development) and `https://app.<domain>` (production).
- Razorpay test and live keys, and a webhook pointed at `/payments/razorpay/webhook` for `payment.captured`.
- Owner approval of the policy pages.

## 12. Out of scope

Refunds to bank/UPI, SMS/WhatsApp/email notifications, loyalty points, GST invoices, locking or controlling PCs, analytics (Milestone 4), multi-café support, different prices per PC or time of day.
