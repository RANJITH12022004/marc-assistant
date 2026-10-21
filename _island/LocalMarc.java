package com.marc.island;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.Calendar;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Everyday commands that run on the phone when the server is unnecessary. */
final class LocalMarc {
    private LocalMarc() {}

    static final class Plan {
        final String spoken;
        final JSONArray steps;
        final boolean aside;
        final boolean resume;

        Plan(String spoken, JSONArray steps, boolean aside, boolean resume) {
            this.spoken = spoken;
            this.steps = steps == null ? new JSONArray() : steps;
            this.aside = aside;
            this.resume = resume;
        }
    }

    static Plan plan(String text) {
        String raw = text == null ? "" : text.trim();
        String low = raw.toLowerCase(Locale.US).replaceAll("[?.!]+$", "").trim();
        if (low.isEmpty()) {
            return null;
        }
        if (low.matches(".*\\bon\\s+(?:my\\s+|the\\s+)?(?:laptop|computer|pc|server|linux)\\b.*")) {
            return null;
        }
        if (low.matches(".*\\brestart\\s+(?:the\\s+)?(?:ollama|n8n|model|desk|api)\\b.*")) {
            return null;
        }
        if (low.matches("(?:please )?(?:step aside|pause yourself|go aside)")) {
            return new Plan("Aside.", new JSONArray(), true, false);
        }
        if (low.matches("(?:please )?(?:come back|resume yourself)")) {
            return new Plan("Here.", new JSONArray(), false, true);
        }
        if (low.matches("(?:please )?(?:hi|hello|hey|yo)(?: there)?(?: (?:marc|mark))?(?: ranjit)?|(?:marc|mark)")) {
            return new Plan("Hi Ranjit.", new JSONArray(), false, false);
        }
        if (low.matches("time|what time is it|what's the time|whats the time") || low.contains("what time") || low.contains("current time")) {
            Calendar now = Calendar.getInstance();
            int hour = now.get(Calendar.HOUR);
            if (hour == 0) {
                hour = 12;
            }
            String minute = String.format(Locale.US, "%02d", now.get(Calendar.MINUTE));
            String half = now.get(Calendar.AM_PM) == Calendar.AM ? "AM" : "PM";
            return new Plan(hour + ":" + minute + " " + half, new JSONArray(), false, false);
        }
        if (low.matches("date|what's the date|whats the date|what day is it") || low.contains("today's date") || low.contains("todays date")) {
            Calendar now = Calendar.getInstance();
            String day = now.getDisplayName(Calendar.DAY_OF_WEEK, Calendar.LONG, Locale.US);
            String month = now.getDisplayName(Calendar.MONTH, Calendar.LONG, Locale.US);
            return new Plan(day + ", " + now.get(Calendar.DAY_OF_MONTH) + " " + month, new JSONArray(), false, false);
        }
        Plan camera = camera(low);
        if (camera != null) {
            return camera;
        }
        Plan call = call(raw, low);
        if (call != null) {
            return call;
        }
        Plan typed = typeInto(raw);
        if (typed != null) {
            return typed;
        }
        Plan song = namedSong(raw, low);
        if (song != null) {
            return song;
        }
        Plan message = message(raw, low);
        if (message != null) {
            return message;
        }
        if (low.matches(".*\\b(?:open|close|send|text|whatsapp|instagram)\\b.*")) {
            Plan app = appCommand(raw, low);
            return app;
        }
        Plan media = media(low);
        if (media != null) {
            return media;
        }
        return appCommand(raw, low);
    }

    private static Plan media(String low) {
        if (low.matches(".*\\b(?:next|skip)\\b.*")) {
            return new Plan("Next.", one("media_key", arg("action", "next")), false, false);
        }
        if (low.matches(".*\\b(?:previous|prev)\\b.*")) {
            return new Plan("Previous.", one("media_key", arg("action", "previous")), false, false);
        }
        if (low.matches("(?:please )?(?:pause|stop)(?: (?:the )?(?:music|song|spotify))?")) {
            String action = low.contains("pause") ? "pause" : "stop";
            String spoken = "pause".equals(action) ? "Paused." : "Stopped.";
            return new Plan(spoken, one("media_key", arg("action", action)), false, false);
        }
        if (low.matches("(?:please )?(?:resume|play|play music|resume music)")) {
            return new Plan("Playing.", one("media_key", arg("action", "play")), false, false);
        }
        return null;
    }

    private static Plan namedSong(String raw, String low) {
        if (low.matches(".*\\b(?:whatsapp|video|youtube|instagram)\\b.*")) {
            return null;
        }
        if (!low.matches("(?:please )?play \\S.*") && !low.matches(".*\\bplay \\S.*(?:spotify)?$") && !low.contains("play ")) {
            return null;
        }
        if (!low.contains("play ")) {
            return null;
        }
        String query = musicQuery(raw);
        if (query.isEmpty()) {
            return null;
        }
        return new Plan("Playing " + query + ".", one("play_music", arg("query", query)), false, false);
    }

    private static Plan typeInto(String raw) {
        Matcher match = Pattern.compile("(?i)^(?:please\\s+)?(?:type|enter)\\s+(.+)$").matcher(raw.trim());
        if (!match.find()) {
            return null;
        }
        String body = match.group(1).replaceAll("[.]+$", "").trim();
        boolean send = body.matches("(?i).*\\band\\s+send(?:\\s+it)?$");
        body = body.replaceAll("(?i)\\s+and\\s+send(?:\\s+it)?$", "").trim();
        if (body.isEmpty()) {
            return null;
        }
        JSONObject args = arg("text", body);
        try {
            args.put("send", send);
        } catch (JSONException ignored) {
            return null;
        }
        return new Plan(send ? "Sent." : "Typed.", one("type_into", args), false, false);
    }

    private static Plan camera(String low) {
        boolean selfie = low.contains("selfie") || low.contains("selfy");
        boolean shoot = selfie || low.matches(".*\\btake (?:a )?(?:picture|photo|pic)\\b.*");
        boolean open = low.matches(".*\\b(?:open|launch|start) (?:the )?camera\\b.*") || low.equals("camera");
        if (!shoot && !open) {
            return null;
        }
        if (!shoot) {
            return new Plan("Opening camera.", one("open_app", arg("name", "camera")), false, false);
        }
        JSONObject args = new JSONObject();
        try {
            args.put("selfie", selfie);
            args.put("shoot", true);
        } catch (JSONException ignored) {
            return null;
        }
        return new Plan(selfie ? "Smile." : "Picture.", one("camera", args), false, false);
    }

    private static Plan call(String raw, String low) {
        if (low.contains("whatsapp") || low.contains("video")) {
            return null;
        }
        Matcher match = Pattern.compile("(?i)^(?:please\\s+)?(?:call|dial|phone)\\s+(.+)$").matcher(raw.trim());
        if (!match.find()) {
            return null;
        }
        String who = match.group(1).replaceAll("(?i)\\s+on\\s+my\\s+phone$", "").replaceAll("[.]+$", "").trim();
        if (who.isEmpty()) {
            return null;
        }
        return new Plan("Calling " + who + ".", one("call", arg("contact", who)), false, false);
    }

    private static Plan message(String raw, String low) {
        String folded = low.replaceAll("what'?s?\\s*app|what s up", "whatsapp");
        String tool;
        if (folded.contains("instagram") || folded.matches(".*\\binsta\\b.*")) {
            tool = "instagram_send";
        } else if (folded.contains("whatsapp")) {
            tool = "whatsapp_send";
        } else if (folded.matches(".*\\b(?:text|sms)\\b.*")) {
            tool = "sms_send";
        } else {
            return null;
        }
        String[] whoBody = contactAndBody(raw);
        String contact = whoBody[0];
        String body = whoBody[1];
        if (contact.isEmpty() || body.isEmpty()) {
            return null;
        }
        boolean draft = folded.matches(".*\\b(?:draft|don't send|do not send)\\b.*");
        boolean send = !draft && folded.matches(".*\\bsend\\b.*");
        if ("sms_send".equals(tool) && folded.matches(".*\\btext\\b.*") && !draft) {
            send = true;
        }
        String spoken;
        if ("whatsapp_send".equals(tool)) {
            spoken = send ? "Sent to " + contact + " on WhatsApp." : "WhatsApp to " + contact + ".";
        } else if ("instagram_send".equals(tool)) {
            spoken = send ? "Sent to " + contact + " on Instagram." : "Instagram to " + contact + ".";
        } else {
            spoken = send ? "Sent to " + contact + "." : "Text to " + contact + ".";
        }
        JSONObject args = arg("contact", contact);
        try {
            args.put("text", body);
            args.put("send", send);
        } catch (JSONException ignored) {
            return null;
        }
        return new Plan(spoken, one(tool, args), false, false);
    }

    private static Plan appCommand(String raw, String low) {
        if (multi(low)) {
            return null;
        }
        Matcher closed = Pattern.compile("(?i)\\b(?:close|quit|exit)\\s+(.+)$").matcher(raw.trim());
        if (closed.find()) {
            String name = closed.group(1)
                .replaceAll("(?i)\\s+on\\s+(?:my\\s+|the\\s+)?(?:phone|mobile)$", "")
                .replaceAll("[.]+$", "")
                .trim();
            if (!name.isEmpty()) {
                return new Plan("Closing " + name + ".", one("close_app", arg("name", name)), false, false);
            }
        }
        if (low.matches(".*\\b(?:send|that|saying)\\b.*")) {
            return null;
        }
        Matcher opened = Pattern.compile("(?i)\\b(?:open|launch|start)\\s+(.+)$").matcher(raw.trim());
        if (opened.find()) {
            String name = opened.group(1)
                .replaceAll("(?i)\\s+on\\s+(?:my\\s+|the\\s+)?(?:phone|mobile)$", "")
                .replaceAll("[.]+$", "")
                .trim();
            if (!name.isEmpty()) {
                return new Plan("Opening " + name + ".", one("open_app", arg("name", name)), false, false);
            }
        }
        return null;
    }

    private static String[] contactAndBody(String text) {
        Matcher said = Pattern.compile("(?i)\\b(?:that|saying)\\s+(.+)$").matcher(text);
        String contact;
        String body;
        if (said.find()) {
            body = said.group(1).replaceAll("[.]+$", "").trim();
            Matcher who = Pattern.compile("(?i)\\b(?:send|text|message|whatsapp|instagram)\\s+(.+?)\\s+(?:on\\s+\\w+\\s+)?(?:that|saying)\\b").matcher(text);
            contact = who.find() ? who.group(1).trim() : "";
        } else {
            Matcher chunk = Pattern.compile("(?i)\\b(?:text|message)\\s+(.+)$").matcher(text);
            if (!chunk.find()) {
                return new String[]{"", ""};
            }
            String[] words = chunk.group(1).replaceAll("[.]+$", "").trim().split("\\s+");
            StringBuilder who = new StringBuilder();
            int index = 0;
            while (index < words.length && index < 3 && !stopWord(words[index])) {
                if (who.length() > 0) {
                    who.append(' ');
                }
                who.append(words[index].replaceAll("[,.]", ""));
                index++;
            }
            contact = who.toString();
            StringBuilder rest = new StringBuilder();
            while (index < words.length) {
                if (rest.length() > 0) {
                    rest.append(' ');
                }
                rest.append(words[index]);
                index++;
            }
            body = rest.toString();
        }
        body = body.replaceAll("(?i)\\s+and\\s+send(?:\\s+(?:it|him|her|them))?$", "").replaceAll("[.]+$", "").trim();
        Matcher named = Pattern.compile("(?i)\\b(?:whatsapp|instagram)\\s+(?:to\\s+)?(.+?)\\s+and\\s+(?:text|message)\\b").matcher(text);
        if ((contact.isEmpty() || contact.equalsIgnoreCase("him") || contact.equalsIgnoreCase("her") || contact.equalsIgnoreCase("them") || contact.equalsIgnoreCase("to")) && named.find()) {
            contact = named.group(1).trim();
        }
        contact = contact.replaceAll("(?i)^(?:to|on)\\s+", "").replaceAll("(?i)\\s+on\\s+(?:whatsapp|instagram|messages)$", "").trim();
        return new String[]{contact, body};
    }

    private static boolean stopWord(String word) {
        String folded = word.toLowerCase(Locale.US).replaceAll("[,.]", "");
        return folded.equals("hi") || folded.equals("hello") || folded.equals("hey") || folded.equals("this") || folded.equals("that") || folded.equals("please");
    }

    private static boolean multi(String low) {
        return low.matches(".*\\b(?:and|then|also)\\b.*");
    }

    private static String musicQuery(String text) {
        Matcher played = Pattern.compile("(?i)\\bplay\\s+(.+?)(?:\\s+on\\s+(?:my\\s+)?(?:phone|spotify))?$").matcher(text.trim());
        if (!played.find()) {
            return "";
        }
        String query = played.group(1).replaceAll("(?i)\\s+on\\s+(?:my\\s+)?(?:phone|spotify)$", "").replaceAll("[.]+$", "").trim();
        return genericMusic(query) ? "" : query;
    }

    private static boolean genericMusic(String query) {
        return query.trim().toLowerCase(Locale.US).matches("(?:(?:some|a|the) )?(?:music|songs?|spotify)?");
    }

    private static JSONObject arg(String key, String value) {
        JSONObject args = new JSONObject();
        try {
            args.put(key, value);
        } catch (JSONException ignored) {
            return args;
        }
        return args;
    }

    private static JSONArray one(String tool, JSONObject args) {
        JSONArray steps = new JSONArray();
        JSONObject step = new JSONObject();
        try {
            step.put("device", "phone");
            step.put("tool", tool);
            step.put("args", args);
            steps.put(step);
        } catch (JSONException ignored) {
            return steps;
        }
        return steps;
    }
}
