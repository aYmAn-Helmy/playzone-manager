# abo_aYmAn Mobile

Android management client for multiple abo_aYmAn / PlayZone customer installations.

## What it does
- Stores a local customer list on the Android device.
- Each customer has a name and a secure HTTPS Remote URL.
- Accepts Cloudflare Quick Tunnel `*.trycloudflare.com` URLs for testing.
- Keeps support for Tailscale Serve `*.ts.net` / `*.tailscale.net` URLs as fallback.
- Shows an ONLINE/OFFLINE probe using `/api/health`.
- Opens the customer's existing abo_aYmAn UI inside a locked-down Android WebView.
- WebView navigation stays restricted to the saved hostname.
- Does not copy the Windows database or Voltra TCP server to Android; those stay on the customer Windows PC.

## Connectivity
### Cloudflare Quick Tunnel test
No Tailscale app is required on the Android phone. Save the temporary `https://xxxx.trycloudflare.com` URL produced by the customer PC.

### Tailscale fallback
The Android phone must be connected to Tailscale and have access to the customer's tailnet/device URL.

## Security
- Only HTTPS is accepted.
- v0.2 test whitelist: `*.trycloudflare.com`, `*.ts.net`, and `*.tailscale.net`.
- Cleartext HTTP is disabled.
- Customer WebView navigation is restricted to the saved hostname.
- SSL errors are not bypassed.
- The app does not store PlayZone usernames/passwords in its customer list.

## Build
Compile SDK 35, min SDK 27, Java 17.

Version 0.2.0 adds Cloudflare Quick Tunnel compatibility for the remote-access test.
