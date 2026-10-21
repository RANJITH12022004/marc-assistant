package com.marc.island;

import android.content.Intent;
import android.util.Log;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.inputmethod.EditorInfo;
import android.widget.ArrayAdapter;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.TextView;

import androidx.appcompat.app.AppCompatActivity;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.List;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.regex.Pattern;

/** Status home, with the chat one tap away. The pill on the camera stays separate. */
public class IslandActivity extends AppCompatActivity {
    private static final int AMBER = 0xFFE8B15A;
    private static final int GREEN = 0xFF30D158;
    private static final int ORANGE = 0xFFFF9F0A;
    private static final int RED = 0xFFFF453A;
    private static final int MUTED = 0x99EBEBF5;
    private static final int INK = 0xFFF5F5F7;

    private static boolean visible;
    private ListView list;
    private View empty;
    private ArrayAdapter<ChatStore.Line> adapter;
    private View statusPage;
    private View chatPage;
    private TextView tabStatus;
    private TextView tabChat;
    private TextView presenceLabel;
    private View presenceDot;
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
    private View detailScrim;
    private TextView detailTitle;
    private TextView detailBody;
    private JSONObject lastWrap;
    private MarcClient client;
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private final Handler poll = new Handler(Looper.getMainLooper());
    private boolean resumed;
    private boolean showingStatus = true;
    private boolean reading;
    private String chatTarget = "auto";
    private TextView targetAuto;
    private TextView targetPhone;
    private TextView targetLaptop;
    private TextView targetServer;
    private final Runnable tick = this::refreshStatus;
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
        statusPage = findViewById(R.id.status_page);
        chatPage = findViewById(R.id.chat_page);
        tabStatus = findViewById(R.id.tab_status);
        tabChat = findViewById(R.id.tab_chat);
        presenceLabel = findViewById(R.id.presence_label);
        presenceDot = findViewById(R.id.presence_dot);
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
        detailScrim = findViewById(R.id.detail_scrim);
        detailTitle = findViewById(R.id.detail_title);
        detailBody = findViewById(R.id.detail_body);
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
        client = new MarcClient(getString(R.string.pi_base_url), getString(R.string.marc_token));
        tabStatus.setOnClickListener(v -> showStatusTab());
        tabChat.setOnClickListener(v -> showChatTab());
        showStatusTab();
        paintAway(null);

        empty = findViewById(R.id.empty_chat);
        list = findViewById(R.id.chat_list);

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
                float r = 18 * density;
                bg.setCornerRadius(r);
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

        findViewById(R.id.listen_button).setOnClickListener(v -> {
            Intent intent = new Intent(this, IslandService.class);
            intent.setAction(IslandService.ACTION_LISTEN);
            startService(intent);
        });

        targetAuto = findViewById(R.id.target_auto);
        targetPhone = findViewById(R.id.target_phone);
        targetLaptop = findViewById(R.id.target_laptop);
        targetServer = findViewById(R.id.target_server);
        if (targetAuto != null) {
            targetAuto.setOnClickListener(v -> setChatTarget("auto"));
        }
        if (targetPhone != null) {
            targetPhone.setOnClickListener(v -> setChatTarget("phone"));
        }
        if (targetLaptop != null) {
            targetLaptop.setOnClickListener(v -> setChatTarget("laptop"));
        }
        if (targetServer != null) {
            targetServer.setOnClickListener(v -> setChatTarget("server"));
        }
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

        startMarc(getIntent());
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
        IslandService.setVoiceListener(voicePhase::setText);
        ChatStore.setListener(this::render);
        render();
        refreshStatus();
    }

    @Override
    protected void onPause() {
        resumed = false;
        visible = false;
        IslandService.setVoiceListener(null);
        poll.removeCallbacks(tick);
        ChatStore.setListener(null);
        super.onPause();
    }

    private void showStatusTab() {
        showingStatus = true;
        statusPage.setVisibility(View.VISIBLE);
        chatPage.setVisibility(View.GONE);
        tabStatus.setTextColor(AMBER);
        tabChat.setTextColor(0x66EBEBF5);
        refreshStatus();
    }

    private void showChatTab() {
        showingStatus = false;
        statusPage.setVisibility(View.GONE);
        chatPage.setVisibility(View.VISIBLE);
        tabChat.setTextColor(AMBER);
        tabStatus.setTextColor(0x66EBEBF5);
        poll.removeCallbacks(tick);
    }

    private void refreshStatus() {
        poll.removeCallbacks(tick);
        if (!resumed || !showingStatus) {
            return;
        }
        if (reading) {
            poll.postDelayed(tick, 3000);
            return;
        }
        reading = true;
        io.execute(() -> {
            JSONObject wrap = null;
            try {
                wrap = client.status();
            } catch (Exception exc) {
                Log.w("MarcIsland", "status " + exc.getMessage());
            }
            JSONObject shown = wrap;
            runOnUiThread(() -> {
                reading = false;
                if (shown == null) {
                    if (lastWrap == null) {
                        paintAway(null);
                    }
                } else {
                    lastWrap = shown;
                    paintStatus(shown);
                }
                if (resumed && showingStatus) {
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
        Log.i("MarcIsland", "status cpu=" + status.optDouble("cpu_pct") + " temp=" + temp + " rtt=" + wrap.optLong("rtt_ms") + " age=" + age);
        if (!fresh) {
            setPresence("Away", MUTED);
        } else if (temp >= 80) {
            setPresence("Hot", RED);
        } else {
            setPresence("Here", AMBER);
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

    private static String size(long bytes) {
        if (bytes >= 1_073_741_824L) {
            return String.format(Locale.US, "%.1f GB", bytes / 1_073_741_824.0);
        }
        return String.format(Locale.US, "%.0f MB", bytes / 1_048_576.0);
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
            body.append("Supply ").append(status.optString("supply")).append("\n");
            body.append(String.format(Locale.US, "Throttle 0x%x", status.optInt("throttled")));
        } else if ("RAM".equals(which)) {
            JSONObject mem = status.optJSONObject("mem");
            long total = mem == null ? 0 : mem.optLong("total");
            long used = mem == null ? 0 : mem.optLong("used");
            long avail = mem == null ? 0 : mem.optLong("avail");
            body.append("Used ").append(size(used)).append("\n");
            body.append("Available ").append(size(avail)).append("\n");
            body.append("Total ").append(size(total));
        } else if ("STORE".equals(which)) {
            JSONArray volumes = status.optJSONArray("volumes");
            boolean pendrive = false;
            if (volumes == null || volumes.length() == 0) {
                body.append("No disk");
            } else {
                for (int i = 0; i < volumes.length(); i++) {
                    JSONObject volume = volumes.optJSONObject(i);
                    if (volume == null) {
                        continue;
                    }
                    if (volume.optBoolean("removable") || "pendrive".equals(volume.optString("kind"))) {
                        pendrive = true;
                    }
                    if (body.length() > 0) {
                        body.append("\n");
                    }
                    body.append(volume.optString("name")).append("  ");
                    if (volume.has("readable") && !volume.optBoolean("readable")) {
                        body.append("unreadable");
                    } else {
                        body.append(size(volume.optLong("used"))).append(" / ")
                                .append(size(volume.optLong("total")));
                    }
                }
                if (!pendrive) {
                    body.append("\n\nNo pendrive connected");
                }
            }
        } else {
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

    @Override
    public void onBackPressed() {
        if (detailScrim != null && detailScrim.getVisibility() == View.VISIBLE) {
            detailScrim.setVisibility(View.GONE);
            return;
        }
        super.onBackPressed();
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
        try {
            startService(intent);
        } catch (RuntimeException exc) {
            composer.setText(text);
            composer.setSelection(text.length());
        }
    }

    private void startMarc(Intent intent) {
        Intent service = new Intent(this, IslandService.class);
        if (intent != null && intent.hasExtra("text")) {
            service.putExtra("text", intent.getStringExtra("text"));
        }
        startService(service);
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
