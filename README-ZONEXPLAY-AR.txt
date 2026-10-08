ZoneXplay v0.35.3
=================

نسخة Local Production مستقرة لتشغيل وإدارة جلسات وأجهزة الألعاب على Windows.

التثبيت
-------
1) فك الضغط بالكامل.
2) شغّل Install-ZoneXplay.bat باستخدام Run as administrator.
3) أول تثبيت سيطلب ROOT Password إذا لم يكن قد تم تأمين الحساب من قبل.
4) Python وElectron وTailscale الرسمي مضمّنون داخل Full Package.
5) بعد التثبيت ستجد اختصار ZoneXplay على سطح المكتب.

Tailscale / Remote Support
--------------------------
- Tailscale يتم تثبيته تلقائياً مع ZoneXplay ويعمل كـWindows Service في الخلفية.
- أيقونة Tailscale والـTray GUI مخفيان على جهاز العميل.
- خدمة Tailscale تعمل Automatic مع Windows.
- ZoneXplay يستخدم Tailscale Serve للوصول الخاص عبر HTTPS داخل الـTailnet.
- لا تستخدم Tailscale Funnel.
- الـBackend المحلي يظل على 127.0.0.1:8000 ولا يتم فتحه مباشرة على الإنترنت.
- إذا احتاج الجهاز ربطاً أولياً بالـTailnet استخدم Tailscale بشكل عادي أو شغّل Setup-ZoneXplay-Remote-Support.bat كمسؤول.

التشغيل
-------
- ZoneXplay.exe هو تطبيق سطح المكتب.
- PlayZoneManager هو اسم Windows Service داخلي للتوافق مع البنية الحالية.
- البيانات المالية تظل محلية في secure-data.
- Cloud Sync غير مفعّل في نسخة Local Production.
- Remote Support اختياري ويعتمد على Tailscale.

إلغاء التثبيت
-------------
- Uninstall-ZoneXplay.bat

لإزالة بيانات جهاز اختبار بالكامل:
- Uninstall-ZoneXplay.bat /RemoveData

ملاحظة:
لا تستخدم /RemoveData على جهاز عميل إنتاجي إلا بعد التأكد من وجود Backup صالح.
