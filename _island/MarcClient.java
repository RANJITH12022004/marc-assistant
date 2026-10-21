package com.marc.island;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/**
 * Talks to the home server first. The public door is only a last resort.
 */
public final class MarcClient {
    private static final String DOOR = "https://marc-door.vercel.app";
    private static final String PUBLIC_STATUS = "https://rox.tail9a2eac.ts.net/api/status";
    private static final String PUBLIC_INBOX = "https://rox.tail9a2eac.ts.net/api/phone-inbox";
    private static final String PUBLIC_UTTER = "https://rox.tail9a2eac.ts.net/api/phone-utterance";
    private static final String PUBLIC_CHAT = "https://rox.tail9a2eac.ts.net/api/phone-chat";
    private static final String[] LIVE = new String[]{
            "http://192.168.68.109:8090",
            "http://100.112.164.77:8090",
            "http://127.0.0.1:8090",
            "http://10.169.52.175:8090"
    };
    private final String token;
    private String home;
    private boolean preferPublic;

    public MarcClient(String baseUrl, String token) {
        this.token = token == null ? "" : token;
    }

    public JSONObject utterance(String text) throws Exception {
        return utterance(text, "auto");
    }

    public JSONObject utterance(String text, String target) throws Exception {
        JSONObject body = new JSONObject();
        body.put("session_id", "phone");
        body.put("text", text);
        if (target != null && !target.isEmpty()) {
            body.put("target", target);
        }
        return post("/utterance", body);
    }

    public JSONObject chat(String text) throws Exception {
        JSONObject body = new JSONObject();
        body.put("session_id", "phone");
        body.put("text", text);
        return post("/chat", body);
    }

    public JSONObject confirm(String confirmToken, boolean yes) throws Exception {
        JSONObject body = new JSONObject();
        body.put("token", confirmToken);
        body.put("yes", yes);
        return post("/confirm", body);
    }

    /** Gauges. Does not consume phone steps waiting for the desk. */
    public JSONObject status() throws Exception {
        return fetchStatus(false);
    }

    /** The service takes waiting phone steps from the home server. */
    public JSONObject takeStatus() throws Exception {
        return fetchStatus(true);
    }

    private JSONObject fetchStatus(boolean take) throws Exception {
        Exception last = null;
        String path = take ? "/status?take=1" : "/status";
        String publicUrl = take ? PUBLIC_INBOX : PUBLIC_STATUS;
        if (preferPublic) {
            try {
                return wrapPublic(publicUrl);
            } catch (Exception exc) {
                last = exc;
                preferPublic = false;
            }
        }
        for (String base : order()) {
            try {
                long started = System.nanoTime();
                JSONObject body = getOk(base + path, 1200, 4000);
                home = base;
                preferPublic = false;
                JSONObject wrap = new JSONObject();
                wrap.put("ok", true);
                wrap.put("age_ms", 0);
                wrap.put("rtt_ms", (System.nanoTime() - started) / 1_000_000L);
                wrap.put("status", body);
                return wrap;
            } catch (Exception exc) {
                last = exc;
            }
        }
        try {
            return wrapPublic(publicUrl);
        } catch (Exception exc) {
            last = exc;
        }
        if (take) {
            throw last == null ? new Exception("Can't reach Marc") : last;
        }
        long started = System.nanoTime();
        JSONObject door = getOk(DOOR + "/v1/status", 2000, 4000);
        door.put("rtt_ms", (System.nanoTime() - started) / 1_000_000L);
        if (!door.has("status")) {
            throw last == null ? new Exception("Can't reach Marc") : last;
        }
        return door;
    }

    private JSONObject wrapPublic(String publicUrl) throws Exception {
        long started = System.nanoTime();
        JSONObject body = getOk(publicUrl, 4000, 8000);
        preferPublic = true;
        JSONObject wrap = new JSONObject();
        wrap.put("ok", true);
        wrap.put("age_ms", 0);
        wrap.put("rtt_ms", (System.nanoTime() - started) / 1_000_000L);
        wrap.put("status", body);
        return wrap;
    }

    private static String publicTalk(String path) {
        if ("/utterance".equals(path)) {
            return PUBLIC_UTTER;
        }
        if ("/chat".equals(path)) {
            return PUBLIC_CHAT;
        }
        return null;
    }

    private String[] order() {
        if (home == null) {
            return LIVE;
        }
        String[] ordered = new String[LIVE.length];
        ordered[0] = home;
        int next = 1;
        for (String base : LIVE) {
            if (!base.equals(home)) {
                ordered[next++] = base;
            }
        }
        return ordered;
    }

    private JSONObject post(String path, JSONObject body) throws Exception {
        Exception last = null;
        String publicUrl = publicTalk(path);
        if (preferPublic && publicUrl != null) {
            try {
                JSONObject response = postOnce(publicUrl, body, 4000, 45000);
                if (useful(response)) {
                    return response;
                }
            } catch (Exception exc) {
                last = exc;
                preferPublic = false;
            }
        }
        for (String base : order()) {
            try {
                JSONObject response = postOnce(base + path, body, 1500, 45000);
                if (useful(response)) {
                    home = base;
                    preferPublic = false;
                    return response;
                }
                last = new Exception(response.optString("spoken", response.optString("error", "Can't reach Marc")));
            } catch (Exception exc) {
                last = exc;
            }
        }
        if (publicUrl != null) {
            try {
                JSONObject response = postOnce(publicUrl, body, 4000, 45000);
                if (useful(response)) {
                    preferPublic = true;
                    return response;
                }
            } catch (Exception exc) {
                last = exc;
            }
        }
        try {
            JSONObject door = followDoor(path, body);
            if (useful(door) && !offline(door)) {
                return door;
            }
            last = new Exception("Can't reach Marc");
        } catch (Exception exc) {
            last = exc;
        }
        throw last == null ? new Exception("Can't reach Marc") : last;
    }

    private static boolean useful(JSONObject response) {
        return response != null && (response.has("spoken") || response.has("phone_steps") || response.has("confirm"));
    }

    private JSONObject followDoor(String path, JSONObject body) throws Exception {
        JSONObject response = postOnce(DOOR + "/v1" + path, body, 2000, 6000);
        if (response.optBoolean("pending") && response.has("id")) {
            return poll(response.getString("id"));
        }
        return response;
    }

    private JSONObject poll(String id) throws Exception {
        long deadline = System.currentTimeMillis() + 6000L;
        while (System.currentTimeMillis() < deadline) {
            JSONObject response = getOnce(DOOR + "/v1/job/" + id);
            if (!response.optBoolean("pending")) {
                return response;
            }
            Thread.sleep(400L);
        }
        throw new Exception("Can't reach Marc");
    }

    private static boolean offline(JSONObject response) {
        if (response == null || !"Can't reach Marc".equals(response.optString("spoken"))) {
            return false;
        }
        JSONArray steps = response.optJSONArray("phone_steps");
        Object confirm = response.opt("confirm");
        boolean noConfirm = confirm == null || confirm == JSONObject.NULL;
        return noConfirm && (steps == null || steps.length() == 0);
    }

    private JSONObject postOnce(String fullUrl, JSONObject body, int connectTimeoutMs, int readTimeoutMs) throws Exception {
        HttpURLConnection conn = (HttpURLConnection) new URL(fullUrl).openConnection();
        conn.setConnectTimeout(connectTimeoutMs);
        conn.setReadTimeout(readTimeoutMs);
        conn.setRequestMethod("POST");
        conn.setRequestProperty("Content-Type", "application/json");
        conn.setRequestProperty("Connection", "close");
        if (!token.isEmpty()) {
            conn.setRequestProperty("Authorization", "Bearer " + token);
        }
        conn.setDoOutput(true);
        byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
        try (OutputStream out = conn.getOutputStream()) {
            out.write(bytes);
        }
        return read(conn);
    }

    private JSONObject getOnce(String fullUrl) throws Exception {
        return getOk(fullUrl, 8000, 15000);
    }

    private JSONObject getOk(String fullUrl, int connectMs, int readMs) throws Exception {
        HttpURLConnection conn = (HttpURLConnection) new URL(fullUrl).openConnection();
        conn.setConnectTimeout(connectMs);
        conn.setReadTimeout(readMs);
        conn.setRequestMethod("GET");
        conn.setRequestProperty("Connection", "close");
        if (!token.isEmpty()) {
            conn.setRequestProperty("Authorization", "Bearer " + token);
        }
        int code = conn.getResponseCode();
        if (code >= 400) {
            conn.disconnect();
            throw new Exception("status " + code);
        }
        return read(conn);
    }

    private JSONObject read(HttpURLConnection conn) throws Exception {
        BufferedReader reader = new BufferedReader(new InputStreamReader(
                conn.getResponseCode() >= 400 ? conn.getErrorStream() : conn.getInputStream(),
                StandardCharsets.UTF_8));
        StringBuilder sb = new StringBuilder();
        String line;
        while ((line = reader.readLine()) != null) {
            sb.append(line);
        }
        reader.close();
        conn.disconnect();
        return new JSONObject(sb.toString());
    }

    public static JSONArray phoneSteps(JSONObject response) {
        return response.optJSONArray("phone_steps");
    }
}
