# abo_aYmAn Mobile

Android management client for multiple abo_aYmAn / PlayZone customer installations.

## What it does
- Stores a local customer list on the Android device.
- Each customer has a name and a Tailscale Serve HTTPS URL.
- Shows an ONLINE/OFFLINE probe using `/api/health`.
- Opens the customer's existing abo_aYmAn UI inside a locked-down Android WebView.
- Web sessions/local storage remain isolated per Tailscale hostname.
- Does not copy the Windows database or Voltra TCP server to Android; those stay on the customer Windows PC.

## Connectivity requirement
The Android phone must be connected to Tailscale and have access to the customer's tailnet/device URL.

## Security
- Only HTTPS Tailscale-style hostnames (`*.ts.net` or `*.tailscale.net`) can be saved.
- Cleartext HTTP is disabled.
- Customer WebView navigation is restricted to the saved hostname.
- SSL errors are not bypassed.
- The app does not store PlayZone usernames/passwords in its customer list.

## Build
Compile SDK 35, min SDK 26, Java 17.

The GitHub Actions workflow in this branch builds a debug APK for installation/testing.
