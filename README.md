# PlayZone Manager

Current Windows client baseline: **v0.31 Remote Support Edition**.

PlayZone Manager is the cashier/session-management application with embedded Voltra screen-power management and ROOT-only remote support.

## v0.31 highlights

- ROOT password is mandatory. ROOT cannot use the development passwordless privileged path.
- The local PlayZone backend remains bound to `127.0.0.1:8000`.
- Remote support uses **Tailscale Serve** over Tailnet-only HTTPS and proxies to `http://127.0.0.1:8000`.
- No router port-forwarding, public listener, or Tailscale Funnel is required.
- ROOT UI shows Tailscale connection status, Tailnet IP, DNS name, Always-On status, Serve status, and the Remote URL.
- ROOT UI includes Enable Remote Access, Disable Remote Access, Reconnect Tailscale, and Refresh Status actions.
- A local Windows Administrator can set/reset the ROOT password using `Setup-Root-Password.bat`.
- Tailscale setup is available through `Setup-Tailscale-Support.bat`.
- Existing session, billing, payment, and Voltra logic from the v0.30 client is preserved.

See `CHANGES-v0.31-AR.txt` for the v0.31 change summary.

## Windows client

Version is stored in `VERSION.txt`.

Main Windows service/runtime files include:

- `backend/`
- `frontend/dist/`
- `offline-runtime/`
- `Install-PlayZone-Service.bat`
- `Setup-Root-Password.bat`
- `Setup-Tailscale-Support.bat`

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

The repository still contains the earlier Railway/staging support files and historical runtime patches for compatibility and reference. The Windows client source under `backend/` and `frontend/` is now at **v0.31**.
