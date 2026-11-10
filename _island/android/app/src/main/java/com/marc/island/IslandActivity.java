package com.marc.island;

import android.Manifest;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.util.Log;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.inputmethod.EditorInfo;
import android.widget.ArrayAdapter;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.RadioGroup;
import android.widget.Switch;
import android.widget.TextView;

import androidx.appcompat.app.AppCompatActivity;
import androidx.core.content.ContextCompat;
import androidx.core.view.GravityCompat;
import androidx.drawerlayout.widget.DrawerLayout;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.List;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.regex.Pattern;

/** Drawer shell: Server gauges, Chat, Activity, Setup, Settings. Pill stays on the camera hole. */
public class IslandActivity extends AppCompatActivity {
    private static final int AMBER = 0xFFE8B15A;
    private static final int GREEN = 0xFF30D158;
    private static final int ORANGE = 0xFFFF9F0A;
    private static final int RED = 0xFFFF453A;
    private static final int MUTED = 0x99EBEBF5;
    private static final int INK = 0xFFF5F5F7;

    private static boolean visible;
    private DrawerLayout drawer;
    private ListView list;
    private View empty;
    private ArrayAdapter<ChatStore.Line> adapter;
    private View statusPage;
    private View chatPage;
    private View activityPage;
    private View setupPage;
    private View settingsPage;
    private TextView pageTitle;
    private TextView navServer;
    private TextView navChat;
    private TextView navActivity;
    private TextView navSetup;
    private TextView navSettings;
    private TextView presenceLabel;
    private View presenceDot;
    private TextView linkStatus;
    private TextView agentStrip;
    private TextView activityLive;
    private View emptyActivity;
    private View activityScroll;
    private LinearLayout activityList;
    private StatusRing cpuRing;
    private StatusRing tempRing;
    private StatusRing ramRing;
    private StatusRing diskRing;
    private StatusRing linkRing;
    private TextView netLine;
    private TextView statsLine;
    private TextView svcApi;
    private TextView svcBridge;
    private TextView svcModel;
    private LinearLayout procList;
    private TextView voicePhase;
    private TextView permissionStatus;
    private View detailScrim;
    private TextView detailTitle;
    private TextView detailBody;
    private JSONObject lastWrap;
    private MarcClient client;
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private final Handler poll = new Handler(Looper.getMainLooper());
    private boolean resumed;
    private boolean reading;
    private String currentPage = "server";
    private String chatTarget = "auto";
    private TextView targetAuto;
    private TextView targetPhone;
    private TextView targetLaptop;
    private TextView targetServer;
    private final Runnable tick = this::refreshStatus;
    private final Runnable activityTick = this::refreshActivity;
    private static final Pattern ACTION = Pattern.compile(
            "(?i)\\b(?:open|launch|start|close|quit|exit|play|pause|resume|next|previous|stop|"
                    + "send|call|dial|text|whatsapp|instagram|search|volume|mute|restart|docker|"
                    + "containers|ollama|n8n|ls|files|journal|install|shell|bash|directory|folder)\\b|"
                    + "\\bon\\s+(?:my\\s+|the\\s+)?(?:laptop|computer|pc|phone|mobile|server|linux)\\b|"
                    + "/home/rox");

    static boolean isVisible() {
        return visible;
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_home);

        drawer = findViewById(R.id.drawer_layout);
        pageTitle = findViewById(R.id.page_title);
        statusPage = findViewById(R.id.status_page);
        chatPage = findViewById(R.id.chat_page);
        activityPage = findViewById(R.id.activity_page);
        setupPage = findViewById(R.id.setup_page);
        settingsPage = findViewById(R.id.settings_page);
        navServer = findViewById(R.id.nav_server);
        navChat = findViewById(R.id.nav_chat);
        navActivity = findViewById(R.id.nav_activity);
        navSetup = findViewById(R.id.nav_setup);
        navSettings = findViewById(R.id.nav_settings);
        presenceLabel = findViewById(R.id.presence_label);
        presenceDot = findViewById(R.id.presence_dot);
        linkStatus = findViewById(R.id.link_status);
        agentStrip = findViewById(R.id.agent_strip);
        activityLive = findViewById(R.id.activity_live);
        emptyActivity = findViewById(R.id.empty_activity);
        activityScroll = findViewById(R.id.activity_scroll);
        activityList = findViewById(R.id.activity_list);
        cpuRing = findViewById(R.id.ring_cpu);
        tempRing = findViewById(R.id.ring_temp);
        ramRing = findViewById(R.id.ring_ram);
        diskRing = findViewById(R.id.ring_disk);
        linkRing = findViewById(R.id.ring_link);
        netLine = findViewById(R.id.net_line);
        statsLine = findViewById(R.id.stats_line);
        svcApi = findViewById(R.id.svc_api);
        svcBridge = findViewById(R.id.svc_bridge);
        svcModel = findViewById(R.id.svc_model);
        procList = findViewById(R.id.proc_list);
        voicePhase = findViewById(R.id.voice_phase);
        permissionStatus = findViewById(R.id.permission_status);
        detailScrim = findViewById(R.id.detail_scrim);
        detailTitle = findViewById(R.id.detail_title);
        detailBody = findViewById(R.id.detail_body);
        empty = findViewById(R.id.empty_chat);
        list = findViewById(R.id.chat_list);

        client = new MarcClient(getString(R.string.pi_base_url), getString(R.string.marc_token));

        findViewById(R.id.menu_button).setOnClickListener(v -> drawer.openDrawer(GravityCompat.START));
        navServer.setOnClickListener(v -> showPage("server"));
        navChat.setOnClickListener(v -> showPage("chat"));
        if (navActivity != null) {
            navActivity.setOnClickListener(v -> showPage("activity"));
        }
        navSetup.setOnClickListener(v -> showPage("setup"));
        navSettings.setOnClickListener(v -> showPage("settings"));

        detailScrim.setOnClickListener(v -> detailScrim.setVisibility(View.GONE));
        findViewById(R.id.detail_card).setOnClickListener(v -> { });
        cpuRing.setOnLongClickListener(v -> openDetail("CPU"));
        tempRing.setOnLongClickListener(v -> openDetail("TEMP"));
        ramRing.setOnLongClickListener(v -> openDetail("RAM"));
        diskRing.setOnLongClickListener(v -> openDetail("STORE"));
        linkRing.setOnLongClickListener(v -> openDetail("LINK"));
        ramRing.setSatellite(true);
        diskRing.setSatellite(true);
        linkRing.setSatellite(true);
        svcApi.setOnClickListener(v -> controlService("api"));
        svcBridge.setOnClickListener(v -> controlService("bridge"));
        svcModel.setOnClickListener(v -> controlService("ollama"));

        final float density = getResources().getDisplayMetrics().density;
        final int padH = Math.round(14 * density);
        final int padV = Math.round(10 * density);
        adapter = new ArrayAdapter<ChatStore.Line>(this, 0) {
            @Override
            public View getView(int position, View convert, ViewGroup parent) {
                LinearLayout container;
                TextView bubble;
                if (convert instanceof LinearLayout) {
                    container = (LinearLayout) convert;
                    bubble = (TextView) container.getChildAt(0);
                } else {
                    container = new LinearLayout(IslandActivity.this);
                    container.setOrientation(LinearLayout.HORIZONTAL);
                    bubble = new TextView(IslandActivity.this);
                    bubble.setTextSize(16);
                    bubble.setLineSpacing(0f, 1.15f);
                    bubble.setMaxWidth(Math.round(280 * density));
                    container.addView(bubble);
                }
                ChatStore.Line line = getItem(position);
                boolean isUser = line != null && line.user;
                bubble.setText(line == null ? "" : line.text);
                bubble.setTextColor(INK);
                bubble.setPadding(padH, padV, padH, padV);
                GradientDrawable bg = new GradientDrawable();
                bg.setCornerRadius(18 * density);
                if (isUser) {
                    container.setGravity(Gravity.END);
                    bg.setColor(0x2EFFFFFF);
                    bg.setStroke(Math.round(0.6f * density), 0x33FFFFFF);
                } else {
                    container.setGravity(Gravity.START);
                    bg.setColor(0x14FFFFFF);
                    bg.setStroke(Math.round(0.6f * density), 0x24FFFFFF);
                }
                bubble.setBackground(bg);
                return container;
            }
        };
        list.setAdapter(adapter);

        wireChat();
        wireSetup();
        wireSettings();
        paintAway(null);
        showPage("server");
        startMarc(getIntent());
    }

    private void wireChat() {
        findViewById(R.id.listen_button).setOnClickListener(v -> startListen());
        targetAuto = findViewById(R.id.target_auto);
        targetPhone = findViewById(R.id.target_phone);
        targetLaptop = findViewById(R.id.target_laptop);
        targetServer = findViewById(R.id.target_server);
        targetAuto.setOnClickListener(v -> setChatTarget("auto"));
        targetPhone.setOnClickListener(v -> setChatTarget("phone"));
        targetLaptop.setOnClickListener(v -> setChatTarget("laptop"));
        targetServer.setOnClickListener(v -> setChatTarget("server"));
        setChatTarget("auto");
        EditText composer = findViewById(R.id.composer);
        findViewById(R.id.send_button).setOnClickListener(v -> sendTyped(composer));
        composer.setOnEditorActionListener((view, actionId, event) -> {
            if (actionId == EditorInfo.IME_ACTION_SEND) {
                sendTyped(composer);
                return true;
            }
            return false;
        });
    }

    private void wireSetup() {
        View overlay = findViewById(R.id.enable_overlay);
        if (overlay != null) {
            overlay.setOnClickListener(v -> startActivity(new Intent(
                    Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                    Uri.parse("package:" + getPackageName()))));
        }
        View a11y = findViewById(R.id.enable_accessibility);
        if (a11y != null) {
            a11y.setOnClickListener(v ->
                    startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)));
        }
        View listenSetup = findViewById(R.id.listen_setup);
        if (listenSetup != null) {
            listenSetup.setOnClickListener(v -> startListen());
        }
        View water = findViewById(R.id.play_water);
        if (water != null) {
            water.setOnClickListener(v -> {
                Intent intent = new Intent(this, IslandService.class);
                intent.setAction(IslandService.ACTION_PLAY_WATER);
                startOverlay(intent);
            });
        }
    }

    private void wireSettings() {
        View saveKey = findViewById(R.id.save_key);
        EditText apiKey = findViewById(R.id.api_key);
        if (saveKey != null && apiKey != null) {
            saveKey.setOnClickListener(v -> {
                String raw = apiKey.getText() == null ? "" : apiKey.getText().toString();
                if (raw.trim().isEmpty()) {
                    return;
                }
                MuseStore.saveKey(this, raw);
                apiKey.setText("");
                paintSettings();
            });
        }
        RadioGroup mode = findViewById(R.id.marc_mode);
        if (mode != null) {
            mode.setOnCheckedChangeListener((group, checkedId) ->
                    MuseStore.saveMode(this, checkedId == R.id.mode_live ? "live" : "sandbox"));
        }
        Switch driving = findViewById(R.id.driving_toggle);
        if (driving != null) {
            driving.setOnCheckedChangeListener((button, on) -> MuseStore.saveDriving(this, on));
        }
        View spark = findViewById(R.id.chip_spark);
        View wonder = findViewById(R.id.chip_wonder);
        View voice = findViewById(R.id.chip_voice);
        if (spark != null) {
            spark.setOnClickListener(v -> {
                MuseStore.saveModelSlot(this, "spark");
                paintSettings();
            });
        }
        if (wonder != null) {
            wonder.setOnClickListener(v -> {
                MuseStore.saveModelSlot(this, "wonder");
                paintSettings();
            });
        }
        if (voice != null) {
            voice.setOnClickListener(v -> {
                MuseStore.saveModelSlot(this, "voice");
                paintSettings();
            });
        }
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        startMarc(intent);
    }

    @Override
    protected void onResume() {
        super.onResume();
        resumed = true;
        visible = true;
        IslandService.setVoiceListener(phase -> {
            if (voicePhase != null) {
                voicePhase.setText(phase);
            }
        });
        ChatStore.setListener(this::render);
        ActivityStore.setListener(this::paintActivity);
        render();
        paintActivity();
        paintPermissions();
        paintSettings();
        if ("server".equals(currentPage)) {
            refreshStatus();
        }
        if ("activity".equals(currentPage)) {
            refreshActivity();
        }
    }

    @Override
    protected void onPause() {
        resumed = false;
        visible = false;
        IslandService.setVoiceListener(null);
        poll.removeCallbacks(tick);
        poll.removeCallbacks(activityTick);
        ChatStore.setListener(null);
        ActivityStore.setListener(null);
        super.onPause();
    }

    @Override
    public void onBackPressed() {
        if (drawer != null && drawer.isDrawerOpen(GravityCompat.START)) {
            drawer.closeDrawer(GravityCompat.START);
            return;
        }
        if (detailScrim != null && detailScrim.getVisibility() == View.VISIBLE) {
            detailScrim.setVisibility(View.GONE);
            return;
        }
        super.onBackPressed();
    }

    private void showPage(String page) {
        currentPage = page == null ? "server" : page;
        if (drawer != null && drawer.isDrawerOpen(GravityCompat.START)) {
            drawer.closeDrawer(GravityCompat.START);
        }
        statusPage.setVisibility("server".equals(currentPage) ? View.VISIBLE : View.GONE);
        chatPage.setVisibility("chat".equals(currentPage) ? View.VISIBLE : View.GONE);
        if (activityPage != null) {
            activityPage.setVisibility("activity".equals(currentPage) ? View.VISIBLE : View.GONE);
        }
        setupPage.setVisibility("setup".equals(currentPage) ? View.VISIBLE : View.GONE);
        settingsPage.setVisibility("settings".equals(currentPage) ? View.VISIBLE : View.GONE);
        pageTitle.setText(titleFor(currentPage));
        paintNav(navServer, "server".equals(currentPage));
        paintNav(navChat, "chat".equals(currentPage));
        paintNav(navActivity, "activity".equals(currentPage));
        paintNav(navSetup, "setup".equals(currentPage));
        paintNav(navSettings, "settings".equals(currentPage));
        poll.removeCallbacks(tick);
        poll.removeCallbacks(activityTick);
        if ("server".equals(currentPage)) {
            refreshStatus();
        }
        if ("activity".equals(currentPage)) {
            paintActivity();
            refreshActivity();
        }
        if ("setup".equals(currentPage)) {
            paintPermissions();
        }
        if ("settings".equals(currentPage)) {
            paintSettings();
        }
    }

    private static String titleFor(String page) {
        if ("chat".equals(page)) {
            return "Chat";
        }
        if ("activity".equals(page)) {
            return "Activity";
        }
        if ("setup".equals(page)) {
            return "Setup";
        }
        if ("settings".equals(page)) {
            return "Settings";
        }
        return "Server";
    }

    private static void paintNav(TextView item, boolean on) {
        if (item == null) {
            return;
        }
        item.setTextColor(on ? AMBER : MUTED);
        item.setBackgroundColor(on ? 0x14E8B15A : 0x00000000);
    }

    private void refreshStatus() {
        poll.removeCallbacks(tick);
        if (!resumed || !"server".equals(currentPage)) {
            return;
        }
        if (reading) {
            poll.postDelayed(tick, 3000);
            return;
        }
        reading = true;
        if (linkStatus != null && lastWrap == null) {
            linkStatus.setText("Connecting…");
        }
        io.execute(() -> {
            JSONObject wrap = null;
            String error = null;
            try {
                wrap = client.status();
            } catch (Exception exc) {
                error = exc.getMessage() == null ? "Can't reach Marc" : exc.getMessage();
                Log.w("MarcIsland", "status " + error);
            }
            JSONObject shown = wrap;
            String fail = error;
            runOnUiThread(() -> {
                reading = false;
                if (shown == null) {
                    if (lastWrap == null) {
                        paintAway(null);
                    }
                    if (linkStatus != null) {
                        linkStatus.setText(fail == null ? "No reading" : fail);
                        linkStatus.setTextColor(ORANGE);
                    }
                } else {
                    lastWrap = shown;
                    paintStatus(shown);
                }
                if (resumed && "server".equals(currentPage)) {
                    poll.postDelayed(tick, 3000);
                }
            });
        });
    }

    private void paintAway(JSONObject stale) {
        setPresence("Away", MUTED);
        if (stale == null) {
            cpuRing.setReading(0f, "—", "CPU", MUTED);
            tempRing.setReading(0f, "—", "Temp", MUTED);
            ramRing.setReading(0f, "—", "RAM", MUTED);
            diskRing.setReading(0f, "—", "Storage", MUTED);
            linkRing.setReading(0f, "—", "Link", MUTED);
            netLine.setText("");
            statsLine.setText("No reading");
            chip(svcApi, false);
            chip(svcBridge, false);
            chip(svcModel, false);
            procList.removeAllViews();
        }
    }

    private void paintStatus(JSONObject wrap) {
        JSONObject status = wrap.optJSONObject("status");
        long age = wrap.optLong("age_ms", 0);
        if (status == null) {
            paintAway(null);
            return;
        }
        boolean fresh = age <= 15000;
        double temp = status.optDouble("temp_c", 0);
        long rtt = wrap.optLong("rtt_ms");
        Log.i("MarcIsland", "status cpu=" + status.optDouble("cpu_pct") + " temp=" + temp
                + " rtt=" + rtt + " age=" + age);
        if (linkStatus != null) {
            linkStatus.setText("Live · " + rtt + " ms");
            linkStatus.setTextColor(GREEN);
        }
        if (!fresh) {
            setPresence("Away", MUTED);
        } else if (temp >= 80) {
            setPresence("Hot", RED);
        } else {
            setPresence("Online", AMBER);
        }
        double cpu = status.optDouble("cpu_pct", 0);
        cpuRing.setReading((float) (cpu / 100.0), pct(cpu), "CPU", heat(cpu, 60, 85));
        float tempFrac = (float) ((temp - 40.0) / 60.0);
        tempRing.setReading(tempFrac, Math.round(temp) + "°", "TEMP", heat(temp, 70, 80));
        JSONObject mem = status.optJSONObject("mem");
        long memTotal = mem == null ? 0 : mem.optLong("total");
        long memUsed = mem == null ? 0 : mem.optLong("used");
        float memFrac = memTotal <= 0 ? 0f : memUsed / (float) memTotal;
        ramRing.setReading(memFrac, pct(memFrac * 100.0), "RAM", heat(memFrac * 100.0, 70, 90));
        long diskUsed = 0;
        long diskTotal = 0;
        JSONArray storeVolumes = status.optJSONArray("volumes");
        if (storeVolumes != null) {
            for (int i = 0; i < storeVolumes.length(); i++) {
                JSONObject volume = storeVolumes.optJSONObject(i);
                if (volume == null || !volume.optBoolean("count")) {
                    continue;
                }
                diskUsed += volume.optLong("used");
                diskTotal += volume.optLong("total");
            }
        }
        if (diskTotal <= 0) {
            JSONObject disk = status.optJSONObject("disk");
            diskTotal = disk == null ? 0 : disk.optLong("total");
            diskUsed = disk == null ? 0 : disk.optLong("used");
        }
        float diskFrac = diskTotal <= 0 ? 0f : diskUsed / (float) diskTotal;
        diskRing.setReading(diskFrac, pct(diskFrac * 100.0), "STORE", heat(diskFrac * 100.0, 70, 90));
        JSONObject net = status.optJSONObject("net");
        long down = net == null ? 0 : net.optLong("rx_bps");
        long up = net == null ? 0 : net.optLong("tx_bps");
        long flow = down + up;
        float link = linkFraction(flow, fresh);
        linkRing.setReading(link, flow <= 0 ? "Idle" : rate(flow), "LINK", link >= 0.82f ? RED : AMBER);
        netLine.setText("Down " + rate(down) + "   Up " + rate(up));
        JSONArray load = status.optJSONArray("load");
        String loadText = load == null || load.length() < 3
                ? "—"
                : String.format(Locale.US, "%.2f  %.2f  %.2f", load.optDouble(0), load.optDouble(1), load.optDouble(2));
        String supply = status.optString("supply", "—");
        statsLine.setText("Load " + loadText
                + "\nUp " + uptime(status.optInt("uptime_s"))
                + "   ·   " + status.optInt("cpu_mhz") + " MHz"
                + "   ·   Core " + String.format(Locale.US, "%.2f V", status.optDouble("core_v"))
                + "   ·   Supply " + supply);
        statsLine.setTextColor("Low".equals(supply) ? RED : INK);
        JSONObject services = status.optJSONObject("services");
        chip(svcApi, services != null && services.optBoolean("api"));
        chip(svcBridge, services != null && services.optBoolean("bridge"));
        chip(svcModel, services != null && services.optBoolean("ollama"));
        paintProcs(status.optJSONArray("procs"));
        paintAgentStrip(status.optJSONObject("agent"));
        ActivityStore.mergeAgent(this, status.optJSONObject("agent"));
        if ("activity".equals(currentPage)) {
            paintActivity();
        }
    }

    private void paintAgentStrip(JSONObject agent) {
        if (agentStrip == null) {
            return;
        }
        if (agent == null) {
            agentStrip.setVisibility(View.GONE);
            return;
        }
        String phase = agent.optString("phase", "");
        String planner = agent.optString("planner", "hermes");
        String source = agent.optString("source", "");
        JSONArray steps = agent.optJSONArray("steps_run");
        StringBuilder line = new StringBuilder();
        if ("planning".equals(phase)) {
            line.append("Planning on ").append(planner.isEmpty() ? "Hermes" : planner);
        } else if (steps != null && steps.length() > 0) {
            JSONObject last = steps.optJSONObject(steps.length() - 1);
            if (last != null) {
                line.append(last.optString("device", "?"))
                        .append(": ")
                        .append(last.optString("tool", "step"));
            }
        } else if (!agent.optString("spoken").isEmpty()) {
            line.append(agent.optString("spoken"));
        }
        if (!source.isEmpty() && line.length() > 0) {
            line.append(" · ").append(source);
        }
        if (line.length() == 0) {
            agentStrip.setVisibility(View.GONE);
            return;
        }
        agentStrip.setVisibility(View.VISIBLE);
        agentStrip.setText(line.toString());
    }

    private void refreshActivity() {
        poll.removeCallbacks(activityTick);
        if (!resumed || !"activity".equals(currentPage)) {
            return;
        }
        paintActivity();
        io.execute(() -> {
            try {
                JSONObject payload = client.activity(0L);
                JSONObject agent = payload.optJSONObject("agent");
                JSONArray runs = payload.optJSONArray("runs");
                if (agent != null) {
                    ActivityStore.mergeAgent(IslandActivity.this, agent);
                }
                if (runs != null) {
                    for (int i = Math.min(runs.length(), 8) - 1; i >= 0; i--) {
                        JSONObject run = runs.optJSONObject(i);
                        if (run == null) {
                            continue;
                        }
                        JSONObject agentLike = new JSONObject();
                        agentLike.put("spoken", run.optString("spoken"));
                        agentLike.put("planner", run.optString("planner"));
                        agentLike.put("source", run.optString("source"));
                        agentLike.put("at", run.optLong("at"));
                        agentLike.put("steps_run", run.optJSONArray("steps"));
                        ActivityStore.mergeAgent(IslandActivity.this, agentLike);
                    }
                }
            } catch (Exception ignored) {
            }
            runOnUiThread(() -> {
                paintActivity();
                if (resumed && "activity".equals(currentPage)) {
                    poll.postDelayed(activityTick, 1500);
                }
            });
        });
    }

    private void paintActivity() {
        if (activityList == null) {
            return;
        }
        List<JSONObject> runs = ActivityStore.snapshot(this);
        boolean busy = !ActivityStore.activeRunId().isEmpty();
        if (activityLive != null) {
            if (busy && !runs.isEmpty()) {
                JSONObject head = runs.get(0);
                String planner = head.optString("planner", "Hermes");
                activityLive.setText("Thinking · " + (planner.isEmpty() ? "Marc" : planner)
                        + " · " + head.optString("phase", "planning"));
            } else if (!runs.isEmpty() && !runs.get(0).optString("spoken").isEmpty()) {
                activityLive.setText(runs.get(0).optString("spoken"));
            } else {
                activityLive.setText("Idle");
            }
        }
        boolean has = !runs.isEmpty();
        if (emptyActivity != null) {
            emptyActivity.setVisibility(has ? View.GONE : View.VISIBLE);
        }
        if (activityScroll != null) {
            activityScroll.setVisibility(has ? View.VISIBLE : View.GONE);
        }
        activityList.removeAllViews();
        float density = getResources().getDisplayMetrics().density;
        int pad = Math.round(12 * density);
        for (JSONObject run : runs) {
            LinearLayout card = new LinearLayout(this);
            card.setOrientation(LinearLayout.VERTICAL);
            card.setPadding(pad, pad, pad, pad);
            GradientDrawable bg = new GradientDrawable();
            bg.setColor(0x14FFFFFF);
            bg.setCornerRadius(12 * density);
            card.setBackground(bg);
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT);
            lp.bottomMargin = Math.round(10 * density);
            card.setLayoutParams(lp);

            String text = run.optString("text");
            if (!text.isEmpty()) {
                card.addView(activityLine("You · " + text, INK, 15));
            }
            String badge = run.optString("planner");
            String source = run.optString("source");
            if (!badge.isEmpty() || !source.isEmpty()) {
                String label = badge.isEmpty() ? source : (source.isEmpty() ? badge : badge + " · " + source);
                card.addView(activityLine(label, AMBER, 12));
            }
            JSONArray steps = run.optJSONArray("steps");
            if (steps != null) {
                for (int i = 0; i < steps.length(); i++) {
                    JSONObject step = steps.optJSONObject(i);
                    if (step == null) {
                        continue;
                    }
                    String status = step.optString("status", "ok");
                    int color = "fail".equals(status) ? RED : ("queued".equals(status) ? ORANGE : GREEN);
                    String row = step.optString("device", "?") + " · " + step.optString("tool", "step");
                    String message = step.optString("message");
                    if (!message.isEmpty()) {
                        row = row + " — " + message;
                    }
                    card.addView(activityLine(row, color, 13));
                }
            }
            String spoken = run.optString("spoken");
            if (!spoken.isEmpty()) {
                card.addView(activityLine(spoken, MUTED, 13));
            }
            activityList.addView(card);
        }
    }

    private TextView activityLine(String text, int color, float sizeSp) {
        TextView view = new TextView(this);
        view.setText(text);
        view.setTextColor(color);
        view.setTextSize(sizeSp);
        view.setPadding(0, Math.round(2 * getResources().getDisplayMetrics().density), 0, 0);
        return view;
    }

    private void paintProcs(JSONArray procs) {
        int count = procs == null ? 0 : Math.min(8, procs.length());
        if (procList.getChildCount() != count) {
            procList.removeAllViews();
            for (int i = 0; i < count; i++) {
                procList.addView(procRow());
            }
        }
        float density = getResources().getDisplayMetrics().density;
        int pad = Math.round(6 * density);
        for (int i = 0; i < count; i++) {
            JSONObject row = procs.optJSONObject(i);
            LinearLayout line = (LinearLayout) procList.getChildAt(i);
            TextView name = (TextView) line.getChildAt(0);
            TextView cpu = (TextView) line.getChildAt(1);
            TextView mem = (TextView) line.getChildAt(2);
            name.setText(row == null ? "" : row.optString("name"));
            cpu.setText(row == null ? "" : String.format(Locale.US, "%.0f%%", row.optDouble("cpu")));
            mem.setText(row == null ? "" : String.format(Locale.US, "%.1f%%", row.optDouble("mem")));
            line.setPadding(0, pad, 0, pad);
        }
    }

    private LinearLayout procRow() {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.addView(procText(true));
        row.addView(procText(false));
        row.addView(procText(false));
        return row;
    }

    private TextView procText(boolean flex) {
        TextView view = new TextView(this);
        view.setTextColor(INK);
        view.setTextSize(14);
        view.setSingleLine(true);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                flex ? 0 : LinearLayout.LayoutParams.WRAP_CONTENT,
                LinearLayout.LayoutParams.WRAP_CONTENT,
                flex ? 1f : 0f);
        if (!flex) {
            lp.leftMargin = Math.round(12 * getResources().getDisplayMetrics().density);
        }
        view.setLayoutParams(lp);
        return view;
    }

    private void setPresence(String label, int color) {
        presenceLabel.setText(label);
        presenceLabel.setTextColor(color == MUTED ? MUTED : INK);
        GradientDrawable dot = new GradientDrawable();
        dot.setShape(GradientDrawable.OVAL);
        dot.setColor(color);
        presenceDot.setBackground(dot);
    }

    private void chip(TextView view, boolean on) {
        GradientDrawable bg = new GradientDrawable();
        bg.setCornerRadius(16f * getResources().getDisplayMetrics().density);
        bg.setColor(on ? 0x22E8B15A : 0x14FFFFFF);
        view.setBackground(bg);
        view.setTextColor(on ? AMBER : MUTED);
    }

    private static int heat(double value, double warm, double hot) {
        if (value >= hot) {
            return RED;
        }
        if (value >= warm) {
            return ORANGE;
        }
        return GREEN;
    }

    private static String pct(double value) {
        return String.format(Locale.US, "%.0f%%", value);
    }

    private static String uptime(int seconds) {
        int minutes = Math.max(0, seconds) / 60;
        if (minutes < 60) {
            return minutes + "m";
        }
        int hours = minutes / 60;
        if (hours < 48) {
            return hours + "h " + (minutes % 60) + "m";
        }
        return (hours / 24) + "d " + (hours % 24) + "h";
    }

    private static float linkFraction(long bps, boolean connected) {
        if (!connected) {
            return 0f;
        }
        if (bps <= 0) {
            return 0.07f;
        }
        double pos = Math.log10(1.0 + bps) / Math.log10(1.0 + 1_500_000.0);
        return (float) Math.max(0.07, Math.min(1.0, pos));
    }

    private static String rate(long bps) {
        if (bps >= 1_000_000L) {
            return String.format(Locale.US, "%.1f MB/s", bps / 1_000_000.0);
        }
        if (bps >= 1000L) {
            return String.format(Locale.US, "%.0f KB/s", bps / 1000.0);
        }
        return bps + " B/s";
    }

    private boolean openDetail(String which) {
        if (lastWrap == null || lastWrap.optJSONObject("status") == null) {
            return true;
        }
        JSONObject status = lastWrap.optJSONObject("status");
        StringBuilder body = new StringBuilder();
        if ("CPU".equals(which)) {
            JSONArray load = status.optJSONArray("load");
            body.append(pct(status.optDouble("cpu_pct"))).append("\n");
            body.append(status.optInt("cpu_mhz")).append(" MHz\nLoad ");
            if (load != null && load.length() >= 3) {
                body.append(String.format(Locale.US, "%.2f   %.2f   %.2f",
                        load.optDouble(0), load.optDouble(1), load.optDouble(2)));
            }
        } else if ("TEMP".equals(which)) {
            body.append(Math.round(status.optDouble("temp_c"))).append("°\n");
            body.append(String.format(Locale.US, "Core %.2f V\n", status.optDouble("core_v")));
            body.append("Supply ").append(status.optString("supply", "—"));
        } else if ("RAM".equals(which)) {
            JSONObject mem = status.optJSONObject("mem");
            long total = mem == null ? 0 : mem.optLong("total");
            long used = mem == null ? 0 : mem.optLong("used");
            body.append(size(used)).append(" / ").append(size(total));
        } else if ("STORE".equals(which)) {
            JSONArray volumes = status.optJSONArray("volumes");
            if (volumes == null || volumes.length() == 0) {
                JSONObject disk = status.optJSONObject("disk");
                long total = disk == null ? 0 : disk.optLong("total");
                long used = disk == null ? 0 : disk.optLong("used");
                body.append(size(used)).append(" / ").append(size(total));
            } else {
                for (int i = 0; i < volumes.length(); i++) {
                    JSONObject volume = volumes.optJSONObject(i);
                    if (volume == null) {
                        continue;
                    }
                    if (body.length() > 0) {
                        body.append("\n\n");
                    }
                    body.append(volume.optString("name", "Disk")).append('\n');
                    body.append(size(volume.optLong("used"))).append(" / ")
                            .append(size(volume.optLong("total")));
                }
            }
        } else if ("LINK".equals(which)) {
            JSONObject net = status.optJSONObject("net");
            body.append(lastWrap.optLong("rtt_ms")).append(" ms\n");
            body.append("Down ").append(rate(net == null ? 0 : net.optLong("rx_bps"))).append("\n");
            body.append("Up ").append(rate(net == null ? 0 : net.optLong("tx_bps")));
        }
        detailTitle.setText(which);
        detailBody.setText(body.toString().trim());
        detailScrim.setVisibility(View.VISIBLE);
        return true;
    }

    private static String size(long bytes) {
        if (bytes >= 1_073_741_824L) {
            return String.format(Locale.US, "%.1f GB", bytes / 1_073_741_824.0);
        }
        return String.format(Locale.US, "%.0f MB", bytes / 1_048_576.0);
    }

    private void controlService(String name) {
        String text = "restart " + name + " on the server";
        Intent intent = new Intent(this, IslandService.class);
        intent.setAction(IslandService.ACTION_ASK);
        intent.putExtra("text", text);
        intent.putExtra("typed", true);
        intent.putExtra("target", "server");
        startOverlay(intent);
        showPage("chat");
    }

    private void setChatTarget(String next) {
        chatTarget = next == null || next.isEmpty() ? "auto" : next;
        paintTarget(targetAuto, "auto".equals(chatTarget));
        paintTarget(targetPhone, "phone".equals(chatTarget));
        paintTarget(targetLaptop, "laptop".equals(chatTarget));
        paintTarget(targetServer, "server".equals(chatTarget));
    }

    private static void paintTarget(TextView chip, boolean on) {
        if (chip == null) {
            return;
        }
        chip.setBackgroundColor(on ? 0x22E8B15A : 0x14FFFFFF);
        chip.setTextColor(on ? AMBER : MUTED);
    }

    private void sendTyped(EditText composer) {
        String text = composer.getText() == null ? "" : composer.getText().toString().trim();
        if (text.isEmpty()) {
            return;
        }
        composer.setText("");
        if (!ACTION.matcher(text).find()) {
            ChatStore.add(this, true, text);
            io.execute(() -> {
                try {
                    JSONObject response = client.chat(text);
                    String spoken = response.optString("spoken", "I didn't catch that.");
                    runOnUiThread(() -> ChatStore.add(this, false, spoken));
                } catch (Exception exc) {
                    String message = exc.getMessage() == null ? "Can't reach Marc" : exc.getMessage();
                    runOnUiThread(() -> ChatStore.add(this, false, message));
                }
            });
            return;
        }
        Intent intent = new Intent(this, IslandService.class);
        intent.setAction(IslandService.ACTION_ASK);
        intent.putExtra("text", text);
        intent.putExtra("typed", true);
        intent.putExtra("target", chatTarget);
        startOverlay(intent);
    }

    private void startListen() {
        Intent intent = new Intent(this, IslandService.class);
        intent.setAction(IslandService.ACTION_LISTEN);
        intent.putExtra("target", chatTarget);
        startOverlay(intent);
    }

    private void startMarc(Intent intent) {
        Intent service = new Intent(this, IslandService.class);
        if (intent != null && intent.hasExtra("text")) {
            service.putExtra("text", intent.getStringExtra("text"));
        }
        startOverlay(service);
    }

    private void startOverlay(Intent service) {
        try {
            if (Build.VERSION.SDK_INT >= 26) {
                startForegroundService(service);
            } else {
                startService(service);
            }
        } catch (RuntimeException ignored) {
        }
    }

    private void paintPermissions() {
        if (permissionStatus == null) {
            return;
        }
        boolean overlay = Settings.canDrawOverlays(this);
        boolean mic = ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
                == PackageManager.PERMISSION_GRANTED;
        permissionStatus.setText("Overlay " + (overlay ? "on" : "off")
                + "  ·  Mic " + (mic ? "on" : "off")
                + "  ·  Accessibility in system settings");
        permissionStatus.setTextColor(overlay && mic ? GREEN : ORANGE);
        if (!mic && Build.VERSION.SDK_INT >= 23) {
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, 7);
        }
    }

    private void paintSettings() {
        TextView mask = findViewById(R.id.masked_key);
        if (mask != null) {
            mask.setText(MuseStore.hasKey(this) ? MuseStore.getMask(this) : "No key saved");
        }
        RadioGroup mode = findViewById(R.id.marc_mode);
        if (mode != null) {
            mode.check("live".equals(MuseStore.getMode(this)) ? R.id.mode_live : R.id.mode_sandbox);
        }
        Switch driving = findViewById(R.id.driving_toggle);
        if (driving != null) {
            driving.setChecked(MuseStore.isDriving(this));
        }
        String slot = MuseStore.getModelSlot(this);
        paintTarget(findViewById(R.id.chip_spark), "spark".equals(slot));
        paintTarget(findViewById(R.id.chip_wonder), "wonder".equals(slot));
        paintTarget(findViewById(R.id.chip_voice), "voice".equals(slot));
    }

    private void render() {
        List<ChatStore.Line> lines = ChatStore.snapshot(this);
        adapter.clear();
        adapter.addAll(lines);
        boolean hasLines = !lines.isEmpty();
        empty.setVisibility(hasLines ? View.GONE : View.VISIBLE);
        list.setVisibility(hasLines ? View.VISIBLE : View.GONE);
        if (hasLines) {
            list.setSelection(lines.size() - 1);
        }
    }
}
