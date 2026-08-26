# Import this schema, then deploy to production

File: `backend/schema.ckdb`  
Container: `iCloud.com.TrueFamily.RoachCoachRadar`

CloudKit does **not** let you paste this straight into Production. Import it into **Development**, then promote.

## Option A — CloudKit Console (no terminal)

1. Open [CloudKit Console](https://icloud.developer.apple.com/dashboard/) → container `iCloud.com.TrueFamily.RoachCoachRadar`.
2. Environment: **Development**.
3. Schema → Import (or use `cktool` in Option B).
4. After Development shows `MenuItem` and `Order` (and the extra Truck fields `region`, `instagramHandle`):
   **Deploy Schema Changes** → Production.

That last button is the production import.

## Option B — `cktool` (Development only)

```bash
xcrun cktool import-schema \
  --team-id 6989P4J9RG \
  --container-id iCloud.com.TrueFamily.RoachCoachRadar \
  --environment development \
  --file backend/schema.ckdb
```

If `cktool` asks you to log in, follow its token prompt once.

Then still use Console → **Deploy Schema Changes** to push Development → Production.

Existing `Truck` / `Sighting` types are additive here (`region`, `instagramHandle`, menu/order types). Nothing is renamed or type-changed.

If Console says **cannot remove field X which exists in production**, the import file was missing a field that Production already has. CloudKit treats a missing field as a delete, which production blocks. Add that field to `schema.ckdb` and import again. `reportedByUserId` on Sighting is already included for that reason.

## After deploy

1. Run the GitHub Action once so starter menus can write.
2. Rebuild the iOS app and open a truck profile — you should see a menu and Order ahead.
