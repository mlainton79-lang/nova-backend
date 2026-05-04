"""
Vinted operator worker — fill-and-stop on real Vinted account.

This package is the Playwright-based browser worker that runs as a
separate Railway service (Dockerfile.vinted_worker). Per N1.vinted-3A:
worker fills the Sell form, takes a screenshot, and STOPS. Matthew
publishes manually in his own Vinted client.

NEVER add code here that clicks Publish, Upload-item, Post-item, or
any equivalent submission control. See safety.py for the hard rails.
"""
