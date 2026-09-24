# PlayZone v0.17 release

This commit rolls the current Windows-tested v0.17 runtime into the Railway deployment baseline.

Included changes since the previous online staging baseline:
- Improved Voltra Power Manager dashboard and strip lifecycle management.
- Automatic strip discovery with Pending/Active/Disabled/Replaced states.
- Strip adopt, disable/enable, replace, remove and mapping safeguards.
- Watt display and PlayStation label alignment in station/power cards.
- Power audit alerts:
  - active session but screen off/standby;
  - session start succeeded financially but screen ON command failed;
  - screen drawing active power with no session.
- ROOT-only customer UI customization page with visibility switches.
- ROOT-controlled payment-method availability (Cash/InstaPay/Visa), enforced by backend.
- Open and timed session modes.
- Timed presets, custom duration, countdown, pause/resume freeze, extension, warnings and expiry handling.
- STOP_AND_WAIT_PAYMENT expiry mode keeps billing deterministic and requires an explicit payment method.
- Database migrations keep older v0.16 and earlier data compatible.
- Railway keeps the Voltra HTTP dashboard private on localhost and exposes it only through a short-lived ROOT console ticket on the PlayZone origin.

Railway demo mode remains enabled for online staging by default. Real strip mappings are not guessed or auto-created.
