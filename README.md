# PlayZone Manager

Current deployment baseline: **v0.23**.

PlayZone Manager is the cashier/session-management application with embedded Voltra screen-power management.

## v0.23 performance update
- Replaces the one-second server polling loop with a local one-second UI timer, station refresh every 5 seconds, and dashboard/shift refresh every 15 seconds.
- Actions refresh station state immediately, while secondary dashboard/page refreshes continue without keeping the action button blocked.
- Session start/end no longer wait for Voltra power commands; display power work runs in a background best-effort job after the financial/session state is committed.
- Station power state is read from one Voltra overview request instead of one HTTP request per station.
- Removes the active-session and dashboard N+1 query patterns by loading active sessions in bulk and using SQL counts.
- Timed-session snapshots include a server timestamp and continue counting down smoothly in the browser between server refreshes.
- API version is **0.23.0** and frontend assets are cache-busted to v0.23.

### v0.23 validation
Local regression testing covered ROOT login/activation, OPEN and TIMED start/end, pause/resume, timed extension, automatic expiry, payment/end flow, and the optimized station refresh path. A simulated 1.2-second Voltra delay remained off the cashier action critical path.

## v0.22 hotfix
- Fixes the blank/dark-screen React crash when a TIMED session becomes visible.
- Corrects the `+ وقت` timer icon to render the Lucide React component instead of the raw icon definition object.
- Cache-busts frontend assets to `index-v022.js` / `index-v022.css`.
- No billing, session-total, Voltra, or Tailscale behavior is changed by this hotfix.

## v0.21 highlights
- ROOT-only Always-On Tailscale remote-support status and reconnect control.
- Tailscale support information is hidden from ADMIN and all other users.
- Windows customer deployments use Tailscale Run Unattended so remote support remains available after logoff/restart.
- One-time provisioning uses a one-off, pre-approved tagged auth key; PlayZone does not store the auth key.
- Support clients use the default device tag `tag:playzone-client`.
- Open sessions and timed sessions with configurable presets.
- ROOT-managed payment methods and customer UI visibility profile.
- Voltra strip discovery/adoption, mapping, power automation and ROOT-only management.

## Tailscale customer setup
Run `Setup-Tailscale-Support.bat` once as Administrator on the customer Windows PC. The setup downloads the latest stable Windows MSI if needed and configures Tailscale with:
- `--unattended=true`
- `--accept-dns=false`
- `--accept-routes=false`
- a PlayZone-specific hostname
- `tag:playzone-client`

The Tailscale auth key is requested interactively for the one-time registration and is not saved in the PlayZone application.

## Railway
The production/staging service listens on web port `8080`. Embedded Voltra listens internally on HTTP `127.0.0.1:8086` and on TCP `10086` for strips.

Tailscale customer remote support is Windows-local functionality; Railway/Linux reports it as unsupported rather than attempting to register the cloud container.

Billing/session financial operations remain independent of Voltra and Tailscale availability.
