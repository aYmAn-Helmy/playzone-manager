# PlayZone Manager

Current Windows client baseline: **v0.34.5 Secure Cash Drawer + Desktop Edition**.

PlayZone Manager is the cashier/session-management application with embedded Voltra screen-power management and ROOT-only remote support.

## v0.34 highlights

- Keeps the original **PlayZone Manager** product name and branding.
- Adds a self-contained Electron/Chromium desktop client instead of depending on Microsoft Edge or Chrome.
- The local PlayZone backend remains bound to `127.0.0.1:8000`.
- Adds a responsive UI for desktop, tablet, and mobile screens.
- Desktop keeps an auto-hide sidebar; tablet/mobile use a touch drawer.
- Station grids, tables, forms, and modals adapt for smaller touch screens.
- Recent invoices and system status stay above the station cards with fixed-height internal scrolling.
- System Logs are available as a separate **ROOT-only** page.
- ROOT password remains mandatory.
- Remote support remains available through Tailscale Serve.
- The verified offline Python runtime and dependency wheels are included under `offline-runtime/`.
- Cash-drawer settlement is admin-password protected; staff expenses remain pending until an ADMIN/ROOT approves or rejects them.
- Drawer settlement can occur while PlayStation sessions remain active; those sessions continue and are billed into the shift that is open when payment is finalized.
- Cashiers can hand off an open shift to another active STAFF account only after the receiving employee enters their own password; the workstation then switches to the receiver's fresh login token.
- Every admin drawer settlement is stored as an immutable sequential report entry, and shift handoffs are recorded separately.
- Only one physical drawer shift can be open at a time, including a database-level race guard.
- STAFF non-cash invoice finalization (InstaPay/Visa) requires ADMIN/ROOT re-authentication.
- Financial SQLite/backup data is stored under a Windows ACL-protected `secure-data` directory.
- Session, billing, product, reporting, and Voltra behavior remains local-first and service-backed.
- This edition does **not** include the customer drinks/running-tab module.

See `CHANGES-v0.34-AR.txt` for the current Arabic security/change summary.

## Windows client

Version is stored in `VERSION.txt`.

Main Windows service/runtime files include:

- `backend/`
- `frontend/dist/`
- `desktop-shell/`
- `desktop-runtime/`
- `offline-runtime/`
- `Install-PlayZone-Service.bat`
- `Install-PlayZone-Service.ps1`
- `Uninstall-PlayZone-Service.ps1`
- `Setup-Root-Password.bat`
- `Setup-Tailscale-Support.bat`

## Desktop runtime

The installer uses Electron 44.4.5 for the embedded Chromium desktop client. It can use a bundled runtime ZIP, a verified cached copy, or download the official Electron archive once and verify its SHA256 before extraction.

## Remote support design

```text
PlayZone backend
127.0.0.1:8000
      |
      v
Tailscale Serve
      |
      v  HTTPS inside the Tailnet
https://<client-name>.<tailnet>.ts.net
```

The application backend is intentionally not exposed on `0.0.0.0:8000`.

## Railway / historical staging files

The repository still contains earlier Railway/staging support files and historical runtime patches for compatibility and reference. The Windows client source under `backend/` and `frontend/` is now at **v0.34.5**.
