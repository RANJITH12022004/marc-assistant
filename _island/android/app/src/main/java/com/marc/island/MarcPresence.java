package com.marc.island;

import android.app.usage.UsageEvents;
import android.app.usage.UsageStatsManager;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.util.Log;

/** Turns screen reading off for a payment, then brings Marc back. */
final class MarcPresence {
    static final String ACTION_ASIDE = "com.marc.island.ASIDE";
    static final String ACTION_RESUME = "com.marc.island.RESUME";
    private static final String TAG = "MarcIsland";
    private static final Handler HANDLER = new Handler(Looper.getMainLooper());
    private static int clearTicks;

    private MarcPresence() {}

    static boolean isAside(Context context) {
        return prefs(context).getBoolean("aside", false);
    }

    static void stepAside(Context context) {
        if (!isAside(context)) {
            prefs(context).edit().putBoolean("aside", true).apply();
            writeEnabled(context, false);
        }
        Intent intent = new Intent(context, IslandService.class);
        intent.setAction(ACTION_ASIDE);
        try {
            context.startForegroundService(intent);
        } catch (RuntimeException exc) {
            Log.e(TAG, "aside start", exc);
            watch(context);
        }
    }

    static void resume(Context context) {
        prefs(context).edit().putBoolean("aside", false).apply();
        HANDLER.removeCallbacksAndMessages(null);
        clearTicks = 0;
        writeEnabled(context, true);
    }

    static void watch(Context context) {
        Context app = context.getApplicationContext();
        HANDLER.removeCallbacksAndMessages(null);
        clearTicks = 0;
        HANDLER.postDelayed(new Runnable() {
            @Override
            public void run() {
                if (!isAside(app)) {
                    return;
                }
                String front = foregroundPackage(app);
                if (front != null && !PaymentApps.isPayment(front) && !"com.marc.island".equals(front)) {
                    clearTicks++;
                    if (clearTicks >= 2) {
                        resume(app);
                        Intent intent = new Intent(app, IslandService.class);
                        intent.setAction(ACTION_RESUME);
                        try {
                            app.startForegroundService(intent);
                        } catch (RuntimeException exc) {
                            Log.e(TAG, "resume start", exc);
                        }
                        return;
                    }
                } else {
                    clearTicks = 0;
                }
                HANDLER.postDelayed(this, 1000);
            }
        }, 1000);
    }

    private static void writeEnabled(Context context, boolean enabled) {
        String ours = new ComponentName(context, IslandAccess.class).flattenToString();
        String current = Settings.Secure.getString(
                context.getContentResolver(), Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES);
        StringBuilder keep = new StringBuilder();
        if (current != null) {
            for (String part : current.split(":")) {
                if (part.isEmpty() || part.equals(ours) || part.endsWith("/.IslandAccess") || part.endsWith(".IslandAccess")) {
                    continue;
                }
                if (keep.length() > 0) {
                    keep.append(':');
                }
                keep.append(part);
            }
        }
        String next = keep.toString();
        if (enabled) {
            next = next.isEmpty() ? ours : next + ":" + ours;
        }
        try {
            Settings.Secure.putString(
                    context.getContentResolver(), Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES, next);
            Settings.Secure.putInt(
                    context.getContentResolver(),
                    Settings.Secure.ACCESSIBILITY_ENABLED,
                    next.isEmpty() ? 0 : 1);
        } catch (SecurityException exc) {
            Log.e(TAG, "accessibility switch", exc);
        }
    }

    private static String foregroundPackage(Context context) {
        try {
            UsageStatsManager manager = (UsageStatsManager) context.getSystemService(Context.USAGE_STATS_SERVICE);
            if (manager == null) {
                return null;
            }
            long now = System.currentTimeMillis();
            UsageEvents events = manager.queryEvents(now - 8000, now);
            if (events == null) {
                return null;
            }
            UsageEvents.Event event = new UsageEvents.Event();
            String last = null;
            while (events.hasNextEvent()) {
                events.getNextEvent(event);
                if (event.getEventType() == UsageEvents.Event.MOVE_TO_FOREGROUND) {
                    String pkg = event.getPackageName();
                    if (pkg != null && !pkg.contains("systemui")) {
                        last = pkg;
                    }
                }
            }
            return last;
        } catch (RuntimeException ignored) {
            return null;
        }
    }

    private static SharedPreferences prefs(Context context) {
        return context.getApplicationContext().getSharedPreferences("marc-presence", Context.MODE_PRIVATE);
    }
}
