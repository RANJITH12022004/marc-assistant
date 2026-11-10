package com.marc.island;

import android.content.Context;
import android.content.res.AssetManager;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * On-device Needle. Loads once, serves on loopback, plans leftover phone commands.
 */
final class NeedleEngine {
    private static final String TAG = "MarcNeedle";
    private static final int PORT = 18096;
    private static final double ACT = 0.45;
    private static final String TOOLS = "["
            + "{\"name\":\"open_app\",\"description\":\"Open an app by name.\","
            + "\"triggers\":[\"\\\\b(?:open|launch)\\\\b\"],"
            + "\"parameters\":{\"type\":\"object\",\"properties\":{\"name\":{\"type\":\"string\",\"description\":\"App name such as Terminal, Google, YouTube, Spotify\"}},\"required\":[\"name\"]}},"
            + "{\"name\":\"type_into\",\"description\":\"Type into the open app. send true means press enter after typing.\","
            + "\"triggers\":[\"\\\\b(?:type|enter|ipconfig|ssh)\\\\b\"],"
            + "\"parameters\":{\"type\":\"object\",\"properties\":{\"text\":{\"type\":\"string\",\"description\":\"Exact text to type\"},\"send\":{\"type\":\"boolean\",\"description\":\"True when the user said enter or send it\"}},\"required\":[\"text\"]}},"
            + "{\"name\":\"play_music\",\"description\":\"Play a song on Spotify. Not for YouTube.\","
            + "\"triggers\":[\"\\\\bspotify\\\\b\",\"\\\\bplay\\\\b(?![\\\\s\\\\S]*\\\\byoutube\\\\b)\"],"
            + "\"parameters\":{\"type\":\"object\",\"properties\":{\"query\":{\"type\":\"string\",\"description\":\"Song or artist\"}}}},"
            + "{\"name\":\"youtube_search\",\"description\":\"Search YouTube for a video.\","
            + "\"triggers\":[\"\\\\byoutube\\\\b\"],"
            + "\"parameters\":{\"type\":\"object\",\"properties\":{\"query\":{\"type\":\"string\",\"description\":\"Video query after youtube or search\"}},\"required\":[\"query\"]}},"
            + "{\"name\":\"google_search\",\"description\":\"Search Google for a query.\","
            + "\"triggers\":[\"\\\\bgoogle\\\\b\"],"
            + "\"parameters\":{\"type\":\"object\",\"properties\":{\"query\":{\"type\":\"string\",\"description\":\"Search query after google or search for\"}},\"required\":[\"query\"]}},"
            + "{\"name\":\"whatsapp_send\",\"description\":\"WhatsApp a named contact.\","
            + "\"triggers\":[\"\\\\bwhatsapp\\\\b\"],"
            + "\"parameters\":{\"type\":\"object\",\"properties\":{\"contact\":{\"type\":\"string\",\"description\":\"Person to message\"},\"text\":{\"type\":\"string\",\"description\":\"Message body\"},\"send\":{\"type\":\"boolean\",\"description\":\"True only when the user said send\"}},\"required\":[\"contact\",\"text\"]}}"
            + "]";

    private static final Object LOCK = new Object();
    private static final AtomicBoolean READY = new AtomicBoolean(false);
    private static final AtomicBoolean FAILED = new AtomicBoolean(false);
    private static Process process;
    private static File files;

    private NeedleEngine() {}

    static void warm(Context context) {
        Context app = context.getApplicationContext();
        new Thread(() -> {
            try {
                startLocked(app);
            } catch (Exception exc) {
                FAILED.set(true);
                Log.e(TAG, "warm failed", exc);
            }
        }, "marc-needle").start();
    }

    static void stop() {
        synchronized (LOCK) {
            READY.set(false);
            Process running = process;
            process = null;
            if (running != null) {
                running.destroy();
            }
        }
    }

    static LocalMarc.Plan plan(String text) {
        if (text == null || text.trim().isEmpty() || FAILED.get() || !READY.get()) {
            return null;
        }
        JSONObject parsed;
        synchronized (LOCK) {
            try {
                parsed = post("/complete", new JSONObject().put("input", text.trim()), 20000);
                try {
                    post("/reset", new JSONObject(), 3000);
                } catch (Exception ignored) {
                }
            } catch (Exception exc) {
                Log.w(TAG, "complete " + exc.getMessage());
                return null;
            }
        }
        double confidence = parsed.optDouble("confidence", 0);
        JSONArray calls = parsed.optJSONArray("function_calls");
        Log.i(TAG, "conf " + confidence + " calls " + (calls == null ? "[]" : calls.toString()));
        if (confidence < ACT || calls == null || calls.length() == 0) {
            return null;
        }
        JSONArray steps = new JSONArray();
        String spoken = "";
        try {
            for (int i = 0; i < calls.length(); i++) {
                JSONObject call = calls.optJSONObject(i);
                if (call == null) {
                    continue;
                }
                String name = call.optString("name");
                JSONObject args = call.optJSONObject("arguments");
                if (args == null) {
                    args = new JSONObject();
                }
                appendPhone(steps, name, args, text);
            }
            if (steps.length() == 0) {
                return null;
            }
            spoken = spokenFor(steps);
        } catch (Exception exc) {
            Log.w(TAG, "map " + exc.getMessage());
            return null;
        }
        return new LocalMarc.Plan(spoken, steps, false, false);
    }

    private static void startLocked(Context context) throws Exception {
        synchronized (LOCK) {
            if (READY.get()) {
                return;
            }
            files = new File(context.getFilesDir(), "needle");
            if (!files.exists() && !files.mkdirs()) {
                throw new IllegalStateException("needle dir");
            }
            File model = copyAsset(context, "needle3.cact", new File(files, "needle3.cact"));
            File tools = writeText(new File(files, "needle_tools.json"), TOOLS);
            File system = writeText(new File(files, "needle_system.txt"), systemFacts());
            String bin = context.getApplicationInfo().nativeLibraryDir + "/libneedle_cli.so";
            File binary = new File(bin);
            if (!binary.exists()) {
                throw new IllegalStateException("missing " + bin);
            }
            ProcessBuilder builder = new ProcessBuilder(
                    bin,
                    "--model", model.getAbsolutePath(),
                    "--tools", tools.getAbsolutePath(),
                    "--system", system.getAbsolutePath(),
                    "--serve",
                    "--port", String.valueOf(PORT)
            );
            builder.directory(files);
            builder.redirectErrorStream(true);
            builder.environment().put("NEEDLE_TELEMETRY", "0");
            builder.environment().put("DO_NOT_TRACK", "1");
            process = builder.start();
            drain(process);
        }
        long deadline = System.currentTimeMillis() + 120_000L;
        Exception last = null;
        while (System.currentTimeMillis() < deadline) {
            try {
                post("/reset", new JSONObject(), 2000);
                READY.set(true);
                Log.i(TAG, "serving");
                return;
            } catch (Exception exc) {
                last = exc;
                if (process != null && !process.isAlive()) {
                    throw new IllegalStateException("needle exited " + process.exitValue());
                }
                Thread.sleep(400L);
            }
        }
        throw last == null ? new IllegalStateException("needle timeout") : last;
    }

    private static void drain(Process running) {
        new Thread(() -> {
            try (InputStream in = running.getInputStream()) {
                byte[] buf = new byte[512];
                int n;
                while ((n = in.read(buf)) > 0) {
                    Log.i(TAG, new String(buf, 0, n, StandardCharsets.UTF_8).trim());
                }
            } catch (Exception ignored) {
            }
        }, "marc-needle-log").start();
    }

    private static File copyAsset(Context context, String name, File dest) throws Exception {
        AssetManager assets = context.getAssets();
        long want = 0;
        try (InputStream in = assets.open(name)) {
            want = in.available();
        }
        if (dest.exists() && dest.length() > 0 && (want <= 0 || dest.length() == want)) {
            return dest;
        }
        File tmp = new File(dest.getAbsolutePath() + ".tmp");
        try (InputStream in = assets.open(name); OutputStream out = new FileOutputStream(tmp)) {
            byte[] buf = new byte[64 * 1024];
            int n;
            while ((n = in.read(buf)) > 0) {
                out.write(buf, 0, n);
            }
        }
        if (dest.exists() && !dest.delete()) {
            throw new IllegalStateException("replace " + dest.getName());
        }
        if (!tmp.renameTo(dest)) {
            throw new IllegalStateException("rename " + dest.getName());
        }
        return dest;
    }

    private static File writeText(File dest, String text) throws Exception {
        try (OutputStream out = new FileOutputStream(dest)) {
            out.write(text.getBytes(StandardCharsets.UTF_8));
        }
        return dest;
    }

    private static String systemFacts() {
        String now = new SimpleDateFormat("yyyy-MM-dd E HH:mm", Locale.US).format(new Date());
        return "date: " + now + "; locale: en-IN; device: phone; user: Ranjith; assistant: Marc";
    }

    private static JSONObject post(String path, JSONObject body, int timeoutMs) throws Exception {
        HttpURLConnection conn = (HttpURLConnection) new URL("http://127.0.0.1:" + PORT + path).openConnection();
        conn.setConnectTimeout(Math.min(2000, timeoutMs));
        conn.setReadTimeout(timeoutMs);
        conn.setRequestMethod("POST");
        conn.setRequestProperty("Content-Type", "application/json");
        conn.setDoOutput(true);
        byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
        try (OutputStream out = conn.getOutputStream()) {
            out.write(bytes);
        }
        InputStream stream = conn.getResponseCode() >= 400 ? conn.getErrorStream() : conn.getInputStream();
        ByteArrayOutputStream buf = new ByteArrayOutputStream();
        byte[] chunk = new byte[2048];
        int n;
        while ((n = stream.read(chunk)) > 0) {
            buf.write(chunk, 0, n);
        }
        stream.close();
        conn.disconnect();
        String raw = buf.toString("UTF-8").trim();
        if (raw.isEmpty()) {
            return new JSONObject();
        }
        int start = raw.indexOf('{');
        int end = raw.lastIndexOf('}');
        if (start >= 0 && end > start) {
            raw = raw.substring(start, end + 1);
        }
        return new JSONObject(raw);
    }

    private static void appendPhone(JSONArray steps, String name, JSONObject args, String text) throws Exception {
        String low = text.toLowerCase(Locale.US);
        if ("youtube_search".equals(name) || ("google_search".equals(name) || "web_search".equals(name))) {
            String query = args.optString("query").trim();
            String app = "youtube_search".equals(name) || low.contains("youtube") ? "YouTube" : "Google";
            steps.put(step("open_app", new JSONObject().put("name", app)));
            if (!query.isEmpty()) {
                steps.put(step("type_into", new JSONObject().put("text", query).put("send", true)));
            }
            return;
        }
        if ("open_app".equals(name) || "close_app".equals(name)) {
            String app = args.optString("name", args.optString("app"));
            steps.put(step(name, new JSONObject().put("name", app)));
            return;
        }
        if ("type_into".equals(name) || "type_text".equals(name)) {
            steps.put(step("type_into", new JSONObject()
                    .put("text", args.optString("text"))
                    .put("send", args.optBoolean("send") || low.contains("send it") || low.contains("enter"))));
            return;
        }
        if ("play_music".equals(name) && !low.contains("youtube")) {
            steps.put(step("play_music", new JSONObject().put("query", args.optString("query"))));
            return;
        }
        if ("whatsapp_send".equals(name) || "sms_send".equals(name) || "instagram_send".equals(name)
                || "dial".equals(name) || "call".equals(name) || "media_key".equals(name)
                || "ui_tap".equals(name) || "open_food_search".equals(name) || "camera".equals(name)) {
            String tool = "call".equals(name) ? "dial" : name;
            steps.put(step(tool, args));
        }
    }

    private static JSONObject step(String tool, JSONObject args) throws Exception {
        return new JSONObject()
                .put("device", "phone")
                .put("tool", tool)
                .put("args", args);
    }

    private static String spokenFor(JSONArray steps) {
        JSONObject first = steps.optJSONObject(0);
        if (first == null) {
            return "Done.";
        }
        String tool = first.optString("tool");
        JSONObject args = first.optJSONObject("args");
        if (args == null) {
            args = new JSONObject();
        }
        if ("play_music".equals(tool)) {
            String query = args.optString("query");
            return query.isEmpty() ? "Playing on Spotify." : "Playing " + query + ".";
        }
        if ("open_app".equals(tool)) {
            return "Opening " + args.optString("name") + ".";
        }
        if ("type_into".equals(tool)) {
            return args.optBoolean("send") ? "Sent." : "Typed.";
        }
        if ("whatsapp_send".equals(tool)) {
            return "WhatsApp to " + args.optString("contact") + ".";
        }
        return "Done.";
    }
}
