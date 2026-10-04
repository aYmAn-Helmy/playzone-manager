nourxplay v0.35.0
================

هذه نسخة White Label من نظام إدارة جلسات وأجهزة الألعاب.

اسم المنتج الظاهر للعميل:
nourxplay

التثبيت:
1) فك الضغط بالكامل.
2) شغّل Install-nourxplay.bat باستخدام Run as administrator.
3) عند أول تثبيت قم بتعيين ROOT Password.
4) لإعداد Remote Support شغّل Setup-nourxplay-Remote-Support.bat كمسؤول بعد تثبيت Tailscale.

التشغيل:
- اختصار Desktop باسم nourxplay.
- تطبيق سطح المكتب باسم nourxplay.exe.
- Remote Support يعمل عبر Tailscale Serve داخل الـTailnet فقط.
- PlayZoneManager هو اسم خدمة Windows داخلي للتوافق مع النسخ السابقة ولا يظهر كاسم المنتج في واجهة العميل.
- بيانات النسخ السابقة تظل في مسار ProgramData القديم لضمان عدم فقد البيانات أثناء التحديث.

إلغاء التثبيت:
- Uninstall-nourxplay.bat
- للحذف الكامل لبيانات جهاز الاختبار:
  Uninstall-nourxplay.bat /RemoveData
