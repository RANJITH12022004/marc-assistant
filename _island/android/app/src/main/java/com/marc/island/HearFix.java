package com.marc.island;

import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;

import java.util.List;
import java.util.Locale;

/** Turns a misheard phrase into an installed app or control name before it is sent. */
final class HearFix {
    private HearFix() {}

    static String correct(Context context, String heard) {
        String low = (heard == null ? "" : heard).toLowerCase(Locale.US)
                .replaceAll("[^a-z0-9 ]", " ")
                .replaceAll("\\s+", " ")
                .trim();
        low = low.replace("blue tooth", "bluetooth")
                .replace("wi fi", "wifi")
                .replace("flash light", "flashlight");
        String tail = low.replaceFirst("^(?:please\\s+)?(?:open|launch|start|turn)\\s+(?:on\\s+|off\\s+)?", "");
        tail = tail.replaceFirst("^s\\s+", "");
        String named = alias(tail);
        if (named == null) {
            named = fuzzy(context, tail);
        }
        if (named == null) {
            return low;
        }
        if (low.startsWith("turn ") || low.contains(" on") || low.contains(" off")) {
            return low.replace(tail, named);
        }
        return "open " + named;
    }

    private static String alias(String tail) {
        if (tail.matches("gate|get her|get hub|git hub|github|s get her")) {
            return "GitHub";
        }
        if (tail.matches("net flix|netflix|net flicks")) {
            return "Netflix";
        }
        if (tail.matches("prime|prime video|amazon prime")) {
            return "Prime Video";
        }
        if (tail.equals("amazon")) {
            return "Amazon";
        }
        return null;
    }

    private static String fuzzy(Context context, String tail) {
        if (tail.length() < 3) {
            return null;
        }
        String compact = tail.replace(" ", "");
        PackageManager manager = context.getPackageManager();
        Intent main = new Intent(Intent.ACTION_MAIN);
        main.addCategory(Intent.CATEGORY_LAUNCHER);
        List<ResolveInfo> apps = manager.queryIntentActivities(main, 0);
        String best = null;
        int bestDist = 3;
        for (ResolveInfo info : apps) {
            String label = info.loadLabel(manager).toString();
            String folded = label.toLowerCase(Locale.US).replace(" ", "");
            int distance = dist(compact, folded);
            if (distance < bestDist) {
                bestDist = distance;
                best = label;
            }
        }
        return best;
    }

    private static int dist(String a, String b) {
        int n = a.length();
        int m = b.length();
        if (n > 24 || m > 24 || Math.abs(n - m) > 2) {
            return 9;
        }
        int[] prev = new int[m + 1];
        int[] cur = new int[m + 1];
        for (int j = 0; j <= m; j++) {
            prev[j] = j;
        }
        for (int i = 1; i <= n; i++) {
            cur[0] = i;
            for (int j = 1; j <= m; j++) {
                int cost = a.charAt(i - 1) == b.charAt(j - 1) ? 0 : 1;
                cur[j] = Math.min(Math.min(cur[j - 1] + 1, prev[j] + 1), prev[j - 1] + cost);
            }
            int[] swap = prev;
            prev = cur;
            cur = swap;
        }
        return prev[m];
    }
}
