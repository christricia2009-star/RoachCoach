#!/bin/bash
# Downloads Stripe iOS 26.8.0 binaries (~76MB zip) instead of cloning
# the multi-GB git history. Run from repo root if Xcode says
# StripePaymentSheet.xcframework is missing.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/IOS/Vendor/StripeXCFrameworks"
VER="26.8.0"
ZIP="/tmp/Stripe.xcframework.zip"
mkdir -p "$DEST"
curl -L --fail -o "$ZIP" "https://github.com/stripe/stripe-ios/releases/download/${VER}/Stripe.xcframework.zip"
rm -rf /tmp/stripe-xc-unpack
mkdir -p /tmp/stripe-xc-unpack
unzip -q -o "$ZIP" -d /tmp/stripe-xc-unpack
for fw in StripePaymentSheet StripePayments StripePaymentsUI StripeCore StripeUICore StripeApplePay Stripe3DS2 StripeFinancialConnections StripeFinancialConnectionsLite; do
  rm -rf "$DEST/${fw}.xcframework"
  mv "/tmp/stripe-xc-unpack/${fw}.xcframework" "$DEST/"
done
echo "Stripe xcframeworks ready in $DEST"
