nourxplay v0.35.1
================

هذه نسخة White Label من نظام إدارة جلسات وأجهزة الألعاب.

اسم المنتج الظاهر للعميل:
nourxplay

التثبيت:
1) فك الضغط بالكامل.
2) شغّل Install-nourxplay.bat باستخدام Run as administrator.
3) عند أول تثبيت قم بتعيين ROOT Password.
4) Tailscale يتم تثبيته تلقائياً وبشكل Silent داخل تثبيت nourxplay.
5) لا يحتاج العميل لتشغيل برنامج Tailscale أو إبقاء أيقونته بجانب الساعة.
6) ربط الجهاز بالـTailnet يتم مرة واحدة بشكل آمن من صفحة ROOT باستخدام Auth Key.

التشغيل:
- اختصار Desktop باسم nourxplay.
- تطبيق سطح المكتب باسم nourxplay.exe.
- Remote Support يعمل عبر Tailscale Serve داخل الـTailnet فقط.
- Tailscale يعمل كـ Windows Service في الخلفية بدون Tray GUI.
- nourxplay يعيد تشغيل خدمة Tailscale وServe تلقائياً عند الحاجة.
- PlayZoneManager هو اسم خدمة Windows داخلي للتوافق مع النسخ السابقة ولا يظهر كاسم المنتج في واجهة العميل.
- بيانات النسخ السابقة تظل في مسار ProgramData القديم لضمان عدم فقد البيانات أثناء التحديث.

إلغاء التثبيت:
- Uninstall-nourxplay.bat
- للحذف الكامل لبيانات جهاز الاختبار:
  Uninstall-nourxplay.bat /RemoveData
