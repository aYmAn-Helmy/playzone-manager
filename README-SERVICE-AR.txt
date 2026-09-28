PlayZone Manager v0.31 - Remote Support Edition
===============================================

التشغيل المحلي
--------------
Windows Boot -> PlayZoneManager Service -> Local Web http://127.0.0.1:8000
ويتم فتح الواجهة للمستخدم في Microsoft Edge App Mode.

المكونات
--------
- Local SQLite DB
- Session Engine
- OPEN / TIMED / Pause / Resume
- Multi Controllers 2 / 3 / 4
- Voltra TCP 10086 + Internal API 8086
- Local Web 127.0.0.1:8000
- Windows Service يبدأ تلقائياً مع Windows
- Tailscale Remote Support اختياري عبر Private Serve
- Cloud Sync: Disabled

التثبيت
-------
1) فك ضغط الملف بالكامل.
2) شغّل Install-PlayZone-Service.bat كـ Run as administrator.
3) التثبيت نفسه Offline بالكامل؛ Python وكل المكتبات مضمنة.
4) أول مرة سيطلب منك ROOT Password إذا لم يكن قد تم تأمين ROOT سابقاً.
5) بعد نجاح التثبيت افتح PlayZone Manager من Shortcut على Desktop.

Remote Support
--------------
- ثبّت Tailscale على جهاز العميل.
- شغّل Setup-Tailscale-Support.bat كمسؤول.
- PlayZone يظل على 127.0.0.1:8000 ولا يتم فتح Port Forwarding.
- Tailscale Serve يعرض الواجهة داخل الـTailnet فقط عبر HTTPS.
- لا تستخدم Tailscale Funnel.
- تفاصيل ACL/Tag موجودة في REMOTE-SUPPORT-SETUP-AR.txt.

البيانات
--------
C:\ProgramData\PlayZone Manager\playzone.db
C:\ProgramData\PlayZone Manager\voltra.json
C:\ProgramData\PlayZone Manager\logs\service.log

مهم
----
- إغلاق Edge لا يوقف الجلسات أو Voltra لأن المحرك يعمل كـ Windows Service.
- ProgramData لا يتم حذفها عند Upgrade/Reinstall.
- ROOT لا يعمل بدون كلمة مرور في v0.31.
- عند فقد ROOT Password يمكن لمسؤول Windows المحلي تشغيل Setup-Root-Password.bat.
