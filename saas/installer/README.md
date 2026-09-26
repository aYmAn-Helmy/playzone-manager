# PlayZone Manager Windows bundle

Expected bundle layout:

```text
PlayZoneManager-Setup/
  Install-PlayZoneManager.ps1
  Uninstall-PlayZoneManager.ps1
  Start-PlayZoneEdge.ps1
  runtime/     # patched local PlayZone runtime
  desktop/     # published PlayZoneManager.exe + WebView2 files
```

The installer:

- installs binaries under `C:\Program Files\PlayZone Manager`
- stores mutable customer data under `C:\ProgramData\PlayZone Manager`
- prepares the portable Python runtime once during installation
- creates a Private-network-only firewall rule for Voltra TCP 10086
- creates an elevated SYSTEM startup task named `PlayZone Manager Edge`
- starts Local Edge automatically at Windows boot, even before the cashier opens the desktop UI
- creates Desktop and Start Menu shortcuts for `PlayZoneManager.exe`

The desktop application always talks to Local Edge on `127.0.0.1:8000`.
Cloud loss therefore does not prevent the cashier from opening or using the local PlayZone runtime.

For the commercial installer, this PowerShell bootstrap will be wrapped in a signed installer package. The scheduled-task host can later be replaced by a dedicated Windows Service without changing the Cloud/Edge protocol.
