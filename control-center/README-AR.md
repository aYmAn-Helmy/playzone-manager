# nourxplay Control Center — MVP v0.36.0

الهدف من هذه المرحلة هو إنشاء لوحة مركزية مستقلة على سيرفر CasaOS لمراقبة أجهزة عملاء nourxplay.

## المعمارية

```text
nourxplay Windows Client
        |
        | HTTPS / Heartbeat outbound
        v
nourxplay Control Center API
        |
        v
PostgreSQL
        |
        v
Control Center Dashboard
```

العميل هو الذي يبدأ الاتصال بالسيرفر. لا يحتاج Control Center إلى فتح Port داخل شبكة العميل.

## وظائف المرحلة الأولى

- إنشاء Enrollment Code مؤقت لكل عميل/فرع.
- تسجيل جهاز العميل مرة واحدة واستبدال الـEnrollment Code بـDevice Token مستقل.
- Heartbeat لكل جهاز.
- Online / Offline.
- إصدار nourxplay.
- Hostname.
- Tailscale IPv4 وDNS name.
- حالة Tailscale وServe.
- Remote URL.
- آخر وقت اتصال.
- Dashboard ويب بسيطة.

## تشغيلها على CasaOS

1. انسخ مجلد `control-center` إلى السيرفر.
2. انسخ `.env.example` إلى `.env`.
3. غيّر `POSTGRES_PASSWORD` و`CONTROL_CENTER_ADMIN_TOKEN` إلى قيم عشوائية قوية ومختلفة.
4. من مجلد `control-center` شغّل:

```bash
docker compose up -d --build
```

5. افتح:

```text
http://SERVER-IP:18080
```

## قبل الاستخدام خارج الشبكة

لا تنشر Port 18080 مباشرة على الإنترنت بدون HTTPS وحماية مناسبة.

الاختيار المفضل للـMVP:
- إما أن يكون Control Center متاحاً فقط داخل نفس Tailscale Tailnet.
- أو يوضع خلف Reverse Proxy مع HTTPS وDomain.

## البيانات

PostgreSQL محفوظ افتراضياً في:

```text
/DATA/AppData/nourxplay-control-center/postgres
```

خذ Backup دوري لهذا المسار.

## المرحلة التالية

بعد تثبيت السيرفر واختيار عنوانه النهائي، يتم ربط Windows Service في nourxplay بالـControl Center وإضافة:
- Enrollment من صفحة ROOT.
- تخزين Device Token داخل secure-data.
- Heartbeat تلقائي كل 60 ثانية.
- Version / Tailscale / Remote status.
