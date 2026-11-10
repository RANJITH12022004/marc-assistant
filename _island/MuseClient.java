package com.marc.island;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Muse Responses client (no Android imports; java.net/java.util/java.io only).
 *
 * <p>Mirrors {@code muse_client.py}: same constants and static helpers.
 * Never prints or logs the API key.
 */
public final class MuseClient {

    /** API base. */
    public static final String BASE = "https://api.meta.ai/v1";

    /** Responses endpoint. */
    public static final String RESPONSES_URL = BASE + "/responses";

    /** Fast model. */
    public static final String SPARK = "muse-spark-1.3";

    /** Reasoning model. */
    public static final String WONDER = "muse-wonder-1.0";

    /** Voice transcription model. */
    public static final String VOICE = "muse-voice-transcribe-1.0";

    private MuseClient() {
    }

    /**
     * Request headers for the Responses API. Never prints the key.
     *
     * @param apiKey raw API key
     * @return map with Authorization Bearer + Content-Type json
     */
    public static Map<String, String> buildHeaders(String apiKey) {
        Map<String, String> h = new LinkedHashMap<String, String>();
        h.put("Authorization", "Bearer " + (apiKey == null ? "" : apiKey));
        h.put("Content-Type", "application/json");
        return h;
    }

    /** Snake-case alias of {@link #buildHeaders(String)}. */
    public static Map<String, String> build_headers(String apiKey) {
        return buildHeaders(apiKey);
    }

    /**
     * Copy of {@code headers} with the Authorization value masked.
     *
     * @param headers input headers (may be null)
     * @return copy with Authorization='Bearer ***'; empty map when null
     */
    public static Map<String, String> redact(Map<String, String> headers) {
        if (headers == null) {
            return new LinkedHashMap<String, String>();
        }
        Map<String, String> copy = new LinkedHashMap<String, String>(headers);
        if (copy.containsKey("Authorization")) {
            copy.put("Authorization", "Bearer ***");
        }
        return copy;
    }

    /**
     * Wrap {@code text} as a message/user/input_text item.
     *
     * @param text user text (null becomes "")
     * @return map {type=message, role=user, content=[{type=input_text, text=...}]}
     */
    public static Map<String, Object> userMessage(String text) {
        if (text == null) {
            text = "";
        }
        Map<String, Object> part = new LinkedHashMap<String, Object>();
        part.put("type", "input_text");
        part.put("text", text);
        List<Object> content = new ArrayList<Object>();
        content.add(part);
        Map<String, Object> msg = new LinkedHashMap<String, Object>();
        msg.put("type", "message");
        msg.put("role", "user");
        msg.put("content", content);
        return msg;
    }

    /** Snake-case alias of {@link #userMessage(String)}. */
    public static Map<String, Object> user_message(String text) {
        return userMessage(text);
    }

    /**
     * Parse a raw SSE buffer into a list of dicts.
     *
     * <p>Only {@code data: <JSON>} lines are considered. Blank lines,
     * non-data lines, the {@code [DONE]} sentinel, and non-JSON /
     * non-object payloads are skipped.
     *
     * @param buffer raw SSE text (may be null)
     * @return list of parsed objects
     */
    public static List<Map<String, Object>> parseSseEvents(String buffer) {
        List<Map<String, Object>> events = new ArrayList<Map<String, Object>>();
        if (buffer == null || buffer.isEmpty()) {
            return events;
        }
        String[] lines = buffer.split("\r?\n", -1);
        for (String rawLine : lines) {
            String line = rawLine.trim();
            if (line.isEmpty()) {
                continue;
            }
            if (!line.startsWith("data:")) {
                continue;
            }
            String payload = line.substring("data:".length()).trim();
            if (payload.isEmpty()) {
                continue;
            }
            if (payload.equals("[DONE]")) {
                continue;
            }
            Object obj;
            try {
                obj = parseJson(payload);
            } catch (Exception e) {
                continue;
            }
            if (obj instanceof Map) {
                @SuppressWarnings("unchecked")
                Map<String, Object> m = (Map<String, Object>) obj;
                events.add(m);
            }
        }
        return events;
    }

    /** Snake-case alias of {@link #parseSseEvents(String)}. */
    public static List<Map<String, Object>> parse_sse_events(String buffer) {
        return parseSseEvents(buffer);
    }

    /**
     * Extract ONLY {@code event['response']['id']}.
     *
     * <p>Never returns the top-level SSE/event {@code id}. Returns null
     * unless {@code response} is a map holding a non-empty string {@code id}.
     *
     * @param event parsed SSE event (may be null)
     * @return response id or null
     */
    public static String captureResponseId(Map<String, Object> event) {
        if (event == null) {
            return null;
        }
        Object resp = event.get("response");
        if (!(resp instanceof Map)) {
            return null;
        }
        Object id = ((Map<?, ?>) resp).get("id");
        if (id instanceof String) {
            String s = (String) id;
            if (!s.isEmpty()) {
                return s;
            }
        }
        return null;
    }

    /** Snake-case alias of {@link #captureResponseId(Map)}. */
    public static String capture_response_id(Map<String, Object> event) {
        return captureResponseId(event);
    }

    /**
     * Generic overload: inspects any object for a missing/expired reference.
     *
     * @param msg string, map, or other object (may be null)
     * @return true when the referenced response was not found or expired
     */
    public static boolean isExpiredRef(Object msg) {
        String text = coerceText(msg);
        if (text == null || text.isEmpty()) {
            return false;
        }
        String low = text.toLowerCase(java.util.Locale.ROOT);
        if (low.contains("expir")) {
            return true;
        }
        if (low.contains("not found") || low.contains("not_found")) {
            return true;
        }
        return false;
    }

    /** String overload of {@link #isExpiredRef(Object)}. */
    public static boolean isExpiredRef(String msg) {
        return isExpiredRef((Object) msg);
    }

    /** Map overload of {@link #isExpiredRef(Object)}. */
    public static boolean isExpiredRef(Map<String, Object> msg) {
        return isExpiredRef((Object) msg);
    }

    /** Snake-case alias accepting Object. */
    public static boolean is_expired_ref(Object msg) {
        return isExpiredRef(msg);
    }

    /** Snake-case alias accepting String. */
    public static boolean is_expired_ref(String msg) {
        return isExpiredRef((Object) msg);
    }

    /** Snake-case alias accepting Map. */
    public static boolean is_expired_ref(Map<String, Object> msg) {
        return isExpiredRef((Object) msg);
    }

    /**
     * Build a {@code /responses} JSON payload with stdlib types only.
     *
     * @param model model id
     * @param text user text (when {@code input} list variant is not used)
     * @param previousResponseId optional previous response id (null/empty omitted)
     * @param stream whether to request streaming
     * @return payload map
     */
    public static Map<String, Object> buildPayload(String model, String text,
                                                   String previousResponseId, boolean stream) {
        List<Object> input = new ArrayList<Object>();
        input.add(userMessage(text));
        Map<String, Object> payload = new LinkedHashMap<String, Object>();
        payload.put("model", model);
        payload.put("input", input);
        if (previousResponseId != null && !previousResponseId.isEmpty()) {
            payload.put("previous_response_id", previousResponseId);
        }
        if (stream) {
            payload.put("stream", Boolean.TRUE);
        }
        return payload;
    }

    /** Snake-case alias of {@link #buildPayload(String, String, String, boolean)}. */
    public static Map<String, Object> build_payload(String model, String text,
                                                    String previousResponseId, boolean stream) {
        return buildPayload(model, text, previousResponseId, stream);
    }

    /**
     * POST a JSON payload to RESPONSES_URL with java.net.
     * Never prints the key.
     *
     * @param apiKey API key
     * @param payload payload map (serialized to JSON)
     * @param timeoutMs connect/read timeout in ms
     * @return raw response body as string
     */
    public static String post(String apiKey, Map<String, Object> payload, int timeoutMs)
            throws java.io.IOException {
        String json = toJson(payload);
        byte[] data = json.getBytes(StandardCharsets.UTF_8);
        URL url = new URL(RESPONSES_URL);
        HttpURLConnection conn = (HttpURLConnection) url.openConnection();
        conn.setRequestMethod("POST");
        conn.setDoOutput(true);
        conn.setConnectTimeout(timeoutMs);
        conn.setReadTimeout(timeoutMs);
        for (Map.Entry<String, String> e : buildHeaders(apiKey).entrySet()) {
            conn.setRequestProperty(e.getKey(), e.getValue());
        }
        OutputStream out = null;
        try {
            out = conn.getOutputStream();
            out.write(data);
            out.flush();
        } finally {
            if (out != null) {
                try {
                    out.close();
                } catch (Exception ignored) {
                }
            }
        }
        InputStream in = null;
        try {
            int code = conn.getResponseCode();
            if (code >= 200 && code < 300) {
                in = conn.getInputStream();
            } else {
                in = conn.getErrorStream();
                if (in == null) {
                    return "";
                }
            }
            return readAll(in);
        } finally {
            if (in != null) {
                try {
                    in.close();
                } catch (Exception ignored) {
                }
            }
            conn.disconnect();
        }
    }

    // ---- internals ----

    private static String coerceText(Object msg) {
        if (msg == null) {
            return "";
        }
        if (msg instanceof String) {
            return (String) msg;
        }
        if (msg instanceof Map) {
            StringBuilder sb = new StringBuilder();
            appendMapText((Map<?, ?>) msg, sb);
            String joined = sb.toString().trim();
            if (!joined.isEmpty()) {
                return joined;
            }
            return String.valueOf(msg);
        }
        if (msg instanceof List) {
            StringBuilder sb = new StringBuilder();
            for (Object o : (List<?>) msg) {
                String t = coerceText(o);
                if (t != null && !t.isEmpty()) {
                    if (sb.length() > 0) {
                        sb.append(' ');
                    }
                    sb.append(t);
                }
            }
            String joined = sb.toString().trim();
            if (!joined.isEmpty()) {
                return joined;
            }
        }
        try {
            return String.valueOf(msg);
        } catch (Exception e) {
            return "";
        }
    }

    private static void appendMapText(Map<?, ?> m, StringBuilder sb) {
        String[] keys = {"message", "error", "detail", "code", "type"};
        for (String k : keys) {
            Object v = m.get(k);
            if (v instanceof String) {
                String s = (String) v;
                if (!s.isEmpty()) {
                    if (sb.length() > 0) {
                        sb.append(' ');
                    }
                    sb.append(s);
                }
            } else if (v instanceof Map) {
                appendMapText((Map<?, ?>) v, sb);
            } else if (v instanceof List) {
                for (Object o : (List<?>) v) {
                    if (o instanceof String) {
                        String s = (String) o;
                        if (!s.isEmpty()) {
                            if (sb.length() > 0) {
                                sb.append(' ');
                            }
                            sb.append(s);
                        }
                    } else if (o instanceof Map) {
                        appendMapText((Map<?, ?>) o, sb);
                    }
                }
            }
        }
        if (sb.length() == 0) {
            for (Map.Entry<?, ?> e : m.entrySet()) {
                Object v = e.getValue();
                if (v instanceof String) {
                    String s = (String) v;
                    if (!s.isEmpty()) {
                        if (sb.length() > 0) {
                            sb.append(' ');
                        }
                        sb.append(s);
                    }
                }
            }
        }
    }

    private static String readAll(InputStream in) throws java.io.IOException {
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        byte[] buf = new byte[4096];
        int n;
        while ((n = in.read(buf)) != -1) {
            bos.write(buf, 0, n);
        }
        return new String(bos.toByteArray(), StandardCharsets.UTF_8);
    }

    /** Minimal JSON serializer for payload maps. */
    static String toJson(Object v) {
        if (v == null) {
            return "null";
        }
        if (v instanceof String) {
            return quote((String) v);
        }
        if (v instanceof Boolean || v instanceof Number) {
            return String.valueOf(v);
        }
        if (v instanceof Map) {
            StringBuilder sb = new StringBuilder();
            sb.append('{');
            boolean first = true;
            for (Map.Entry<?, ?> e : ((Map<?, ?>) v).entrySet()) {
                if (!first) {
                    sb.append(',');
                }
                first = false;
                sb.append(quote(String.valueOf(e.getKey())));
                sb.append(':');
                sb.append(toJson(e.getValue()));
            }
            sb.append('}');
            return sb.toString();
        }
        if (v instanceof List) {
            StringBuilder sb = new StringBuilder();
            sb.append('[');
            boolean first = true;
            for (Object o : (List<?>) v) {
                if (!first) {
                    sb.append(',');
                }
                first = false;
                sb.append(toJson(o));
            }
            sb.append(']');
            return sb.toString();
        }
        if (v instanceof Object[]) {
            StringBuilder sb = new StringBuilder();
            sb.append('[');
            Object[] arr = (Object[]) v;
            for (int i = 0; i < arr.length; i++) {
                if (i > 0) {
                    sb.append(',');
                }
                sb.append(toJson(arr[i]));
            }
            sb.append(']');
            return sb.toString();
        }
        return quote(String.valueOf(v));
    }

    private static String quote(String s) {
        StringBuilder sb = new StringBuilder();
        sb.append('"');
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"':
                    sb.append("\\\"");
                    break;
                case '\\':
                    sb.append("\\\\");
                    break;
                case '\b':
                    sb.append("\\b");
                    break;
                case '\f':
                    sb.append("\\f");
                    break;
                case '\n':
                    sb.append("\\n");
                    break;
                case '\r':
                    sb.append("\\r");
                    break;
                case '\t':
                    sb.append("\\t");
                    break;
                default:
                    if (c < 0x20) {
                        sb.append(String.format("\\u%04x", (int) c));
                    } else {
                        sb.append(c);
                    }
                    break;
            }
        }
        sb.append('"');
        return sb.toString();
    }

    // ---- minimal JSON parser (objects/arrays/strings/numbers/true/false/null) ----

    static Object parseJson(String s) throws Exception {
        if (s == null) {
            throw new Exception("null json");
        }
        int[] pos = new int[]{0};
        skipWs(s, pos);
        Object v = parseValue(s, pos);
        skipWs(s, pos);
        if (pos[0] != s.length()) {
            throw new Exception("trailing characters");
        }
        return v;
    }

    private static void skipWs(String s, int[] pos) {
        int n = s.length();
        while (pos[0] < n) {
            char c = s.charAt(pos[0]);
            if (c == ' ' || c == '\t' || c == '\n' || c == '\r') {
                pos[0]++;
            } else {
                break;
            }
        }
    }

    private static Object parseValue(String s, int[] pos) throws Exception {
        skipWs(s, pos);
        if (pos[0] >= s.length()) {
            throw new Exception("eof");
        }
        char c = s.charAt(pos[0]);
        if (c == '{') {
            return parseObject(s, pos);
        }
        if (c == '[') {
            return parseArray(s, pos);
        }
        if (c == '"') {
            return parseString(s, pos);
        }
        if (c == 't' && s.startsWith("true", pos[0])) {
            pos[0] += 4;
            return Boolean.TRUE;
        }
        if (c == 'f' && s.startsWith("false", pos[0])) {
            pos[0] += 5;
            return Boolean.FALSE;
        }
        if (c == 'n' && s.startsWith("null", pos[0])) {
            pos[0] += 4;
            return null;
        }
        if (c == '-' || (c >= '0' && c <= '9')) {
            return parseNumber(s, pos);
        }
        throw new Exception("unexpected char: " + c);
    }

    private static Map<String, Object> parseObject(String s, int[] pos) throws Exception {
        // assumes s[pos] == '{'
        pos[0]++;
        Map<String, Object> m = new LinkedHashMap<String, Object>();
        skipWs(s, pos);
        if (pos[0] < s.length() && s.charAt(pos[0]) == '}') {
            pos[0]++;
            return m;
        }
        while (true) {
            skipWs(s, pos);
            if (pos[0] >= s.length() || s.charAt(pos[0]) != '"') {
                throw new Exception("expected string key");
            }
            String key = parseString(s, pos);
            skipWs(s, pos);
            if (pos[0] >= s.length() || s.charAt(pos[0]) != ':') {
                throw new Exception("expected :");
            }
            pos[0]++;
            Object val = parseValue(s, pos);
            m.put(key, val);
            skipWs(s, pos);
            if (pos[0] >= s.length()) {
                throw new Exception("eof in object");
            }
            char d = s.charAt(pos[0]);
            if (d == '}') {
                pos[0]++;
                return m;
            }
            if (d == ',') {
                pos[0]++;
                continue;
            }
            throw new Exception("expected , or }");
        }
    }

    private static List<Object> parseArray(String s, int[] pos) throws Exception {
        // assumes s[pos] == '['
        pos[0]++;
        List<Object> list = new ArrayList<Object>();
        skipWs(s, pos);
        if (pos[0] < s.length() && s.charAt(pos[0]) == ']') {
            pos[0]++;
            return list;
        }
        while (true) {
            Object v = parseValue(s, pos);
            list.add(v);
            skipWs(s, pos);
            if (pos[0] >= s.length()) {
                throw new Exception("eof in array");
            }
            char d = s.charAt(pos[0]);
            if (d == ']') {
                pos[0]++;
                return list;
            }
            if (d == ',') {
                pos[0]++;
                continue;
            }
            throw new Exception("expected , or ]");
        }
    }

    private static String parseString(String s, int[] pos) throws Exception {
        // assumes s[pos] == '"'
        pos[0]++;
        StringBuilder sb = new StringBuilder();
        int n = s.length();
        while (pos[0] < n) {
            char c = s.charAt(pos[0]++);
            if (c == '"') {
                return sb.toString();
            }
            if (c == '\\') {
                if (pos[0] >= n) {
                    throw new Exception("eof in escape");
                }
                char e = s.charAt(pos[0]++);
                switch (e) {
                    case '"':
                        sb.append('"');
                        break;
                    case '\\':
                        sb.append('\\');
                        break;
                    case '/':
                        sb.append('/');
                        break;
                    case 'b':
                        sb.append('\b');
                        break;
                    case 'f':
                        sb.append('\f');
                        break;
                    case 'n':
                        sb.append('\n');
                        break;
                    case 'r':
                        sb.append('\r');
                        break;
                    case 't':
                        sb.append('\t');
                        break;
                    case 'u':
                        if (pos[0] + 4 > n) {
                            throw new Exception("bad unicode");
                        }
                        String hex = s.substring(pos[0], pos[0] + 4);
                        pos[0] += 4;
                        try {
                            sb.append((char) Integer.parseInt(hex, 16));
                        } catch (NumberFormatException ex) {
                            throw new Exception("bad unicode");
                        }
                        break;
                    default:
                        throw new Exception("bad escape");
                }
            } else {
                sb.append(c);
            }
        }
        throw new Exception("unterminated string");
    }

    private static Number parseNumber(String s, int[] pos) throws Exception {
        int start = pos[0];
        int n = s.length();
        if (pos[0] < n && s.charAt(pos[0]) == '-') {
            pos[0]++;
        }
        while (pos[0] < n && Character.isDigit(s.charAt(pos[0]))) {
            pos[0]++;
        }
        boolean isDouble = false;
        if (pos[0] < n && s.charAt(pos[0]) == '.') {
            isDouble = true;
            pos[0]++;
            while (pos[0] < n && Character.isDigit(s.charAt(pos[0]))) {
                pos[0]++;
            }
        }
        if (pos[0] < n && (s.charAt(pos[0]) == 'e' || s.charAt(pos[0]) == 'E')) {
            isDouble = true;
            pos[0]++;
            if (pos[0] < n && (s.charAt(pos[0]) == '+' || s.charAt(pos[0]) == '-')) {
                pos[0]++;
            }
            while (pos[0] < n && Character.isDigit(s.charAt(pos[0]))) {
                pos[0]++;
            }
        }
        String num = s.substring(start, pos[0]);
        if (num.isEmpty() || num.equals("-")) {
            throw new Exception("bad number");
        }
        try {
            if (isDouble) {
                return Double.valueOf(Double.parseDouble(num));
            }
            try {
                return Long.valueOf(Long.parseLong(num));
            } catch (NumberFormatException e) {
                return Double.valueOf(Double.parseDouble(num));
            }
        } catch (NumberFormatException e) {
            throw new Exception("bad number");
        }
    }

    /** Unmodifiable view helper (unused by contract, handy for callers). */
    public static Map<String, String> unmodifiableHeaders(Map<String, String> h) {
        if (h == null) {
            return Collections.unmodifiableMap(new LinkedHashMap<String, String>());
        }
        return Collections.unmodifiableMap(new LinkedHashMap<String, String>(h));
    }

    /**
     * POST a prompt and return output text. Never logs the key.
     */
    public static String complete(String apiKey, String model, String text)
            throws java.io.IOException {
        Map<String, Object> payload = buildPayload(model, text, null, true);
        String raw = post(apiKey, payload, 120000);
        return extractOutputText(raw);
    }

    static String extractOutputText(String raw) {
        if (raw == null || raw.isEmpty()) {
            return "";
        }
        StringBuilder acc = new StringBuilder();
        for (Map<String, Object> evt : parseSseEvents(raw)) {
            Object delta = evt.get("delta");
            if (delta instanceof String) {
                acc.append((String) delta);
            } else if (delta instanceof Map) {
                Object t = ((Map<?, ?>) delta).get("text");
                if (t instanceof String) {
                    acc.append((String) t);
                }
            }
            Object text = evt.get("text");
            if (text instanceof String && "response.output_text.delta".equals(String.valueOf(evt.get("type")))) {
                acc.append((String) text);
            }
        }
        if (acc.length() > 0) {
            return acc.toString();
        }
        int idx = raw.indexOf("\"output_text\"");
        if (idx >= 0) {
            int colon = raw.indexOf(':', idx);
            int q1 = raw.indexOf('"', colon + 1);
            int q2 = raw.indexOf('"', q1 + 1);
            if (q1 >= 0 && q2 > q1) {
                return raw.substring(q1 + 1, q2);
            }
        }
        return raw.trim().startsWith("{") ? "" : raw.trim();
    }
}
