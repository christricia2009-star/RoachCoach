# Phase 1: Extended Data Models (Postgres + CloudKit) for Menu + Order

Status: **done**. This is an additive change — nothing existing was removed or
renamed. Diff against your original repo to review; everything below is new.

## What changed

### Backend (CloudKit — this is your live data store)
- `backend/cloudkit_schema.txt` — new `MenuItem` and `Order` record type field
  definitions, appended at the end. Create these in the CloudKit Dashboard
  (Development first, then deploy) the same way the existing `RadarWatch` /
  `Reputation` types were added.
- `backend/cloudkit_bridge.py` — new helpers: `get_menu_items_for_truck`,
  `get_menu_item`, `save_menu_item`, `delete_menu_item`, `get_orders_for_truck`,
  `get_order`, `save_order`, `update_order_status`. Same style as the existing
  `get_trucks`/`save_sighting` helpers.
- `backend/main.py` — new Pydantic schemas (`MenuItemIn/Out`, `OrderIn/Out`,
  `OrderItemIn/Out`) and 8 new endpoints:
  - `GET /api/trucks/{truck_id}/menu`
  - `POST /api/trucks/{truck_id}/menu/items` (owner: add item)
  - `PATCH /api/menu/items/{item_id}` (owner: edit item)
  - `DELETE /api/menu/items/{item_id}`
  - `POST /api/orders` (Order Ahead checkout — **prices are always resolved
    server-side from the live MenuItem record**, never trusted from the
    client, so a stale cached menu can't under/over-charge)
  - `GET /api/trucks/{truck_id}/orders` (Owner Order Board feed,
    `active_only=true` by default)
  - `GET /api/orders/{order_id}`
  - `PATCH /api/orders/{order_id}/status` (owner board status transitions)

### Backend (Postgres — reference schema)
- `backend/schema.sql` — added `menus`, `menu_items`, `orders`, `order_items`
  tables. Your backend doesn't currently run against Postgres in production
  (main.py's docstring says so explicitly), so this is kept as the canonical
  relational shape both stores should agree on — useful if you ever add
  reporting/analytics on Postgres, or migrate off CloudKit later.

### iOS
- `IOS/RoachCoachRadar/MenuItem.swift` — new `MenuItem`, `MenuItemModifier`,
  `MenuCategory` models. Codable keys match `MenuItemOut` directly (camelCase,
  no workaround needed — see note below).
- `IOS/RoachCoachRadar/Order.swift` — new `Order`, `OrderLineItem`,
  `OrderStatus`, plus `NewOrderRequest`/`NewOrderLineItem` for the client ->
  server checkout payload.
- `IOS/RoachCoachRadar/APIService.swift` — protocol gained 5 new methods
  (`fetchMenu`, `createOrder`, `fetchOrder`, `fetchOrders`,
  `updateOrderStatus`), implemented in both `MockAPIService` (in-memory, for
  previews/demo) and `LiveAPIService` (hits the new endpoints above).
- `IOS/RoachCoachRadar/MockDataService.swift` — sample menu items for the
  first two mock trucks, plus an in-memory order store so `MockAPIService`
  has something real to return.

## A convention note worth knowing
`Truck.swift` has a documented workaround: `TruckOut` in `main.py` has no
alias generator, so it serializes plain snake_case (`cuisine_type`), and
`Truck.swift` needs manual `CodingKeys` to cope. The newer `SightingIn/Out`
schemas fixed this by using `populate_by_name=True` + `Field(alias=...)` to
emit camelCase directly. **`MenuItemOut`/`OrderOut` follow the `Sighting`
convention**, not the `Truck` one — so `MenuItem.swift`/`Order.swift` decode
the wire format directly with no CodingKeys remapping needed.

## Before this ships
1. Create the `MenuItem` and `Order` record types in the CloudKit Dashboard
   (Development environment) using `backend/cloudkit_schema.txt` as the spec,
   test, then deploy to Production — same process as any other record type
   in this repo.
2. `ORDER_TAX_RATE` in `main.py` is a placeholder (`0.0`). Wire up a real rate
   or hand tax off to your payment processor (e.g. Stripe Tax) in Phase 5.
3. No new Python dependencies were needed (`json` is stdlib).

## Next phases (not started yet)
2. Public web map redesign with radar layers
3. Truck detail page with menu + Order Ahead button
4. Owner Order Board (iOS + web)
5. Stripe/Square payment flow skeleton
