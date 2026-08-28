Stripe iOS binaries (v26.8.0) live in `StripeXCFrameworks/` and are gitignored (~348MB).

From the repo root:

```
bash scripts/fetch_stripe_ios.sh
```

That downloads the ~76MB release zip instead of cloning the stripe-ios git history (multi-GB, which is what Xcode SPM was stuck on).
