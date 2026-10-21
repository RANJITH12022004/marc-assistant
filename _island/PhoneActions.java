package com.marc.island;

import android.Manifest;
import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.database.Cursor;
import android.graphics.drawable.Drawable;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.provider.ContactsContract;
import android.telephony.SmsManager;

import org.json.JSONArray;
import org.json.JSONObject;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Locale;

/** Phone hands. An explicit send types the message and taps Send. */
public final class PhoneActions {
    private static Fail failListener;

    interface Fail {
        void onFail(String message);
    }

    private PhoneActions() {}

    static void setFail(Fail listener) {
        failListener = listener;
    }

    static void fail(String message) {
        Fail listener = failListener;
        if (listener != null && message != null && !message.isEmpty()) {
            listener.onFail(message);
        }
    }

    public static void run(Context context, JSONArray steps) {
        if (steps == null || steps.length() == 0) {
            return;
        }
        Handler handler = new Handler(Looper.getMainLooper());
        stepAt(context, handler, steps, 0);
    }

    /** One step, then the next once that app is in front or 0.7s has passed. */
    private static void stepAt(Context context, Handler handler, JSONArray steps, int index) {
        if (index >= steps.length()) {
            return;
        }
        JSONObject step = steps.optJSONObject(index);
        String expect = "";
        if (step != null) {
            try {
                expect = perform(context, step);
            } catch (ActivityNotFoundException ignored) {
            }
        }
        String waiting = expect == null ? "" : expect;
        long settle = settleFor(step);
        long started = SystemClock.uptimeMillis();
        handler.postDelayed(new Runnable() {
            @Override
            public void run() {
                boolean arrived = waiting.isEmpty() || waiting.equals(IslandAccess.foreground());
                boolean elapsed = SystemClock.uptimeMillis() - started >= settle;
                if (arrived || elapsed) {
                    stepAt(context, handler, steps, index + 1);
                    return;
                }
                handler.postDelayed(this, 100);
            }
        }, 100);
    }

    private static String perform(Context context, JSONObject step) {
        String tool = step.optString("tool");
        JSONObject args = step.optJSONObject("args");
        if (args == null) {
            args = new JSONObject();
        }
        if ("play_music".equals(tool)) {
            playMusic(context, args.optString("query"));
            return "com.spotify.music";
        }
        if ("media_key".equals(tool)) {
            SpotifyPlay.media(context, args.optString("action", "play"));
            return "com.spotify.music";
        }
        if ("mail_compose".equals(tool) || "mail_send".equals(tool)) {
            mail(context, args.optString("to"), args.optString("subject"), args.optString("body"));
            return "com.google.android.gm";
        }
        if ("dial".equals(tool) || "call".equals(tool)) {
            placeCall(context, args.optString("contact", args.optString("number")));
            return "";
        }
        if ("camera".equals(tool)) {
            shoot(context, args.optBoolean("selfie"), args.optBoolean("shoot", true));
            return "com.nothing.camera";
        }
        if ("whatsapp_prefill".equals(tool) || "whatsapp_send".equals(tool)) {
            message(context, "WhatsApp", "com.whatsapp", args.optString("contact", args.optString("phone")), args.optString("text"), args.optBoolean("send"));
            return "com.whatsapp";
        }
        if ("type_text".equals(tool) || "type_into".equals(tool)) {
            typeNow(args.optString("text"), args.optBoolean("send"));
            return "";
        }
        if ("sms_send".equals(tool)) {
            sms(context, args.optString("contact"), args.optString("text"), args.optBoolean("send"));
            return "com.google.android.apps.messaging";
        }
        if ("instagram_send".equals(tool)) {
            message(context, "Instagram", "com.instagram.android", args.optString("contact"), args.optString("text"), args.optBoolean("send"));
            return "com.instagram.android";
        }
        if ("ui_tap".equals(tool)) {
            String pkg = args.optString("package");
            if (!pkg.isEmpty()) {
                launchPackage(context, pkg);
            }
            String label = args.optString("text", "Connect");
            new Handler(Looper.getMainLooper()).postDelayed(() -> {
                if (!ScreenHands.clickAny(label)) {
                    fail("I couldn't find " + label + ".");
                }
            }, 1200);
            return pkg;
        }
        if ("open_food_search".equals(tool)) {
            String app = args.optString("app", "swiggy");
            food(context, app, args.optString("query"));
            return "zomato".equalsIgnoreCase(app) ? "com.application.zomato" : "in.swiggy.android";
        }
        if ("open_app".equals(tool)) {
            String name = args.optString("name");
            if (name.isEmpty()) {
                name = args.optString("app");
            }
            return openApp(context, name);
        }
        if ("close_app".equals(tool)) {
            String name = args.optString("name", args.optString("app"));
            if (name.toLowerCase(Locale.US).contains("spotify") || "it".equalsIgnoreCase(name)) {
                SpotifyPlay.media(context, "pause");
            }
            goHome(context);
            return "";
        }
        return "";
    }

    private static long settleFor(JSONObject step) {
        if (step == null) {
            return 700;
        }
        String tool = step.optString("tool");
        if ("whatsapp_send".equals(tool) || "whatsapp_prefill".equals(tool) || "sms_send".equals(tool) || "instagram_send".equals(tool)) {
            return 4500;
        }
        return 700;
    }

    private static void typeNow(String text, boolean send) {
        String body = text == null ? "" : text;
        if (body.isEmpty()) {
            fail("I couldn't type that.");
            return;
        }
        Handler handler = new Handler(Looper.getMainLooper());
        handler.postDelayed(() -> {
            if (!ScreenHands.typeInto(body, true)) {
                handler.postDelayed(() -> {
                    if (!ScreenHands.typeInto(body, true)) {
                        fail("I couldn't type that.");
                        return;
                    }
                    if (send) {
                        tapSend(handler, "the app", 0);
                    }
                }, 700);
                return;
            }
            if (send) {
                tapSend(handler, "the app", 0);
            }
        }, 400);
    }

    private static void message(Context context, String label, String pkg, String contact, String text, boolean send) {
        String who = contact == null ? "" : contact.trim();
        String body = text == null ? "" : text;
        if ("WhatsApp".equals(label)) {
            String number = phoneFor(context, who);
            if (number.isEmpty()) {
                return;
            }
            whatsapp(context, number, body);
            Handler handler = new Handler(Looper.getMainLooper());
            handler.postDelayed(() -> deliverWhatsApp(handler, body, send, 0), 1000);
            return;
        }
        launchPackage(context, pkg);
        Handler handler = new Handler(Looper.getMainLooper());
        ScreenHands.play(handler, new ScreenHands.Step[]{
                step(() -> ScreenHands.clickAny("Search", "Search or ask", "Ask Meta AI or Search"), "I couldn't find search in " + label + "."),
                step(() -> ScreenHands.typeInto(who, false), "I couldn't type the contact in " + label + "."),
                step(() -> who.isEmpty() || ScreenHands.clickAny(who), "I couldn't open " + who + " in " + label + "."),
                step(() -> {
                    ScreenHands.clickAny("Message");
                    return true;
                }, ""),
                step(() -> ScreenHands.typeInto(body, true), "I couldn't type the message in " + label + "."),
                step(() -> !send || ScreenHands.clickAny("Send", "send"), "I couldn't find Send in " + label + "."),
        });
    }

    private static void deliverWhatsApp(Handler handler, String body, boolean send, int attempt) {
        if (!ScreenHands.hasEditable()) {
            if (attempt >= 10) {
                fail("I couldn't open that chat.");
                return;
            }
            handler.postDelayed(() -> deliverWhatsApp(handler, body, send, attempt + 1), 500);
            return;
        }
        if (body != null && !body.isEmpty()) {
            ScreenHands.typeInto(body, true);
        }
        if (!send || ScreenHands.clickAny("Send", "send")) {
            return;
        }
        if (attempt >= 10) {
            fail("I couldn't find Send in WhatsApp.");
            return;
        }
        handler.postDelayed(() -> deliverWhatsApp(handler, body, send, attempt + 1), 500);
    }

    private static void tapSend(Handler handler, String label, int attempt) {
        if (ScreenHands.clickAny("Send", "send")) {
            return;
        }
        if (attempt >= 8) {
            fail("I couldn't find Send in " + label + ".");
            return;
        }
        handler.postDelayed(() -> tapSend(handler, label, attempt + 1), 500);
    }

    private static ScreenHands.Step step(Check check, String failure) {
        return new ScreenHands.Step() {
            @Override
            public boolean go() {
                return check.ok();
            }

            @Override
            public String fail() {
                return failure;
            }
        };
    }

    private interface Check {
        boolean ok();
    }

    private static void sms(Context context, String contact, String text, boolean send) {
        String number = phoneFor(context, contact);
        if (number.isEmpty()) {
            return;
        }
        if (send) {
            if (context.checkSelfPermission(Manifest.permission.SEND_SMS) != PackageManager.PERMISSION_GRANTED) {
                fail("I couldn't send the text.");
                return;
            }
            SmsManager.getDefault().sendTextMessage(number, null, text == null ? "" : text, null, null);
            return;
        }
        Intent intent = new Intent(Intent.ACTION_SENDTO, Uri.parse("smsto:" + Uri.encode(number)));
        intent.putExtra("sms_body", text == null ? "" : text);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        try {
            context.startActivity(intent);
        } catch (ActivityNotFoundException exc) {
            fail("I couldn't open Messages.");
            return;
        }
    }

    private static void placeCall(Context context, String contact) {
        String number = phoneFor(context, contact);
        if (number.isEmpty()) {
            return;
        }
        Intent intent = new Intent(Intent.ACTION_CALL, Uri.parse("tel:" + Uri.encode(number)));
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        try {
            context.startActivity(intent);
        } catch (SecurityException exc) {
            fail("I couldn't place the call.");
        }
    }

    private static void shoot(Context context, boolean selfie, boolean take) {
        launchPackage(context, "com.nothing.camera");
        if (!take) {
            return;
        }
        Handler handler = new Handler(Looper.getMainLooper());
        handler.postDelayed(() -> {
            if (selfie) {
                ScreenHands.clickAny("Switch to front camera", "Front camera", "Flip camera");
            }
            handler.postDelayed(() -> {
                if (!ScreenHands.clickAny("Take Photo", "Shutter", "Capture")) {
                    fail("I couldn't take the picture.");
                }
            }, selfie ? 800 : 200);
        }, 900);
    }

    private static String phoneFor(Context context, String contact) {
        if (contact == null) {
            return "";
        }
        String digits = contact.replaceAll("[^0-9+]", "");
        if (digits.length() >= 7) {
            return digits;
        }
        if (context.checkSelfPermission(Manifest.permission.READ_CONTACTS) != PackageManager.PERMISSION_GRANTED) {
            fail("I need contacts for that.");
            return "";
        }
        Cursor cursor = context.getContentResolver().query(
                ContactsContract.CommonDataKinds.Phone.CONTENT_URI,
                new String[]{ContactsContract.CommonDataKinds.Phone.NUMBER, ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME},
                ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME + " LIKE ?",
                new String[]{"%" + contact.trim() + "%"},
                null);
        if (cursor == null) {
            fail("I couldn't find " + contact + " in contacts.");
            return "";
        }
        java.util.LinkedHashMap<String, String> found = new java.util.LinkedHashMap<>();
        while (cursor.moveToNext()) {
            String number = cursor.getString(0);
            String name = cursor.getString(1);
            if (number == null || name == null || name.trim().isEmpty()) {
                continue;
            }
            String key = name.trim();
            if (!found.containsKey(key)) {
                found.put(key, number);
            }
        }
        cursor.close();
        java.util.ArrayList<String> exact = new java.util.ArrayList<>();
        for (String name : found.keySet()) {
            if (name.equalsIgnoreCase(contact.trim())) {
                exact.add(name);
            }
        }
        java.util.List<String> names = exact.isEmpty() ? new java.util.ArrayList<>(found.keySet()) : exact;
        if (names.isEmpty()) {
            fail("I couldn't find " + contact + " in contacts.");
            return "";
        }
        if (names.size() > 1) {
            fail("Which one, " + names.get(0) + " or " + names.get(1) + "?");
            return "";
        }
        String number = found.get(names.get(0));
        return number == null ? "" : number;
    }

    public static Drawable iconForName(Context context, String name) {
        Drawable alias = iconForPackage(context, aliasPackage(name));
        if (alias != null) {
            return alias;
        }
        ResolveInfo match = matchApp(context, name);
        if (match == null) {
            return null;
        }
        return match.loadIcon(context.getPackageManager());
    }

    private static String aliasPackage(String name) {
        String want = name == null ? "" : name.trim().toLowerCase(Locale.US);
        if ("github".equals(want)) {
            return "com.github.android";
        }
        if ("tailscale".equals(want)) {
            return "com.tailscale.ipn";
        }
        if ("spotify".equals(want)) {
            return "com.spotify.music";
        }
        if ("instagram".equals(want) || "insta".equals(want)) {
            return "com.instagram.android";
        }
        if ("whatsapp".equals(want)) {
            return "com.whatsapp";
        }
        if ("camera".equals(want)) {
            return "com.nothing.camera";
        }
        if ("messages".equals(want) || "sms".equals(want)) {
            return "com.google.android.apps.messaging";
        }
        return "";
    }

    public static Drawable iconForPackage(Context context, String pkg) {
        if (pkg == null || pkg.isEmpty()) {
            return null;
        }
        try {
            return context.getPackageManager().getApplicationIcon(pkg);
        } catch (PackageManager.NameNotFoundException ignored) {
            return null;
        }
    }

    private static String launchPackage(Context context, String pkg) {
        Intent launch = context.getPackageManager().getLaunchIntentForPackage(pkg);
        if (launch == null) {
            return "";
        }
        launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        context.startActivity(launch);
        return pkg;
    }

    private static String openApp(Context context, String name) {
        String alias = aliasPackage(name);
        if (!alias.isEmpty()) {
            String launched = launchPackage(context, alias);
            if (!launched.isEmpty()) {
                return launched;
            }
        }
        ResolveInfo match = matchApp(context, name);
        if (match == null) {
            return "";
        }
        String pkg = match.activityInfo.packageName;
        Intent launch = context.getPackageManager().getLaunchIntentForPackage(pkg);
        if (launch == null) {
            return "";
        }
        launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        context.startActivity(launch);
        return pkg;
    }

    private static ResolveInfo matchApp(Context context, String name) {
        String want = name == null ? "" : name.trim().toLowerCase(Locale.US);
        if (want.isEmpty()) {
            return null;
        }
        PackageManager manager = context.getPackageManager();
        Intent main = new Intent(Intent.ACTION_MAIN);
        main.addCategory(Intent.CATEGORY_LAUNCHER);
        List<ResolveInfo> apps = manager.queryIntentActivities(main, 0);
        ResolveInfo best = null;
        int bestScore = 0;
        for (ResolveInfo info : apps) {
            String label = info.loadLabel(manager).toString().toLowerCase(Locale.US);
            String pkg = info.activityInfo.packageName.toLowerCase(Locale.US);
            int score = 0;
            if (label.equals(want) || pkg.equals(want)) {
                score = 3;
            } else if (label.startsWith(want) || want.startsWith(label)) {
                score = 2;
            } else if (label.contains(want) || pkg.contains(want)) {
                score = 1;
            }
            if (score > bestScore) {
                bestScore = score;
                best = info;
            }
        }
        return best;
    }

    private static void goHome(Context context) {
        Intent home = new Intent(Intent.ACTION_MAIN);
        home.addCategory(Intent.CATEGORY_HOME);
        home.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        context.startActivity(home);
    }

    private static void playMusic(Context context, String query) {
        SpotifyPlay.request(context, query == null ? "" : query.trim());
    }

    private static void mail(Context context, String to, String subject, String body) {
        Intent intent = new Intent(Intent.ACTION_SENDTO, Uri.parse("mailto:" + Uri.encode(to == null ? "" : to)));
        intent.putExtra(Intent.EXTRA_SUBJECT, subject == null ? "" : subject);
        intent.putExtra(Intent.EXTRA_TEXT, body == null ? "" : body);
        intent.setPackage("com.google.android.gm");
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        try {
            context.startActivity(intent);
        } catch (ActivityNotFoundException exc) {
            intent.setPackage(null);
            context.startActivity(intent);
        }
    }

    private static void dial(Context context, String number) {
        Intent intent = new Intent(Intent.ACTION_DIAL, Uri.parse("tel:" + Uri.encode(number)));
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        context.startActivity(intent);
    }

    private static void whatsapp(Context context, String phone, String text) {
        String digits = phone.replaceAll("[^0-9]", "");
        if (digits.length() == 11 && digits.startsWith("0")) {
            digits = digits.substring(1);
        }
        if (digits.length() == 10) {
            digits = "91" + digits;
        }
        String encoded = URLEncoder.encode(text == null ? "" : text, StandardCharsets.UTF_8);
        Uri uri = digits.isEmpty()
                ? Uri.parse("https://api.whatsapp.com/send?text=" + encoded)
                : Uri.parse("https://api.whatsapp.com/send?phone=" + digits + "&text=" + encoded);
        Intent intent = new Intent(Intent.ACTION_VIEW, uri);
        intent.setPackage("com.whatsapp");
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        context.startActivity(intent);
    }

    private static void food(Context context, String app, String query) {
        boolean zomato = "zomato".equalsIgnoreCase(app);
        String encoded = URLEncoder.encode(query == null ? "" : query, StandardCharsets.UTF_8);
        String url = zomato
                ? "https://www.zomato.com/search?q=" + encoded
                : "https://www.swiggy.com/search?query=" + encoded;
        Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
        intent.setPackage(zomato ? "com.application.zomato" : "in.swiggy.android");
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        try {
            context.startActivity(intent);
        } catch (ActivityNotFoundException exc) {
            intent.setPackage(null);
            context.startActivity(intent);
        }
    }
}
