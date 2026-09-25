# PlayZone Manager

Current deployment baseline: **v0.20**.

PlayZone Manager is the cashier/session-management application with embedded Voltra screen-power management.

## v0.20 connectivity
- Private Tailscale transport for the real Voltra TCP/10086 listener on Railway.
- LAN relay for strip firmware that can only accept an IPv4 server address and fixed TCP/10086.
- Windows relay launcher with LocalSubnet-only firewall option.
- Tailscale failure is non-blocking so billing/session operation remains independent of Voltra connectivity.

See `TAILSCALE_VOLTRA.md` for deployment and validation.

## Core features
- Open sessions and timed sessions with configurable presets.
- Timed-session countdown, pause/resume freeze, extension, expiry warnings, and optional stop-and-wait-for-payment mode.
- ROOT-managed payment methods: Cash, InstaPay, Visa.
- ROOT-managed customer UI visibility profile.
- Power monitoring/alerts for screen off during an active session, failed start-power command, and screen on without a session.
- Voltra strip discovery/adoption, enable/disable, replace, remove and mapping workflow.
- ROOT-only Voltra management and protected same-origin Voltra console on Railway.

## Railway
The production/staging service listens on web port `8080`. Embedded Voltra listens internally on HTTP `127.0.0.1:8086` and on TCP `10086` for strips.

Billing/session financial operations remain independent of Voltra availability.
