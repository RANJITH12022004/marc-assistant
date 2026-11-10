package com.marc.island;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/** In-app chat bubbles. One line per island wave. */
final class ChatStore {
    interface Listener {
        void onChat();
    }

    static final class Line {
        final boolean user;
        final String text;

        Line(boolean user, String text) {
            this.user = user;
            this.text = text == null ? "" : text;
        }
    }

    private static Listener listener;

    private ChatStore() {
    }

    static void setListener(Listener next) {
        listener = next;
    }

    static void add(Context context, boolean user, String text) {
        List<Line> lines = snapshot(context);
        lines.add(new Line(user, text));
        JSONArray arr = new JSONArray();
        for (Line line : lines) {
            JSONObject row = new JSONObject();
            try {
                row.put("user", line.user);
                row.put("text", line.text);
                arr.put(row);
            } catch (Exception ignored) {
            }
        }
        prefs(context).edit().putString("lines", arr.toString()).apply();
        Listener current = listener;
        if (current != null) {
            current.onChat();
        }
    }

    static List<Line> snapshot(Context context) {
        List<Line> out = new ArrayList<Line>();
        String raw = prefs(context).getString("lines", "[]");
        try {
            JSONArray arr = new JSONArray(raw);
            for (int i = 0; i < arr.length(); i++) {
                JSONObject row = arr.optJSONObject(i);
                if (row != null) {
                    out.add(new Line(row.optBoolean("user"), row.optString("text")));
                }
            }
        } catch (Exception ignored) {
        }
        return out;
    }

    private static SharedPreferences prefs(Context context) {
        return context.getSharedPreferences("bee_chat", Context.MODE_PRIVATE);
    }
}
