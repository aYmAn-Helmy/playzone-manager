PlayZone Manager v0.34.2 - Secure Cash Drawer + Remote Support
===============================================

التشغيل المحلي
--------------
Windows Boot -> PlayZoneManager Service -> Local Web http://127.0.0.1:8000
واجهة المستخدم تفتح داخل PlayZone Manager.exe بمتصفح Chromium مدمج (Electron)، بدون الاعتماد على Microsoft Edge.

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
C:\ProgramData\PlayZone Manager\secure-data\playzone.db
C:\ProgramData\PlayZone Manager\secure-data\voltra.json
C:\ProgramData\PlayZone Manager\secure-data\backups\
C:\ProgramData\PlayZone Manager\logs\service.log

مجلد secure-data محمي على Windows بحيث لا يستطيع Standard User قراءة أو تعديل
قاعدة البيانات أو النسخ الاحتياطية مباشرة. الوصول متاح لـ LocalSystem وAdministrators فقط.

مهم
----
- إغلاق Edge لا يوقف الجلسات أو Voltra لأن المحرك يعمل كـ Windows Service.
- ProgramData لا يتم حذفها عند Upgrade/Reinstall.
- ROOT لا يعمل بدون كلمة مرور.
- مصروفات الموظف تظل PENDING حتى إدخال باسورد ADMIN/ROOT واعتمادها.
- تصفية وإقفال الدرج تتطلب باسورد ADMIN/ROOT.
- الدفع InstaPay/Visa من حساب STAFF يتطلب اعتماد ADMIN/ROOT لمنع إخفاء نقص الكاش.
- عند فقد ROOT Password يمكن لمسؤول Windows المحلي تشغيل Setup-Root-Password.bat.


إلغاء التثبيت الكامل
--------------------
شغّل Uninstall-PlayZone-Service.ps1 كمسؤول. يمكن الاحتفاظ بقاعدة البيانات أو حذفها باستخدام -RemoveData.


Desktop Edition v0.32
---------------------
- System Logs: ROOT only.
- PlayZone Manager.exe يستخدم Chromium مدمجاً عبر Electron 44.4.5.
- أول تثبيت يحتاج إنترنت لتنزيل runtime الرسمي إذا لم يتم وضع electron-v44.4.5-win32-x64.zip داخل desktop-runtime بجوار الـInstaller.
- بعد التثبيت لا يعتمد البرنامج على Edge أو Chrome.
