package com.marc.island;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

/** Local mirror of Marc run events for the Activity screen. */
final class ActivityStore {
    interface Listener {
        void onActivity();
    }

    private static final String PREFS = "marc_activity";
    private static final String KEY = "runs";
    private static final int MAX_RUNS = 40;
    private static Listener listener;
    private static String activeRunId = "";

    private ActivityStore() {
    }

    static void setListener(Listener next) {
        listener = next;
    }

    static synchronized String activeRunId() {
        return activeRunId == null ? "" : activeRunId;
    }

    static void heard(Context context, String text) {
        String id = UUID.randomUUID().toString().substring(0, 8);
        activeRunId = id;
        JSONObject run = new JSONObject();
        try {
            run.put("id", id);
            run.put("at", System.currentTimeMillis());
            run.put("text", text == null ? "" : text);
            run.put("phase", "heard");
            run.put("planner", "");
            run.put("source", "");
            run.put("spoken", "");
            run.put("events", new JSONArray());
            run.put("steps", new JSONArray());
            addEvent(run, "heard", text == null ? "" : text, "", "");
        } catch (Exception ignored) {
        }
        prepend(context, run);
    }

    static void planning(Context context, String planner, String target) {
        mutateActive(context, run -> {
            run.put("phase", "planning");
            run.put("planner", planner == null ? "" : planner);
            addEvent(run, "planning",
                    "Planning via " + (planner == null ? "?" : planner)
                            + (target == null || target.isEmpty() || "auto".equals(target) ? "" : " → " + target),
                    "", "");
        });
    }

    static void localPlan(Context context, String source, String spoken, JSONArray steps) {
        mutateActive(context, run -> {
            run.put("phase", "local");
            run.put("planner", source == null ? "LocalMarc" : source);
            run.put("source", source == null ? "local" : source);
            run.put("spoken", spoken == null ? "" : spoken);
            JSONArray out = new JSONArray();
            if (steps != null) {
                for (int i = 0; i < steps.length(); i++) {
                    JSONObject step = steps.optJSONObject(i);
                    if (step == null) {
                        continue;
                    }
                    JSONObject row = new JSONObject();
                    row.put("device", "phone");
                    row.put("tool", step.optString("tool"));
                    row.put("status", "ok");
                    row.put("message", "");
                    out.put(row);
                    addEvent(run, "step_ok", step.optString("tool"), "phone", "");
                }
            }
            run.put("steps", out);
            addEvent(run, "spoken", spoken == null ? "" : spoken, "", "");
            run.put("phase", "done");
            addEvent(run, "done", "", "", "");
        });
        activeRunId = "";
    }

    static void fromResponse(Context context, JSONObject response) {
        if (response == null) {
            return;
        }
        mutateActive(context, run -> {
            String planner = response.optString("planner", run.optString("planner", "hermes"));
            String source = response.optString("source", "");
            run.put("planner", planner);
            run.put("source", source);
            run.put("spoken", response.optString("spoken", ""));
            run.put("phase", "planned");
            addEvent(run, "planned",
                    source.isEmpty() ? planner : planner + " · " + source,
                    "", "");
            JSONArray steps = new JSONArray();
            JSONArray runSteps = response.optJSONArray("steps_run");
            if (runSteps != null) {
                for (int i = 0; i < runSteps.length(); i++) {
                    JSONObject item = runSteps.optJSONObject(i);
                    if (item == null) {
                        continue;
                    }
                    JSONObject row = new JSONObject();
                    String device = item.optString("device", item.optString("machine", ""));
                    String tool = item.optString("tool", item.optString("name", ""));
                    boolean ok = item.optBoolean("ok", true);
                    String message = item.optString("message", item.optString("result", ""));
                    row.put("device", device);
                    row.put("tool", tool);
                    row.put("status", ok ? "ok" : "fail");
                    row.put("message", message);
                    steps.put(row);
                    addEvent(run, ok ? "step_ok" : "step_fail", tool, device, message);
                }
            } else {
                JSONArray phone = response.optJSONArray("phone_steps");
                if (phone != null) {
                    for (int i = 0; i < phone.length(); i++) {
                        JSONObject step = phone.optJSONObject(i);
                        if (step == null) {
                            continue;
                        }
                        JSONObject row = new JSONObject();
                        row.put("device", "phone");
                        row.put("tool", step.optString("tool"));
                        row.put("status", "queued");
                        row.put("message", "");
                        steps.put(row);
                        addEvent(run, "step_start", step.optString("tool"), "phone", "");
                    }
                }
                JSONArray machines = response.optJSONArray("machines");
                if (machines != null) {
                    for (int i = 0; i < machines.length(); i++) {
                        String machine = machines.optString(i);
                        if ("phone".equals(machine) || machine.isEmpty()) {
                            continue;
                        }
                        JSONObject row = new JSONObject();
                        row.put("device", machine);
                        row.put("tool", "run");
                        row.put("status", "ok");
                        row.put("message", "");
                        steps.put(row);
                        addEvent(run, "step_ok", "run", machine, "");
                    }
                }
            }
            run.put("steps", steps);
            addEvent(run, "spoken", response.optString("spoken", ""), "", "");
            run.put("phase", "done");
            addEvent(run, "done", "", "", "");
        });
        activeRunId = "";
    }

    static void fail(Context context, String message) {
        mutateActive(context, run -> {
            run.put("phase", "fail");
            run.put("spoken", message == null ? "" : message);
            addEvent(run, "fail", message == null ? "" : message, "", "");
        });
        activeRunId = "";
    }

    static void mergeAgent(Context context, JSONObject agent) {
        if (agent == null) {
            return;
        }
        String spoken = agent.optString("spoken", "");
        JSONArray stepsRun = agent.optJSONArray("steps_run");
        if ((spoken == null || spoken.isEmpty()) && (stepsRun == null || stepsRun.length() == 0)) {
            return;
        }
        List<JSONObject> runs = load(context);
        if (!runs.isEmpty()) {
            JSONObject first = runs.get(0);
            long age = System.currentTimeMillis() - first.optLong("at", 0);
            if (age < 15_000L && spoken.equals(first.optString("spoken"))) {
                return;
            }
        }
        JSONObject run = new JSONObject();
        try {
            run.put("id", "srv-" + System.currentTimeMillis());
            run.put("at", agent.optLong("at", System.currentTimeMillis()));
            run.put("text", "");
            run.put("phase", "done");
            run.put("planner", agent.optString("planner", "hermes"));
            run.put("source", agent.optString("source", ""));
            run.put("spoken", spoken);
            run.put("events", new JSONArray());
            JSONArray steps = new JSONArray();
            if (stepsRun != null) {
                for (int i = 0; i < stepsRun.length(); i++) {
                    JSONObject item = stepsRun.optJSONObject(i);
                    if (item == null) {
                        continue;
                    }
                    JSONObject row = new JSONObject();
                    row.put("device", item.optString("device", item.optString("machine", "")));
                    row.put("tool", item.optString("tool", item.optString("name", "")));
                    String status = item.optString("status", "");
                    if (status.isEmpty()) {
                        status = item.optBoolean("ok", true) ? "ok" : "fail";
                    }
                    row.put("status", status);
                    row.put("message", item.optString("message", ""));
                    steps.put(row);
                }
            }
            run.put("steps", steps);
            addEvent(run, "spoken", spoken, "", "");
        } catch (Exception ignored) {
        }
        prepend(context, run);
    }

    static List<JSONObject> snapshot(Context context) {
        return load(context);
    }

    private interface Mutator {
        void apply(JSONObject run) throws Exception;
    }

    private static void mutateActive(Context context, Mutator mutator) {
        List<JSONObject> runs = load(context);
        if (runs.isEmpty() || activeRunId.isEmpty()) {
            return;
        }
        JSONObject active = runs.get(0);
        if (!activeRunId.equals(active.optString("id"))) {
            return;
        }
        try {
            mutator.apply(active);
        } catch (Exception ignored) {
        }
        save(context, runs);
        notifyListener();
    }

    private static void addEvent(JSONObject run, String type, String text, String device, String message)
            throws Exception {
        JSONArray events = run.optJSONArray("events");
        if (events == null) {
            events = new JSONArray();
            run.put("events", events);
        }
        JSONObject event = new JSONObject();
        event.put("at", System.currentTimeMillis());
        event.put("type", type);
        event.put("text", text == null ? "" : text);
        event.put("device", device == null ? "" : device);
        event.put("message", message == null ? "" : message);
        events.put(event);
    }

    private static void prepend(Context context, JSONObject run) {
        List<JSONObject> runs = load(context);
        runs.add(0, run);
        while (runs.size() > MAX_RUNS) {
            runs.remove(runs.size() - 1);
        }
        save(context, runs);
        notifyListener();
    }

    private static List<JSONObject> load(Context context) {
        List<JSONObject> out = new ArrayList<>();
        SharedPreferences prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        try {
            JSONArray arr = new JSONArray(prefs.getString(KEY, "[]"));
            for (int i = 0; i < arr.length(); i++) {
                JSONObject row = arr.optJSONObject(i);
                if (row != null) {
                    out.add(row);
                }
            }
        } catch (Exception ignored) {
        }
        return out;
    }

    private static void save(Context context, List<JSONObject> runs) {
        JSONArray arr = new JSONArray();
        for (JSONObject run : runs) {
            arr.put(run);
        }
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .edit()
                .putString(KEY, arr.toString())
                .apply();
    }

    private static void notifyListener() {
        Listener next = listener;
        if (next != null) {
            next.onActivity();
        }
    }
}
