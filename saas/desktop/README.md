# PlayZone Manager Desktop

Windows desktop shell for the customer cashier PC.

The app deliberately opens the **local** PlayZone/Edge runtime at `http://127.0.0.1:8000`, not the Cloud URL. This keeps cashier actions usable when the internet is unavailable.

Behavior:
- Starts as a normal Windows desktop application.
- Probes `/api/health` on the local Edge runtime.
- Opens the existing PlayZone UI inside Microsoft WebView2 when Local Edge is healthy.
- Shows a local-service error/retry screen when the Edge service is unavailable.
- Internet/Cloud availability does not control whether the cashier UI opens.

The next packaging step will install this shell together with the PlayZone Edge Windows Service and create Start Menu/Desktop shortcuts.
