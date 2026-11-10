package com.marc.island;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Bee ask DAG (no Android imports). Mirrors bee_ask.py + bee_island.py.
 * Needle is never enabled on the live path.
 */
public final class BeeAsk {

    public static final String SPARK_MODEL = "muse-spark-1.3";
    public static final String WONDER_MODEL = "muse-wonder-1.0";
    public static final int ISLAND_MAX = 40;

    private static final Pattern CLAUSE_SPLIT = Pattern.compile(
            "\\s*;\\s*"
                    + "|\\s*,?\\s*\\bafter\\s+that\\b\\s*,?\\s*"
                    + "|\\s*,?\\s*\\band\\s+then\\b\\s*,?\\s*"
                    + "|\\s*,?\\s*\\bthen\\b\\s*,?\\s*"
                    + "|\\s*(?:,\\s*(?:and\\s+)?|\\band\\b\\s+)"
                    + "(?=(?:text|whatsapp|play|email|mail|call|dial|open)\\b)",
            Pattern.CASE_INSENSITIVE);

    private BeeAsk() {
    }

    public static boolean needleEnabled() {
        return false;
    }

    public static String clampLine(String value) {
        if (value == null) {
            return "";
        }
        String s = value.trim().replaceAll("\\s+", " ");
        if (s.length() > ISLAND_MAX) {
            return s.substring(0, ISLAND_MAX);
        }
        return s;
    }

    public static String lineFor(String state) {
        return lineFor(state, null);
    }

    public static String lineFor(String state, List<String> agents) {
        if ("idle".equals(state)) {
            return "";
        }
        if ("listen".equals(state)) {
            return "Listening…";
        }
        if ("plan".equals(state)) {
            return "Planning…";
        }
        if ("confirm".equals(state)) {
            return "Say yes or cancel.";
        }
        if ("done".equals(state)) {
            return "Done.";
        }
        if ("fail".equals(state)) {
            return "Failed.";
        }
        if ("wave".equals(state)) {
            if (agents == null || agents.isEmpty()) {
                return "";
            }
            StringBuilder b = new StringBuilder();
            for (String a : agents) {
                if (a == null) {
                    continue;
                }
                String t = a.trim();
                if (t.isEmpty()) {
                    continue;
                }
                if (b.length() > 0) {
                    b.append(" · ");
                }
                b.append(t);
            }
            return clampLine(b.toString());
        }
        return "";
    }

    public static boolean skipMuse(String text) {
        if (text == null) {
            return false;
        }
        String low = text.toLowerCase(Locale.US);
        if (low.matches("(?s).*\\bdemo\\b.*")) {
            return false;
        }
        if (low.contains("email") || low.contains("whatsapp")) {
            return false;
        }
        List<String> clauses = splitClauses(text);
        if (clauses.size() > 1) {
            return false;
        }
        if (text.contains(";")
                || low.matches("(?s).*\\bafter\\s+that\\b.*")
                || low.matches("(?s).*\\bthen\\b.*")) {
            return false;
        }
        String stripped = low.trim();
        if (stripped.startsWith("type ")) {
            return true;
        }
        if (stripped.matches("open\\s+spotify\\b.*")) {
            return true;
        }
        return low.contains("youtube");
    }

    public static List<String> splitClauses(String text) {
        List<String> out = new ArrayList<String>();
        if (text == null || text.trim().isEmpty()) {
            return out;
        }
        String[] parts = CLAUSE_SPLIT.split(text);
        for (String p : parts) {
            if (p == null) {
                continue;
            }
            String s = p.trim();
            if (!s.isEmpty()) {
                out.add(s);
            }
        }
        return out;
    }

    public static String classifyVoice(String text) {
        String low = text == null ? "" : text.toLowerCase(Locale.US);
        if (low.contains("reboot")
                || low.contains("shutdown")
                || low.contains("sudo")
                || low.contains("poweroff")
                || low.contains("rm -rf")) {
            return "refuse";
        }
        if (low.matches("(?s).*\\b(yes|yeah|yep|okay|ok|send it)\\b.*")) {
            return "confirm";
        }
        if (low.matches("(?s).*\\b(nope|cancel|stop|no)\\b.*")) {
            return "cancel";
        }
        return "ask";
    }

    public static List<Map<String, Object>> splitUtterance(String text) {
        List<Map<String, Object>> steps = new ArrayList<Map<String, Object>>();
        List<String> clauses = splitClauses(text);
        String lowText = text == null ? "" : text.toLowerCase(Locale.US);
        int pos = 0;
        int[] starts = new int[clauses.size()];
        int[] ends = new int[clauses.size()];
        for (int i = 0; i < clauses.size(); i++) {
            String cl = clauses.get(i).toLowerCase(Locale.US);
            int idx = lowText.indexOf(cl, pos);
            if (idx < 0) {
                idx = pos;
            }
            starts[i] = idx;
            ends[i] = idx + cl.length();
            pos = ends[i];
        }
        for (int i = 0; i < clauses.size(); i++) {
            Map<String, Object> tool = clauseToTool(clauses.get(i));
            if (tool == null || tool.get("tool") == null) {
                continue;
            }
            String sid = "s" + (steps.size() + 1);
            List<String> after = new ArrayList<String>();
            if (!steps.isEmpty()) {
                String gap = "";
                try {
                    gap = lowText.substring(ends[i - 1], starts[i]);
                } catch (Exception ignored) {
                    gap = "";
                }
                if (gap.matches("(?s).*\\bthen\\b.*") || gap.matches("(?s).*\\bafter\\s+that\\b.*")) {
                    Object prev = steps.get(steps.size() - 1).get("id");
                    if (prev != null) {
                        after.add(String.valueOf(prev));
                    }
                }
            }
            Map<String, Object> step = new HashMap<String, Object>();
            step.put("id", sid);
            step.put("tool", tool.get("tool"));
            step.put("args", tool.get("args"));
            step.put("device", tool.get("device"));
            step.put("after", after);
            steps.add(step);
        }
        return steps;
    }

    public static Map<String, Object> planAsk(String text) {
        return planAsk(text, null, false);
    }

    public static Map<String, Object> planAsk(String text, List<Map<String, Object>> sparkTools, boolean longUtterance) {
        Map<String, Object> out = new HashMap<String, Object>();
        if ("refuse".equals(classifyVoice(text))) {
            out.put("steps", new ArrayList<Object>());
            out.put("model", SPARK_MODEL);
            out.put("kind", "refuse");
            return out;
        }
        if (skipMuse(text)) {
            List<Map<String, Object>> steps = splitUtterance(text);
            out.put("steps", steps);
            out.put("model", "local_fast");
            out.put("kind", "local_fast");
            return out;
        }
        List<Map<String, Object>> dag = splitUtterance(text);
        if (dag.size() >= 2) {
            out.put("steps", dag);
            out.put("model", SPARK_MODEL);
            out.put("kind", "dag");
            return out;
        }
        if (sparkTools != null && !sparkTools.isEmpty()) {
            out.put("steps", sparkTools);
            out.put("model", SPARK_MODEL);
            out.put("kind", "spark");
            return out;
        }
        boolean isLong = longUtterance || (text != null && text.length() > 80);
        if (isLong) {
            out.put("steps", new ArrayList<Object>());
            out.put("model", WONDER_MODEL);
            out.put("kind", "wonder");
            return out;
        }
        out.put("steps", new ArrayList<Object>());
        out.put("model", SPARK_MODEL);
        out.put("kind", "spark");
        return out;
    }

    static Map<String, Object> clauseToTool(String clause) {
        if (clause == null) {
            clause = "";
        }
        String low = clause.toLowerCase(Locale.US);
        String device = low.contains("on my laptop") ? "laptop" : "phone";
        String cleaned = clause.replaceAll("(?i)\\bon\\s+my\\s+laptop\\b", " ").trim();
        Map<String, Object> row = new HashMap<String, Object>();
        row.put("device", device);
        Matcher m;
        m = Pattern.compile("(?i)^\\s*(?:text|whatsapp)\\s+(\\S+)(?:\\s+(.*))?$").matcher(cleaned);
        if (m.find()) {
            row.put("tool", "whatsapp_send");
            Map<String, String> args = new HashMap<String, String>();
            args.put("to", nz(m.group(1)));
            args.put("text", m.group(2) == null ? "" : m.group(2).trim());
            row.put("args", args);
            return row;
        }
        m = Pattern.compile("(?i)^\\s*play\\b\\s*(.*)$").matcher(cleaned);
        if (m.find()) {
            row.put("tool", "music_play");
            Map<String, String> args = new HashMap<String, String>();
            args.put("query", nz(m.group(1)));
            row.put("args", args);
            return row;
        }
        m = Pattern.compile("(?i)^\\s*(?:email|mail)\\s+(\\S+)(?:\\s+(.*))?$").matcher(cleaned);
        if (m.find()) {
            row.put("tool", "mail_compose");
            Map<String, String> args = new HashMap<String, String>();
            args.put("to", nz(m.group(1)));
            args.put("subject", m.group(2) == null ? "" : m.group(2).trim());
            row.put("args", args);
            return row;
        }
        m = Pattern.compile("(?i)^\\s*(?:call|dial)\\b\\s*(.*)$").matcher(cleaned);
        if (m.find()) {
            row.put("tool", "phone_dial");
            Map<String, String> args = new HashMap<String, String>();
            args.put("to", nz(m.group(1)));
            row.put("args", args);
            return row;
        }
        m = Pattern.compile("(?i)^\\s*open\\b\\s*(.*)$").matcher(cleaned);
        if (m.find()) {
            row.put("tool", "app_open");
            Map<String, String> args = new HashMap<String, String>();
            args.put("app", nz(m.group(1)));
            row.put("args", args);
            return row;
        }
        return null;
    }

    private static String nz(String s) {
        return s == null ? "" : s.trim();
    }
}
