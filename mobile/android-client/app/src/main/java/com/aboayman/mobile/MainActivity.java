package com.aboayman.mobile;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.net.HttpURLConnection;
import java.net.URL;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class MainActivity extends Activity {
    private static final String PREFS = "abo_mobile_customers";
    private static final String KEY_CUSTOMERS = "customers_v1";
    private final ExecutorService executor = Executors.newFixedThreadPool(4);
    private LinearLayout customersContainer;
    private TextView summaryText;
    private SharedPreferences prefs;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        setContentView(buildUi());
    }

    @Override
    protected void onResume() {
        super.onResume();
        renderCustomers();
    }

    @Override
    protected void onDestroy() {
        executor.shutdownNow();
        super.onDestroy();
    }

    private View buildUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(16), dp(12), dp(16), dp(16));
        root.setBackgroundColor(Color.rgb(7, 17, 31));
        root.setLayoutDirection(View.LAYOUT_DIRECTION_RTL);

        LinearLayout header = new LinearLayout(this);
        header.setOrientation(LinearLayout.HORIZONTAL);
        header.setGravity(Gravity.CENTER_VERTICAL);
        header.setLayoutDirection(View.LAYOUT_DIRECTION_LTR);

        ImageView logo = new ImageView(this);
        logo.setImageResource(com.aboayman.mobile.R.drawable.abo_gamepad);
        logo.setScaleType(ImageView.ScaleType.CENTER_INSIDE);
        header.addView(logo, new LinearLayout.LayoutParams(dp(54), dp(54)));

        TextView brand = text("abo_aYmAn", 21, true, Color.WHITE);
        brand.setGravity(Gravity.CENTER_VERTICAL);
        header.addView(brand, new LinearLayout.LayoutParams(dp(150), dp(54)));

        View spacer = new View(this);
        header.addView(spacer, new LinearLayout.LayoutParams(0, 1, 1f));

        Button tailscale = actionButton("Tailscale", false);
        tailscale.setOnClickListener(v -> openTailscale());
        header.addView(tailscale, new LinearLayout.LayoutParams(dp(104), dp(44)));
        root.addView(header, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(68)));

        TextView title = text("إدارة العملاء", 25, true, Color.WHITE);
        title.setGravity(Gravity.RIGHT);
        root.addView(title, marginParams(-1, -2, 2, 12, 2, 0));

        summaryText = text("", 14, false, Color.rgb(143, 178, 214));
        summaryText.setGravity(Gravity.RIGHT);
        root.addView(summaryText, marginParams(-1, -2, 2, 0, 2, 12));

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        customersContainer = new LinearLayout(this);
        customersContainer.setOrientation(LinearLayout.VERTICAL);
        customersContainer.setLayoutDirection(View.LAYOUT_DIRECTION_RTL);
        scroll.addView(customersContainer, new ScrollView.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        root.addView(scroll, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));

        Button add = actionButton("+ إضافة عميل", true);
        add.setTextSize(17);
        add.setOnClickListener(v -> showCustomerDialog(null));
        root.addView(add, marginParams(-1, dp(52), 0, 14, 0, 0));

        return root;
    }

    private void renderCustomers() {
        List<Customer> customers = loadCustomers();
        customersContainer.removeAllViews();
        summaryText.setText(String.format(Locale.US, "%d عميل • روابط Tailscale HTTPS", customers.size()));

        if (customers.isEmpty()) {
            LinearLayout empty = card();
            TextView t1 = text("مفيش عملاء مضافين لسه", 20, true, Color.WHITE);
            t1.setGravity(Gravity.CENTER);
            empty.addView(t1, marginParams(-1, -2, 12, 18, 12, 8));
            TextView t2 = text("اضغط «إضافة عميل» واكتب اسم العميل ورابط Tailscale Serve بتاعه.\nلازم Tailscale يكون متصل على الموبايل بنفس الـTailnet.", 15, false, Color.rgb(150, 178, 208));
            t2.setGravity(Gravity.CENTER);
            empty.addView(t2, marginParams(-1, -2, 12, 0, 12, 18));
            customersContainer.addView(empty, marginParams(-1, -2, 0, 4, 0, 12));
            return;
        }

        for (Customer customer : customers) {
            customersContainer.addView(buildCustomerCard(customer), marginParams(-1, -2, 0, 0, 0, 12));
        }
    }

    private View buildCustomerCard(Customer customer) {
        LinearLayout card = card();

        LinearLayout top = new LinearLayout(this);
        top.setOrientation(LinearLayout.HORIZONTAL);
        top.setGravity(Gravity.CENTER_VERTICAL);

        TextView name = text(customer.name, 20, true, Color.WHITE);
        name.setGravity(Gravity.RIGHT);
        top.addView(name, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));

        TextView status = text("● فحص...", 13, true, Color.rgb(255, 184, 77));
        status.setGravity(Gravity.LEFT);
        top.addView(status, new LinearLayout.LayoutParams(dp(100), ViewGroup.LayoutParams.WRAP_CONTENT));
        card.addView(top, marginParams(-1, -2, 14, 12, 14, 4));

        TextView url = text(customer.url, 13, false, Color.rgb(117, 172, 226));
        url.setGravity(Gravity.LEFT);
        url.setTextDirection(View.TEXT_DIRECTION_LTR);
        card.addView(url, marginParams(-1, -2, 14, 0, 14, 12));

        LinearLayout actions = new LinearLayout(this);
        actions.setOrientation(LinearLayout.HORIZONTAL);
        actions.setGravity(Gravity.CENTER_VERTICAL);

        Button open = actionButton("فتح الإدارة", true);
        open.setOnClickListener(v -> openCustomer(customer));
        actions.addView(open, new LinearLayout.LayoutParams(0, dp(46), 1.4f));

        Button edit = actionButton("تعديل", false);
        LinearLayout.LayoutParams editLp = new LinearLayout.LayoutParams(0, dp(46), 0.8f);
        editLp.setMargins(dp(8), 0, dp(8), 0);
        edit.setOnClickListener(v -> showCustomerDialog(customer));
        actions.addView(edit, editLp);

        Button delete = actionButton("حذف", false);
        delete.setTextColor(Color.rgb(255, 127, 127));
        delete.setOnClickListener(v -> confirmDelete(customer));
        actions.addView(delete, new LinearLayout.LayoutParams(0, dp(46), 0.7f));
        card.addView(actions, marginParams(-1, -2, 12, 0, 12, 12));

        checkStatus(customer, status);
        return card;
    }

    private void checkStatus(Customer customer, TextView status) {
        executor.submit(() -> {
            boolean online = false;
            int code = 0;
            HttpURLConnection connection = null;
            try {
                URL health = new URL(customer.url + "/api/health");
                connection = (HttpURLConnection) health.openConnection();
                connection.setRequestMethod("GET");
                connection.setConnectTimeout(4500);
                connection.setReadTimeout(4500);
                connection.setInstanceFollowRedirects(false);
                connection.setRequestProperty("User-Agent", "abo_aYmAn-Mobile/0.1");
                code = connection.getResponseCode();
                online = code >= 200 && code < 500;
            } catch (Exception ignored) {
                online = false;
            } finally {
                if (connection != null) connection.disconnect();
            }
            final boolean finalOnline = online;
            final int finalCode = code;
            runOnUiThread(() -> {
                if (isFinishing() || status == null) return;
                status.setText(finalOnline ? "● ONLINE" : "● OFFLINE");
                status.setTextColor(finalOnline ? Color.rgb(52, 211, 153) : Color.rgb(255, 107, 107));
                status.setContentDescription(finalOnline ? "Online HTTP " + finalCode : "Offline");
            });
        });
    }

    private void openCustomer(Customer customer) {
        Intent intent = new Intent(this, CustomerWebActivity.class);
        intent.putExtra("name", customer.name);
        intent.putExtra("url", customer.url);
        startActivity(intent);
    }

    private void showCustomerDialog(Customer existing) {
        LinearLayout form = new LinearLayout(this);
        form.setOrientation(LinearLayout.VERTICAL);
        form.setPadding(dp(20), dp(6), dp(20), 0);
        form.setLayoutDirection(View.LAYOUT_DIRECTION_RTL);

        EditText name = new EditText(this);
        name.setHint("اسم العميل - مثال: Maher Gaming");
        name.setSingleLine(true);
        name.setTextColor(Color.DKGRAY);
        name.setHintTextColor(Color.GRAY);
        if (existing != null) name.setText(existing.name);
        form.addView(name, new LinearLayout.LayoutParams(-1, dp(56)));

        EditText url = new EditText(this);
        url.setHint("https://client-name.tailnet.ts.net");
        url.setSingleLine(true);
        url.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        url.setTextDirection(View.TEXT_DIRECTION_LTR);
        url.setGravity(Gravity.LEFT | Gravity.CENTER_VERTICAL);
        url.setTextColor(Color.DKGRAY);
        url.setHintTextColor(Color.GRAY);
        if (existing != null) url.setText(existing.url);
        form.addView(url, new LinearLayout.LayoutParams(-1, dp(56)));

        AlertDialog dialog = new AlertDialog.Builder(this)
                .setTitle(existing == null ? "إضافة عميل" : "تعديل العميل")
                .setView(form)
                .setNegativeButton("إلغاء", null)
                .setPositiveButton("حفظ", null)
                .create();

        dialog.setOnShowListener(ignored -> dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
            String customerName = name.getText().toString().trim();
            String customerUrl;
            try {
                customerUrl = normalizeTailscaleUrl(url.getText().toString());
            } catch (IllegalArgumentException ex) {
                url.setError(ex.getMessage());
                return;
            }
            if (customerName.length() < 2) {
                name.setError("اكتب اسم العميل");
                return;
            }
            List<Customer> customers = loadCustomers();
            if (existing == null) {
                customers.add(new Customer(UUID.randomUUID().toString(), customerName, customerUrl));
            } else {
                for (Customer item : customers) {
                    if (item.id.equals(existing.id)) {
                        item.name = customerName;
                        item.url = customerUrl;
                        break;
                    }
                }
            }
            saveCustomers(customers);
            dialog.dismiss();
            renderCustomers();
        }));
        dialog.show();
    }

    private void confirmDelete(Customer customer) {
        new AlertDialog.Builder(this)
                .setTitle("حذف العميل؟")
                .setMessage(customer.name + "\nهيتم حذف الرابط من الموبايل فقط، ومش هيتغير أي شيء على جهاز العميل.")
                .setNegativeButton("إلغاء", null)
                .setPositiveButton("حذف", (d, w) -> {
                    List<Customer> customers = loadCustomers();
                    customers.removeIf(c -> c.id.equals(customer.id));
                    saveCustomers(customers);
                    renderCustomers();
                })
                .show();
    }

    private String normalizeTailscaleUrl(String raw) {
        String value = raw == null ? "" : raw.trim();
        if (value.isEmpty()) throw new IllegalArgumentException("اكتب رابط Tailscale");
        if (!value.contains("://")) value = "https://" + value;
        Uri uri = Uri.parse(value);
        if (!"https".equalsIgnoreCase(uri.getScheme()) || uri.getHost() == null) {
            throw new IllegalArgumentException("الرابط لازم يكون HTTPS صحيح");
        }
        String host = uri.getHost().toLowerCase(Locale.US);
        if (!(host.endsWith(".ts.net") || host.endsWith(".tailscale.net"))) {
            throw new IllegalArgumentException("استخدم رابط Tailscale HTTPS للعميل");
        }
        String normalized = "https://" + host;
        if (uri.getPort() != -1 && uri.getPort() != 443) normalized += ":" + uri.getPort();
        String path = uri.getEncodedPath();
        if (path != null && !path.equals("/") && !path.isEmpty()) normalized += path;
        while (normalized.endsWith("/")) normalized = normalized.substring(0, normalized.length() - 1);
        return normalized;
    }

    private List<Customer> loadCustomers() {
        List<Customer> result = new ArrayList<>();
        String raw = prefs.getString(KEY_CUSTOMERS, "[]");
        try {
            JSONArray array = new JSONArray(raw);
            for (int i = 0; i < array.length(); i++) {
                JSONObject obj = array.getJSONObject(i);
                result.add(new Customer(obj.optString("id"), obj.optString("name"), obj.optString("url")));
            }
        } catch (Exception ignored) { }
        return result;
    }

    private void saveCustomers(List<Customer> customers) {
        JSONArray array = new JSONArray();
        try {
            for (Customer customer : customers) {
                JSONObject obj = new JSONObject();
                obj.put("id", customer.id);
                obj.put("name", customer.name);
                obj.put("url", customer.url);
                array.put(obj);
            }
        } catch (Exception ignored) { }
        prefs.edit().putString(KEY_CUSTOMERS, array.toString()).apply();
    }

    private void openTailscale() {
        Intent launch = getPackageManager().getLaunchIntentForPackage("com.tailscale.ipn");
        try {
            if (launch != null) {
                startActivity(launch);
            } else {
                startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse("https://play.google.com/store/apps/details?id=com.tailscale.ipn")));
            }
        } catch (Exception ex) {
            Toast.makeText(this, "افتح تطبيق Tailscale واتأكد إنه Connected", Toast.LENGTH_LONG).show();
        }
    }

    private LinearLayout card() {
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setLayoutDirection(View.LAYOUT_DIRECTION_RTL);
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(Color.rgb(13, 28, 46));
        bg.setCornerRadius(dp(18));
        bg.setStroke(dp(1), Color.rgb(27, 64, 96));
        layout.setBackground(bg);
        return layout;
    }

    private Button actionButton(String label, boolean primary) {
        Button button = new Button(this);
        button.setText(label);
        button.setAllCaps(false);
        button.setTextSize(14);
        button.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        button.setTextColor(Color.WHITE);
        button.setPadding(dp(8), 0, dp(8), 0);
        GradientDrawable bg = new GradientDrawable();
        bg.setCornerRadius(dp(12));
        if (primary) {
            bg.setColor(Color.rgb(22, 140, 255));
        } else {
            bg.setColor(Color.rgb(17, 43, 68));
            bg.setStroke(dp(1), Color.rgb(37, 84, 123));
        }
        button.setBackground(bg);
        return button;
    }

    private TextView text(String value, int sizeSp, boolean bold, int color) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(sizeSp);
        view.setTextColor(color);
        view.setLineSpacing(0, 1.12f);
        if (bold) view.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        return view;
    }

    private LinearLayout.LayoutParams marginParams(int width, int height, int left, int top, int right, int bottom) {
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(width, height);
        lp.setMargins(dp(left), dp(top), dp(right), dp(bottom));
        return lp;
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    static class Customer {
        String id;
        String name;
        String url;
        Customer(String id, String name, String url) {
            this.id = id == null || id.isEmpty() ? UUID.randomUUID().toString() : id;
            this.name = name;
            this.url = url;
        }
    }
}
