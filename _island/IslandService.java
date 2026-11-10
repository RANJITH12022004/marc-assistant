package com.marc.island;

import android.accessibilityservice.AccessibilityService;
import android.app.KeyguardManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.content.pm.ServiceInfo;
import android.graphics.PixelFormat;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.annotation.SuppressLint;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.app.PendingIntent;
import android.os.PowerManager;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.media.AudioAttributes;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;
import android.telephony.PhoneStateListener;
import android.telephony.TelephonyCallback;
import android.telephony.TelephonyManager;
import android.util.Log;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;
import android.view.animation.DecelerateInterpolator;
import android.view.animation.OvershootInterpolator;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import android.os.SystemClock;

import java.lang.ref.WeakReference;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/**
 * Dynamic Island locked to the Nothing Phone (3a) Lite front camera.
 * Uses RenderThread scale animations (no 60fps WindowManager surface reallocations)
 * and preserves partial speech hypotheses so SpeechRecognizer never drops spoken words.
 */
public class IslandService extends Service {
    static final String ACTION_LISTEN = "com.marc.island.LISTEN";
    static final String ACTION_ASK = "com.marc.island.ASK";
    static final String ACTION_PLAY_WATER = "com.marc.island.PLAY_WATER";
    private static final String TAG = "MarcIsland";
    /** Circle center from the display cutout path: M540,68.6 radius 21.5 (device px). */
    private static final float CAMERA_X_PX = IslandTouch.CAMERA_X;
    private static final float CAMERA_Y_PX = IslandTouch.CAMERA_Y;
    private static final long HYDRATION_HOUR_MS = 60L * 60L * 1000L;
    private static final long HYDRATION_SNOOZE_MS = 15L * 60L * 1000L;
    private static final long HYDRATION_FIRST_MS = 8000L;

    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private final ScheduledExecutorService inboxWatch = Executors.newSingleThreadScheduledExecutor();
    private boolean inboxStarted;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private int lineToken;
    private Runnable clearLine;
    private final BroadcastReceiver screenReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            String action = intent == null ? null : intent.getAction();
            // Lock screen wake: app overlays sit under the keyguard — promote to a11y.
            if (Intent.ACTION_SCREEN_ON.equals(action) || Intent.ACTION_USER_PRESENT.equals(action)) {
                ensurePillForLockScreen();
            } else {
                ensurePill();
            }
            applyScreen();
            if (Intent.ACTION_USER_PRESENT.equals(action) && backdropView != null) {
                backdropView.showFace();
            }
            if (Intent.ACTION_USER_PRESENT.equals(action) || Intent.ACTION_SCREEN_ON.equals(action)) {
                maybeHydration();
            }
            if (Intent.ACTION_SCREEN_OFF.equals(action)
                    && heroView != null && heroView.isPlaying()) {
                dropHero();
                hydrationPending = true;
            }
        }
    };
    private FrameLayout pill;
    private HydrationHeroView heroView;
    private View heroHit;
    private IslandBackdropView backdropView;
    private IslandWaveView waveView;
    private LinearLayout iconRow;
    private TextView lineView;
    private TextView yesView;
    private TextView noView;
    private WindowManager windowManager;
    private SpeechRecognizer recognizer;
    private TextToSpeech tts;
    private boolean ttsReady;
    private String pendingSpeech;
    private String phase = "Idle";
    private static VoiceListener voiceListener;

    interface VoiceListener {
        void onPhase(String phase);
    }

    static void setVoiceListener(VoiceListener listener) {
        voiceListener = listener;
    }

    private void watchInbox() {
        if (inboxStarted) {
            return;
        }
        inboxStarted = true;
        inboxWatch.scheduleWithFixedDelay(this::pullInbox, 1, 2, TimeUnit.SECONDS);
    }

    private void pullInbox() {
        MarcClient current = client;
        if (current == null) {
            return;
        }
        try {
            JSONObject wrap = current.takeStatus();
            JSONObject status = wrap.optJSONObject("status");
            JSONArray inbox = status == null ? null : status.optJSONArray("inbox");
            if (inbox != null && inbox.length() > 0) {
                deliver(inbox);
            }
        } catch (Exception exc) {
            Log.w(TAG, "inbox " + exc.getMessage());
        }
    }

    static void deliver(JSONArray inbox) {
        IslandService service = running == null ? null : running.get();
        if (service == null || inbox == null) {
            return;
        }
        service.mainHandler.post(() -> {
            for (int i = 0; i < inbox.length(); i++) {
                JSONObject item = inbox.optJSONObject(i);
                if (item != null) {
                    service.show(item);
                }
            }
        });
    }
    private MarcClient client;
    private String confirmToken = "";
    private String chatTarget = "auto";
    private boolean listening;
    private long listenStartedAt;
    private final Runnable listenWatch = this::expireListen;
    private int listenGen;
    private boolean watchingScreen;
    private boolean hydrationPending;
    private boolean hydrationArmed;
    private final Runnable hydrationTick = this::maybeHydration;
    private boolean pillLongFired;
    private final Runnable pillLongPress = this::onPillLongPress;
    /** True while cellular/VoIP call is ringing or active — pill stays visible, taps ignored. */
    private boolean onCall;
    private TelephonyManager telephony;
    private Object callCallback;
    @SuppressWarnings("deprecation")
    private PhoneStateListener callListener;
    private static WeakReference<AccessibilityService> hostRef;
    private static WeakReference<IslandService> running;

    static void bindHost(AccessibilityService host) {
        hostRef = host == null ? null : new WeakReference<>(host);
        IslandService service = running == null ? null : running.get();
        if (service == null) {
            return;
        }
        if (host == null) {
            service.mainHandler.post(service::dropPill);
            return;
        }
        service.mainHandler.post(() -> {
            if (MarcPresence.isAside(service)) {
                return;
            }
            // Recreate on this same main-thread turn so nested ensurePill posts cannot
            // race and fall back to APPLICATION_OVERLAY after a11y already won.
            service.dropPill();
            service.ensurePillNow();
        });
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        running = new WeakReference<>(this);
        try {
            ensureForeground();
        } catch (RuntimeException ignored) {
        }
        if (client == null) {
            client = new MarcClient(getString(R.string.pi_base_url), getString(R.string.marc_token));
        }
        watchInbox();
        if (tts == null) {
            tts = new TextToSpeech(this, status -> {
                ttsReady = status == TextToSpeech.SUCCESS;
                Log.i(TAG, "tts " + status);
                if (!ttsReady) {
                    return;
                }
                tts.setLanguage(Locale.US);
                tts.setAudioAttributes(new AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_MEDIA)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                        .build());
                tts.setOnUtteranceProgressListener(new UtteranceProgressListener() {
                    @Override
                    public void onStart(String utteranceId) {
                        setPhase("Speaking");
                    }

                    @Override
                    public void onDone(String utteranceId) {
                        mainHandler.post(() -> {
                            if ("Speaking".equals(phase)) {
                                setPhase("Idle");
                            }
                        });
                    }

                    @Override
                    public void onError(String utteranceId) {
                        mainHandler.post(() -> {
                            if ("Speaking".equals(phase)) {
                                setPhase("Idle");
                            }
                        });
                    }
                });
                String waiting = pendingSpeech;
                pendingSpeech = null;
                if (waiting != null) {
                    say(waiting);
                }
            });
        }
        if (intent != null && MarcPresence.ACTION_RESUME.equals(intent.getAction())) {
            MarcPresence.resume(this);
            try {
                ensureForeground();
            } catch (RuntimeException ignored) {
            }
        }
        if (MarcPresence.isAside(this) || (intent != null && MarcPresence.ACTION_ASIDE.equals(intent.getAction()))) {
            dropPill();
            MarcPresence.watch(this);
            if (intent != null && ACTION_LISTEN.equals(intent.getAction())) {
                startListening();
            } else if (intent != null && intent.hasExtra("text")) {
                if (intent.hasExtra("target")) {
                    String extra = intent.getStringExtra("target");
                    if (extra != null && !extra.isEmpty()) {
                        chatTarget = extra;
                    }
                }
                ask(intent.getStringExtra("text"), intent.getBooleanExtra("typed", false));
            }
            return START_STICKY;
        }
        ensurePill();
        mainHandler.postDelayed(() -> {
            if (!MarcPresence.isAside(this) && (pill == null || !pill.isAttachedToWindow())) {
                ensurePill();
            }
        }, 800);
        watchScreen();
        watchCalls();
        applyScreen();
        armHydration();
        if (intent != null && ACTION_PLAY_WATER.equals(intent.getAction())) {
            playWaterNow();
        } else if (intent != null && ACTION_LISTEN.equals(intent.getAction())) {
            startListening();
        } else if (intent != null && intent.hasExtra("text")) {
            if (intent.hasExtra("target")) {
                String extra = intent.getStringExtra("target");
                if (extra != null && !extra.isEmpty()) {
                    chatTarget = extra;
                }
            }
            ask(intent.getStringExtra("text"), intent.getBooleanExtra("typed", false));
        }
        return START_STICKY;
    }

    private void ensureForeground() {
        boolean aside = MarcPresence.isAside(this);
        String channelId = aside ? "marc-aside" : "marc";
        int importance = aside ? NotificationManager.IMPORTANCE_DEFAULT : NotificationManager.IMPORTANCE_LOW;
        NotificationChannel channel = new NotificationChannel(channelId, aside ? "Marc is aside" : "Marc", importance);
        NotificationManager manager = getSystemService(NotificationManager.class);
        manager.createNotificationChannel(channel);
        Notification.Builder builder = new Notification.Builder(this, channelId)
                .setContentTitle(aside ? "Marc is aside" : "Marc")
                .setContentText(aside ? "Tap to bring Marc back" : "Marc")
                .setSmallIcon(android.R.drawable.ic_btn_speak_now)
                .setOngoing(true);
        if (aside) {
            Intent resume = new Intent(this, IslandService.class);
            resume.setAction(MarcPresence.ACTION_RESUME);
            PendingIntent tap = PendingIntent.getService(
                    this, 1, resume, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
            builder.setContentIntent(tap);
        }
        Notification notification = builder.build();
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(7, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE);
        } else {
            startForeground(7, notification);
        }
    }

    private void dropPill() {
        mainHandler.removeCallbacks(pillLongPress);
        removeOverlayView(pill);
        dropHero();
        pill = null;
        backdropView = null;
        waveView = null;
        lineView = null;
        yesView = null;
        noView = null;
        iconRow = null;
        windowManager = null;
    }

    private void removeOverlayView(View view) {
        if (view == null) {
            return;
        }
        // Try every WindowManager that may own the pill so reconnects don't leave ghosts.
        WindowManager[] managers = new WindowManager[]{
                windowManager,
                (WindowManager) getSystemService(WINDOW_SERVICE),
                hostRef == null || hostRef.get() == null
                        ? null
                        : (WindowManager) hostRef.get().getSystemService(WINDOW_SERVICE),
        };
        for (WindowManager manager : managers) {
            if (manager == null) {
                continue;
            }
            try {
                manager.removeViewImmediate(view);
            } catch (RuntimeException ignored) {
            }
        }
    }

    private void dropHero() {
        try {
            if (windowManager != null && heroView != null && heroView.isAttachedToWindow()) {
                windowManager.removeView(heroView);
            }
        } catch (RuntimeException ignored) {
        }
        heroView = null;
        dropHeroHit();
    }

    private void ensurePill() {
        mainHandler.post(this::ensurePillNow);
    }

    /**
     * Prefer TYPE_ACCESSIBILITY_OVERLAY (shows above the lock-screen keyguard).
     * Must run on the main thread. Upgrades an existing app-overlay pill when a11y binds.
     */
    private void ensurePillNow() {
        if (MarcPresence.isAside(this)) {
            return;
        }
        boolean hostReady = hostRef != null && hostRef.get() != null;
        if (pill != null && pill.getParent() != null) {
            WindowManager.LayoutParams params =
                    (WindowManager.LayoutParams) pill.getLayoutParams();
            boolean appOverlay = params != null
                    && params.type == WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY;
            if (!(hostReady && appOverlay)) {
                return;
            }
            // Stuck under the keyguard as SYSTEM_ALERT_WINDOW — promote to a11y.
            dropPill();
        } else {
            dropPill();
        }
        // Trust addOverlay's result — isAttachedToWindow() can lag false on a11y overlays
        // and was causing an immediate fallback to APPLICATION_OVERLAY (hidden on lock).
        if (!showPill(true)) {
            showPill(false);
        }
    }

    /** Wake / lock-screen path: same as ensurePill, then re-apply visibility flags. */
    private void ensurePillForLockScreen() {
        mainHandler.post(() -> {
            ensurePillNow();
            if (pill != null && pill.getParent() != null) {
                applyScreen();
            }
        });
    }

    private boolean showPill() {
        return showPill(hostRef != null && hostRef.get() != null);
    }

    private boolean showPill(boolean preferA11y) {
        if (pill != null && pill.getParent() != null) {
            return true;
        }
        dropPill();
        AccessibilityService host = preferA11y && hostRef != null ? hostRef.get() : null;
        // View context MUST match the WindowManager owner or Android throws BadTokenException.
        Context overlayCtx = host != null ? host : this;
        windowManager = (WindowManager) overlayCtx.getSystemService(WINDOW_SERVICE);
        if (windowManager == null) {
            Log.e(TAG, "no window manager for pill");
            return false;
        }
        int height = dp(38);
        int slop = dp(IslandTouch.HIT_SLOP_DP);
        int extraBelow = dp(IslandTouch.HIT_BELOW_DP);
        pill = new FrameLayout(overlayCtx);
        pill.setClickable(true);
        pill.setFocusable(false);
        pill.setClipToPadding(false);
        pill.setClipChildren(false);
        pill.setPadding(slop, 0, slop, extraBelow);

        backdropView = new IslandBackdropView(overlayCtx);
        FrameLayout.LayoutParams backdropLp = new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, height, Gravity.TOP);
        pill.addView(backdropView, backdropLp);

        LinearLayout row = new LinearLayout(overlayCtx);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        FrameLayout.LayoutParams rowLp = new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, height, Gravity.TOP);
        pill.addView(row, rowLp);

        iconRow = new LinearLayout(overlayCtx);
        iconRow.setOrientation(LinearLayout.HORIZONTAL);
        iconRow.setGravity(Gravity.CENTER_VERTICAL);
        row.addView(iconRow, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.MATCH_PARENT));

        View hole = new View(overlayCtx);
        row.addView(hole, new LinearLayout.LayoutParams(dp(26), 1));

        waveView = new IslandWaveView(overlayCtx);
        waveView.setVisibility(View.GONE);
        LinearLayout.LayoutParams waveLp = new LinearLayout.LayoutParams(dp(24), dp(18));
        waveLp.leftMargin = dp(2);
        waveLp.rightMargin = dp(2);
        row.addView(waveView, waveLp);

        lineView = label(overlayCtx, "");
        lineView.setGravity(Gravity.CENTER_VERTICAL | Gravity.START);
        lineView.setMaxWidth(dp(92));
        lineView.setPadding(dp(2), 0, dp(8), 0);
        row.addView(lineView, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.MATCH_PARENT));

        yesView = chipLabel(overlayCtx, "Yes", 0x3330D158, 0xFF30D158);
        noView = chipLabel(overlayCtx, "No", 0x33FF453A, 0xFFFF453A);
        yesView.setVisibility(View.GONE);
        noView.setVisibility(View.GONE);
        LinearLayout.LayoutParams yesLp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, dp(24));
        yesLp.rightMargin = dp(4);
        LinearLayout.LayoutParams noLp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT, dp(24));
        noLp.rightMargin = dp(6);
        row.addView(yesView, yesLp);
        row.addView(noView, noLp);
        yesView.setOnClickListener(v -> sendConfirm(true));
        noView.setOnClickListener(v -> sendConfirm(false));

        // Touch only on the drawn capsule (backdrop + row), not empty padding under/beside it.
        View.OnTouchListener islandHit = this::onPillTouch;
        backdropView.setOnTouchListener(islandHit);
        row.setOnTouchListener(islandHit);
        pill.setOnTouchListener((v, event) -> {
            if (event.getY() > height) {
                return false;
            }
            return onPillTouch(v, event);
        });

        WindowManager.LayoutParams params = buildPillParams(
                host != null,
                dp(112) + slop * 2,
                height + extraBelow,
                Math.max(0, Math.round(CAMERA_X_PX - dp(112) / 2f - slop)),
                Math.max(0, Math.round(CAMERA_Y_PX - height / 2f)));
        if (!addOverlay(pill, params)) {
            removeOverlayView(pill);
            pill = null;
            backdropView = null;
            waveView = null;
            lineView = null;
            yesView = null;
            noView = null;
            iconRow = null;
            windowManager = null;
            return false;
        }
        pill.setPivotX(slop + dp(112) / 2f);
        pill.setPivotY(height / 2f);
        setLine("");
        Log.i(TAG, "pill live y=" + params.y + " h=" + params.height
                + " cameraY=" + CAMERA_Y_PX + " type=" + params.type
                + " a11y=" + (host != null));
        return true;
    }

    private WindowManager.LayoutParams buildPillParams(boolean a11y, int width, int height, int x, int y) {
        int type = a11y
                ? WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY
                : WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY;
        WindowManager.LayoutParams params = new WindowManager.LayoutParams(
                width,
                height,
                type,
                windowFlags(true),
                PixelFormat.TRANSLUCENT);
        params.gravity = Gravity.TOP | Gravity.START;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            params.layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS;
            params.setFitInsetsTypes(0);
            params.setFitInsetsIgnoringVisibility(true);
        }
        params.x = x;
        params.y = y;
        return params;
    }

    private void showHeroStage() {
        AccessibilityService host = hostRef == null ? null : hostRef.get();
        if (windowManager == null) {
            windowManager = (WindowManager) (host != null ? host : this).getSystemService(WINDOW_SERVICE);
        }
        if (windowManager == null) {
            return;
        }
        if (heroView != null && heroView.isAttachedToWindow()) {
            return;
        }
        heroView = new HydrationHeroView(this);
        heroView.setHost(new HydrationHeroView.Host() {
            @Override
            public void onOffer() {
                say("Hey. Drink some water.");
            }

            @Override
            public void onOffering(boolean offering) {
                if (offering) {
                    showHeroHit();
                } else {
                    dropHeroHit();
                }
            }

            @Override
            public void onFinished(boolean drank) {
                dropHeroHit();
                mainHandler.post(() -> dropHero());
                SharedPreferences prefs = hydrationPrefs();
                long now = System.currentTimeMillis();
                long wait = drank ? HYDRATION_HOUR_MS : HYDRATION_SNOOZE_MS;
                prefs.edit()
                        .putBoolean("seen", true)
                        .putLong("last", now)
                        .putLong("next", now + wait)
                        .apply();
                hydrationPending = false;
                armHydrationIn(wait);
                Log.i(TAG, "hydration done drank=" + drank);
            }
        });
        int type = host != null
                ? WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY
                : WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY;
        WindowManager.LayoutParams params = new WindowManager.LayoutParams(
                getResources().getDisplayMetrics().widthPixels,
                dp(380),
                type,
                windowFlags(screenLit()) | WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE,
                PixelFormat.TRANSLUCENT);
        params.gravity = Gravity.TOP | Gravity.START;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            params.layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS;
            params.setFitInsetsTypes(0);
            params.setFitInsetsIgnoringVisibility(true);
        }
        params.x = 0;
        params.y = 0;
        if (!addOverlay(heroView, params)) {
            heroView = null;
            return;
        }
        raisePill();
    }

    private void showHeroHit() {
        if (windowManager == null || heroHit != null) {
            return;
        }
        heroHit = new View(this);
        heroHit.setClickable(true);
        heroHit.setOnClickListener(v -> {
            if (heroView != null) {
                heroView.acceptDrink();
            }
        });
        AccessibilityService host = hostRef == null ? null : hostRef.get();
        int type = host != null
                ? WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY
                : WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY;
        // Sit clearly under the island so drink taps never steal the camera-hole hit box.
        int w = dp(160);
        int h = dp(200);
        int visualH = dp(38);
        int below = dp(IslandTouch.HIT_BELOW_DP);
        WindowManager.LayoutParams params = new WindowManager.LayoutParams(
                w,
                h,
                type,
                windowFlags(true),
                PixelFormat.TRANSLUCENT);
        params.gravity = Gravity.TOP | Gravity.START;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            params.layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS;
            params.setFitInsetsTypes(0);
            params.setFitInsetsIgnoringVisibility(true);
        }
        params.x = Math.max(0, Math.round(CAMERA_X_PX - w / 2f));
        params.y = Math.max(0, Math.round(CAMERA_Y_PX + visualH / 2f + below + dp(8)));
        if (!addOverlay(heroHit, params)) {
            heroHit = null;
        }
    }

    private void dropHeroHit() {
        try {
            if (windowManager != null && heroHit != null && heroHit.isAttachedToWindow()) {
                windowManager.removeView(heroHit);
            }
        } catch (RuntimeException ignored) {
        }
        heroHit = null;
    }

    private SharedPreferences hydrationPrefs() {
        return getSharedPreferences("marc_hydration", MODE_PRIVATE);
    }

    private void armHydration() {
        if (hydrationArmed) {
            return;
        }
        SharedPreferences prefs = hydrationPrefs();
        boolean seen = prefs.getBoolean("seen", false);
        long now = System.currentTimeMillis();
        long last = prefs.getLong("last", 0);
        long delay = BeeOverlay.nextDelayMs(seen, last, now);
        if (delay <= 0L) {
            delay = 1000L;
        }
        armHydrationIn(delay);
    }

    private void armHydrationIn(long delayMs) {
        hydrationArmed = true;
        mainHandler.removeCallbacks(hydrationTick);
        mainHandler.postDelayed(hydrationTick, Math.max(1000L, delayMs));
        Log.i(TAG, "hydration in " + delayMs + "ms");
    }

    private void maybeHydration() {
        if (MarcPresence.isAside(this)) {
            armHydrationIn(60_000L);
            return;
        }
        if (!screenLit()) {
            hydrationPending = true;
            return;
        }
        if (listening || !confirmToken.isEmpty()) {
            armHydrationIn(20_000L);
            return;
        }
        if (heroView != null && heroView.isPlaying()) {
            return;
        }
        SharedPreferences prefs = hydrationPrefs();
        boolean seen = prefs.getBoolean("seen", false);
        long last = prefs.getLong("last", 0);
        long now = System.currentTimeMillis();
        long delay = BeeOverlay.nextDelayMs(seen, last, now);
        if (!hydrationPending && delay > 0L) {
            armHydrationIn(delay);
            return;
        }
        playHydration();
    }

    private void playWaterNow() {
        ensurePill();
        playHydration();
    }

    private void playHydration() {
        ensurePill();
        showHeroStage();
        raisePill();
        if (heroView == null) {
            armHydrationIn(15_000L);
            return;
        }
        hydrationPending = false;
        if (pill != null) {
            pill.animate()
                    .scaleX(1.08f)
                    .scaleY(1.1f)
                    .setDuration(180)
                    .setInterpolator(new DecelerateInterpolator())
                    .withEndAction(() -> {
                        if (pill != null) {
                            pill.animate()
                                    .scaleX(1f)
                                    .scaleY(1f)
                                    .setDuration(240)
                                    .setInterpolator(new OvershootInterpolator(1.8f))
                                    .start();
                        }
                    })
                    .start();
        }
        heroView.play();
        Log.i(TAG, "hydration play");
    }

    private void openChat() {
        Intent intent = new Intent(this, IslandActivity.class);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        startActivity(intent);
    }

    private boolean onPillTouch(View view, MotionEvent event) {
        if (onCall) {
            // Stay visible during calls, but never steal taps from the dialer.
            return false;
        }
        // Map hits to the drawn island only (38dp capsule). Ignore invisible padding.
        int visualH = dp(38);
        float localY = event.getY();
        if (view != pill && pill != null) {
            // Child coordinates → pill-local for the visual-band check.
            localY = event.getY() + view.getTop();
        }
        if (localY < 0 || localY > visualH) {
            mainHandler.removeCallbacks(pillLongPress);
            return false;
        }
        if (touchOnChip(yesView, event) || touchOnChip(noView, event)) {
            mainHandler.removeCallbacks(pillLongPress);
            return false;
        }
        int action = event.getActionMasked();
        View animateTarget = pill != null ? pill : view;
        if (action == MotionEvent.ACTION_DOWN) {
            IslandTouch.onDown(listening, !confirmToken.isEmpty());
            pillLongFired = false;
            mainHandler.removeCallbacks(pillLongPress);
            mainHandler.postDelayed(pillLongPress, IslandTouch.LONG_PRESS_MS);
            animateTarget.animate().cancel();
            animateTarget.animate()
                    .scaleX(0.93f)
                    .scaleY(0.93f)
                    .setDuration(80)
                    .setInterpolator(new DecelerateInterpolator())
                    .start();
            return true;
        }
        if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL) {
            mainHandler.removeCallbacks(pillLongPress);
            animateTarget.animate().cancel();
            animateTarget.animate()
                    .scaleX(1f)
                    .scaleY(1f)
                    .setDuration(220)
                    .setInterpolator(new OvershootInterpolator(2.2f))
                    .start();
            if (action == MotionEvent.ACTION_UP && !pillLongFired) {
                onPillTap();
            }
            return true;
        }
        return true;
    }

    private void onPillTap() {
        long age = listening ? SystemClock.uptimeMillis() - listenStartedAt : 0L;
        String action = IslandTouch.onTap(listening, !confirmToken.isEmpty(), age);
        Log.i(TAG, "pill tap " + action);
        if ("cancel".equals(action)) {
            sendConfirm(false);
            return;
        }
        if ("ignore".equals(action)) {
            return;
        }
        if ("stop_listen".equals(action)) {
            listening = false;
            mainHandler.removeCallbacks(listenWatch);
            releaseRecognizer();
            if (waveView != null) {
                waveView.setMode(false, false);
            }
            if (backdropView != null) {
                backdropView.setState(IslandBackdropView.STATE_IDLE);
            }
            setLine("", false);
            setPhase("Idle");
            return;
        }
        if ("restart_listen".equals(action)) {
            releaseRecognizer();
            listening = false;
        }
        startListening();
    }

    private void onPillLongPress() {
        pillLongFired = true;
        if (pill != null) {
            pill.animate().cancel();
            pill.animate()
                    .scaleX(1f)
                    .scaleY(1f)
                    .setDuration(180)
                    .setInterpolator(new OvershootInterpolator(2.2f))
                    .start();
        }
        String action = IslandTouch.onLongPress(listening, !confirmToken.isEmpty());
        Log.i(TAG, "pill long-press " + action);
        if ("open_app".equals(action)) {
            openChat();
        }
    }

    private boolean touchOnChip(View chip, MotionEvent event) {
        if (chip == null || chip.getVisibility() != View.VISIBLE || pill == null) {
            return false;
        }
        int[] pillLoc = new int[2];
        int[] chipLoc = new int[2];
        pill.getLocationOnScreen(pillLoc);
        chip.getLocationOnScreen(chipLoc);
        float x = event.getRawX();
        float y = event.getRawY();
        return x >= chipLoc[0] && x < chipLoc[0] + chip.getWidth()
                && y >= chipLoc[1] && y < chipLoc[1] + chip.getHeight();
    }

    private void raisePill() {
        if (windowManager == null || pill == null || !pill.isAttachedToWindow()) {
            return;
        }
        WindowManager.LayoutParams params = (WindowManager.LayoutParams) pill.getLayoutParams();
        params.flags = windowFlags(screenLit());
        try {
            windowManager.removeView(pill);
            windowManager.addView(pill, params);
        } catch (RuntimeException exc) {
            Log.w(TAG, "raise pill", exc);
            try {
                windowManager.updateViewLayout(pill, params);
            } catch (RuntimeException ignored) {
            }
        }
    }

    private void startListening() {
        startListening(false);
    }

    private void expireListen() {
        if (!listening) {
            return;
        }
        if (SystemClock.uptimeMillis() - listenStartedAt < IslandTouch.LISTEN_TIMEOUT_MS) {
            return;
        }
        listening = false;
        releaseRecognizer();
        if (waveView != null) {
            waveView.setMode(false, false);
        }
        if (backdropView != null) {
            backdropView.setState(IslandBackdropView.STATE_IDLE);
        }
        setLine(BeeAsk.lineFor("fail"));
        setPhase("Idle");
    }

    private void startListening(boolean retried) {
        final int gen = ++listenGen;
        listening = true;
        listenStartedAt = SystemClock.uptimeMillis();
        mainHandler.removeCallbacks(listenWatch);
        mainHandler.postDelayed(listenWatch, IslandTouch.LISTEN_TIMEOUT_MS);
        setPhase("Listening");
        if (!retried && tts != null) {
            tts.stop();
        }
        if (backdropView != null) {
            backdropView.setState(IslandBackdropView.STATE_LISTENING);
        }
        if (waveView != null) {
            waveView.setMode(true, false);
        }
        setLine(BeeAsk.lineFor("listen"), false);
        Log.i(TAG, "listen-start gen=" + gen + " retry=" + retried);
        if (recognizer == null) {
            recognizer = SpeechRecognizer.createSpeechRecognizer(this);
        } else {
            try {
                recognizer.cancel();
            } catch (Exception ignored) {
            }
        }
        recognizer.setRecognitionListener(new Listener(gen, retried));
        Intent intent = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
        intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
        intent.putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true);
        if (Build.VERSION.SDK_INT >= 33) {
            intent.putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true);
        }
        intent.putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_MINIMUM_LENGTH_MILLIS, 1500);
        intent.putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 2200);
        intent.putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_POSSIBLY_COMPLETE_SILENCE_LENGTH_MILLIS, 1800);
        recognizer.startListening(intent);
    }

    private void ask(String text) {
        ask(text, false);
    }

    private void ask(String text, boolean typed) {
        if (text == null || text.trim().isEmpty()) {
            if (waveView != null) {
                waveView.setMode(false, false);
            }
            if (backdropView != null) {
                backdropView.setState(IslandBackdropView.STATE_IDLE);
            }
            setLine("");
            setPhase("Idle");
            return;
        }
        String said = typed ? text.trim() : HearFix.correct(this, text.trim());
        String voice = BeeAsk.classifyVoice(said);
        if ("refuse".equals(voice)) {
            ChatStore.add(this, false, "No.");
            setLine(BeeAsk.lineFor("fail"));
            setPhase("Idle");
            return;
        }
        if (!confirmToken.isEmpty()) {
            if ("confirm".equals(voice)) {
                sendConfirm(true);
                return;
            }
            if ("cancel".equals(voice)) {
                sendConfirm(false);
                return;
            }
        }
        setPhase("Thinking");
        setLine(BeeAsk.lineFor("plan"), false);
        ChatStore.add(this, true, said);
        ActivityStore.heard(this, said);
        Log.i(TAG, "utterance " + text.trim() + " -> " + said);

        // Named device or Chat target always goes to Marc API.
        String target = resolveTarget(said);
        if (!"auto".equals(target) && !"phone".equals(target)) {
            askMarc(said, target);
            return;
        }

        Map<String, Object> planned = BeeAsk.planAsk(said);
        String kind = String.valueOf(planned.get("kind"));
        if ("local_fast".equals(kind) || BeeAsk.skipMuse(said)) {
            LocalMarc.Plan localPlan = LocalMarc.plan(said);
            if (localPlan != null) {
                ActivityStore.localPlan(this, "LocalMarc", localPlan.spoken, localPlan.steps);
                actLocal(localPlan);
                return;
            }
        }
        if ("dag".equals(kind) && !dagNeedsRemote(planned)) {
            runBeeDag(planned);
            return;
        }
        askMarc(said, target);
    }

    private String resolveTarget(String said) {
        if (namedLaptop(said)) {
            return "laptop";
        }
        if (namedServer(said)) {
            return "server";
        }
        if (chatTarget != null && !chatTarget.isEmpty() && !"auto".equals(chatTarget)) {
            return chatTarget;
        }
        return "auto";
    }

    @SuppressWarnings("unchecked")
    private static boolean dagNeedsRemote(Map<String, Object> planned) {
        List<Map<String, Object>> steps = (List<Map<String, Object>>) planned.get("steps");
        if (steps == null) {
            return false;
        }
        for (Map<String, Object> step : steps) {
            String device = String.valueOf(step.get("device"));
            if ("laptop".equals(device) || "server".equals(device)) {
                return true;
            }
        }
        return false;
    }

    @SuppressWarnings("unchecked")
    private void runBeeDag(Map<String, Object> planned) {
        List<Map<String, Object>> steps = (List<Map<String, Object>>) planned.get("steps");
        JSONArray phone = new JSONArray();
        if (steps != null) {
            for (Map<String, Object> step : steps) {
                String device = String.valueOf(step.get("device"));
                if ("laptop".equals(device) || "server".equals(device)) {
                    continue;
                }
                phone.put(toPhoneStep(step));
            }
        }
        String spoken = phone.length() <= 1
                ? "On it."
                : "On it — " + phone.length() + " steps queued.";
        ActivityStore.localPlan(this, "BeeAsk", spoken, phone);
        setLine(BeeAsk.clampLine(spoken));
        actLocal(new LocalMarc.Plan(spoken, phone, false, false));
    }

    private void askMarc(String said, String target) {
        if (backdropView != null) {
            backdropView.setState(IslandBackdropView.STATE_THINKING);
        }
        if (waveView != null) {
            waveView.setMode(true, true);
        }
        fitPill(said);
        ActivityStore.planning(this, "hermes", target);
        final String dest = target == null || target.isEmpty() ? "auto" : target;
        io.execute(() -> {
            try {
                JSONObject response = client.utterance(said, dest);
                ActivityStore.fromResponse(this, response);
                runMain(() -> show(response));
            } catch (Exception exc) {
                Log.e(TAG, "marc utterance failed", exc);
                String message = connectionLine(exc.getMessage());
                ActivityStore.fail(this, message);
                runMain(() -> {
                    if (waveView != null) {
                        waveView.setMode(false, false);
                    }
                    if (backdropView != null) {
                        backdropView.setState(IslandBackdropView.STATE_ERROR);
                    }
                    ChatStore.add(this, false, message);
                    setLine(BeeAsk.clampLine(message));
                    say(message);
                    setPhase("Idle");
                });
            }
        });
    }

    private JSONObject toPhoneStep(Map<String, Object> step) {
        JSONObject out = new JSONObject();
        try {
            String tool = String.valueOf(step.get("tool"));
            if ("music_play".equals(tool)) {
                tool = "play_music";
            } else if ("phone_dial".equals(tool)) {
                tool = "dial";
            } else if ("app_open".equals(tool)) {
                tool = "open_app";
            }
            out.put("tool", tool);
            JSONObject args = new JSONObject();
            Object raw = step.get("args");
            if (raw instanceof Map) {
                Map<?, ?> map = (Map<?, ?>) raw;
                for (Map.Entry<?, ?> e : map.entrySet()) {
                    args.put(String.valueOf(e.getKey()), e.getValue() == null ? "" : String.valueOf(e.getValue()));
                }
            }
            if (args.has("to") && !args.has("contact")) {
                args.put("contact", args.optString("to"));
            }
            if (args.has("app") && !args.has("name")) {
                args.put("name", args.optString("app"));
            }
            out.put("args", args);
        } catch (Exception ignored) {
        }
        return out;
    }

    private void show(JSONObject response) {
        if (heroView != null && heroView.isPlaying()) {
            dropHeroHit();
            mainHandler.post(this::dropHero);
            hydrationPending = true;
            armHydrationIn(30_000L);
        }
        if (waveView != null) {
            waveView.setMode(false, false);
        }
        String line = response.optString("spoken", "");
        Log.i(TAG, "reply " + line);
        say(line);
        JSONArray steps = MarcClient.phoneSteps(response);
        if (PaymentApps.opens(steps)) {
            MarcPresence.stepAside(this);
        }
        PhoneActions.setFail(message -> runMain(() -> {
            if (backdropView != null) {
                backdropView.setState(IslandBackdropView.STATE_ERROR);
            }
            ChatStore.add(this, false, message);
                say(message);
            setLine(message);
        }));
        PhoneActions.run(this, steps);
        if (response.has("apps")) {
            showApps(response.optJSONArray("apps"));
        }
        JSONObject confirm = response.optJSONObject("confirm");
        if (confirm == null) {
            confirmToken = "";
            if (yesView != null) {
                yesView.setVisibility(View.GONE);
            }
            if (noView != null) {
                noView.setVisibility(View.GONE);
            }
            if (backdropView != null) {
                backdropView.setState(IslandBackdropView.STATE_ACTING);
            }
            String spoken = line.isEmpty() ? "Done" : line;
            ChatStore.add(this, false, withSteps(spoken, response));
            setLine(line.isEmpty() ? "" : line);
            return;
        }
        confirmToken = confirm.optString("token");
        if (backdropView != null) {
            backdropView.setState(IslandBackdropView.STATE_CONFIRM);
        }
        if (yesView != null) {
            yesView.setVisibility(View.VISIBLE);
        }
        if (noView != null) {
            noView.setVisibility(View.VISIBLE);
        }
        String summary = confirm.optString("summary");
        ChatStore.add(this, false, summary);
        setLine(summary);
    }

    private void sendConfirm(boolean yes) {
        String token = confirmToken;
        confirmToken = "";
        yesView.setVisibility(View.GONE);
        noView.setVisibility(View.GONE);
        if (backdropView != null) {
            backdropView.setState(yes ? IslandBackdropView.STATE_THINKING : IslandBackdropView.STATE_IDLE);
        }
        setLine(yes ? "Sending" : "Cancelled");
        io.execute(() -> {
            try {
                JSONObject response = client.confirm(token, yes);
                runMain(() -> show(response));
            } catch (Exception exc) {
                String message = exc.getMessage() == null ? "Can't reach Marc" : exc.getMessage();
                runMain(() -> {
                    if (backdropView != null) {
                        backdropView.setState(IslandBackdropView.STATE_ERROR);
                    }
                    ChatStore.add(this, false, message);
                    setLine("Can't reach Marc");
                });
            }
        });
    }

    private void actLocal(LocalMarc.Plan plan) {
        if (plan.resume) {
            MarcPresence.resume(this);
            try {
                ensureForeground();
            } catch (RuntimeException ignored) {
            }
            speakLocal(plan.spoken);
            ensurePill();
            return;
        }
        speakLocal(plan.spoken);
        if (plan.aside || PaymentApps.opens(plan.steps)) {
            MarcPresence.stepAside(this);
        }
        if (plan.steps.length() > 0) {
            PhoneActions.setFail(message -> runMain(() -> {
                ChatStore.add(this, false, message);
                say(message);
                setLine(message);
            }));
            PhoneActions.run(this, plan.steps);
        }
    }

    private void speakLocal(String spoken) {
        if (waveView != null) {
            waveView.setMode(false, false);
        }
        if (backdropView != null) {
            backdropView.setState(IslandBackdropView.STATE_ACTING);
        }
        ChatStore.add(this, false, spoken == null ? "" : spoken);
        if ("Hi Ranjit.".equals(spoken) && backdropView != null) {
            backdropView.showFace();
        }
        say(spoken);
        setLine(spoken);
    }

    private static boolean namedLaptop(String text) {
        return text != null && text.toLowerCase(java.util.Locale.US)
                .matches(".*\\bon\\s+(?:my\\s+|the\\s+)?(?:laptop|computer|pc)\\b.*");
    }

    private static boolean namedServer(String text) {
        if (text == null) {
            return false;
        }
        String low = text.toLowerCase(java.util.Locale.US);
        return low.matches(".*\\bon\\s+(?:my\\s+|the\\s+)?(?:server|linux|home\\s+server)\\b.*")
                || low.matches(".*\\brestart\\s+(?:the\\s+)?(?:ollama|n8n|model|desk|api)\\b.*");
    }

    private static String withSteps(String spoken, JSONObject response) {
        JSONArray run = response == null ? null : response.optJSONArray("steps_run");
        if (run == null || run.length() == 0) {
            JSONArray machines = response == null ? null : response.optJSONArray("machines");
            if (machines == null || machines.length() == 0) {
                return spoken;
            }
            StringBuilder labels = new StringBuilder();
            for (int i = 0; i < machines.length(); i++) {
                if (labels.length() > 0) {
                    labels.append(" · ");
                }
                labels.append(machines.optString(i));
            }
            return spoken + "\n" + labels;
        }
        StringBuilder extra = new StringBuilder(spoken == null ? "" : spoken);
        for (int i = 0; i < run.length(); i++) {
            JSONObject step = run.optJSONObject(i);
            if (step == null) {
                continue;
            }
            extra.append('\n');
            if (step.optInt("hop") > 0) {
                extra.append("hop ").append(step.optInt("hop")).append(" ");
            }
            extra.append(step.optString("device"));
            extra.append(' ');
            extra.append(step.optString("tool"));
            extra.append(step.optBoolean("ok", true) ? " · ok" : " · failed");
            String message = step.optString("message");
            if (!message.isEmpty()) {
                extra.append(" — ");
                extra.append(message);
            }
        }
        return extra.toString();
    }

    private void say(String line) {
        if (line == null || line.isEmpty()) {
            return;
        }
        if (tts == null || !ttsReady) {
            pendingSpeech = line;
            return;
        }
        int code = tts.speak(line, TextToSpeech.QUEUE_FLUSH, null, "marc");
        Log.i(TAG, "speak " + code + " " + line);
        setPhase(code == TextToSpeech.SUCCESS ? "Speaking" : "Idle");
    }

    private void setPhase(String next) {
        phase = next;
        VoiceListener listener = voiceListener;
        if (listener != null) {
            mainHandler.post(() -> listener.onPhase(next));
        }
        if ("Listening".equals(next) && lineView != null) {
            setLine(BeeAsk.lineFor("listen"), false);
        } else if ("Thinking".equals(next) && lineView != null) {
            setLine(BeeAsk.lineFor("plan"), false);
        }
    }

    private static String connectionLine(String message) {
        if (message == null || message.isEmpty()) {
            return "I need a connection for that.";
        }
        String low = message.toLowerCase();
        if (low.contains("can't reach") || low.contains("failed to connect") || low.contains("timeout")
                || low.contains("unable to resolve") || low.contains("network") || low.contains("host")) {
            return "I need a connection for that.";
        }
        return message;
    }

    private void setLine(String text) {
        setLine(text, true);
    }

    private void setLine(String text, boolean clearLater) {
        final int token = ++lineToken;
        if (clearLine != null) {
            mainHandler.removeCallbacks(clearLine);
            clearLine = null;
        }
        String safe = text == null ? "" : text;
        if (lineView != null) {
            String prev = String.valueOf(lineView.getText());
            lineView.setText(safe);
            if (!safe.isEmpty() && !safe.equals(prev) && !listening) {
                lineView.setAlpha(0f);
                lineView.setTranslationY(dp(4));
                lineView.animate()
                        .alpha(1f)
                        .translationY(0f)
                        .setDuration(150)
                        .setInterpolator(new DecelerateInterpolator())
                        .start();
            }
        }
        fitPill(safe);
        boolean resting = safe.isEmpty() || "Listening".equals(safe);
        if (!clearLater || resting || listening || !confirmToken.isEmpty()) {
            return;
        }
        clearLine = () -> {
            if (token != lineToken || listening || !confirmToken.isEmpty()) {
                return;
            }
            if (waveView != null) {
                waveView.setMode(false, false);
            }
            if (backdropView != null && backdropView.getState() != IslandBackdropView.STATE_ACTING) {
                backdropView.setState(IslandBackdropView.STATE_IDLE);
            }
            setLine("", false);
        };
        mainHandler.postDelayed(clearLine, 2200);
    }

    /**
     * Updates WindowManager layout ONCE per state/width change and uses GPU RenderThread scale
     * animation for springy expansion—avoiding 60fps WindowManager surface reallocations during speech.
     */
    private void fitPill(String text) {
        if (pill == null || lineView == null || windowManager == null) {
            return;
        }
        String shown = text == null ? "" : text;
        int textW = shown.isEmpty() ? 0 : Math.min((int) lineView.getPaint().measureText(shown) + dp(10), dp(92));
        if (listening && textW > 0) {
            textW = dp(80);
        }
        int icons = iconRow == null ? 0 : iconRow.getChildCount();
        int iconW = icons == 0 ? 0 : icons * dp(22) + dp(6);
        int waveW = (waveView != null && waveView.getVisibility() == View.VISIBLE) ? dp(28) : 0;
        int extra = confirmToken.isEmpty() ? 0 : dp(72);
        boolean idle = icons == 0 && textW == 0 && waveW == 0 && extra == 0;

        int width = iconW + dp(26) + waveW + textW + extra + dp(14);
        int holeCenter = iconW + dp(13);
        if (idle) {
            width = dp(112);
            holeCenter = width / 2;
        } else if (iconW == 0 && (waveW + textW + extra) > 0) {
            int leftPad = dp(20);
            width = leftPad + dp(26) + waveW + textW + extra + dp(12);
            holeCenter = leftPad + dp(13);
        }
        width = Math.max(width, dp(112));
        width = Math.min(dp(256), width);

        WindowManager.LayoutParams params = (WindowManager.LayoutParams) pill.getLayoutParams();
        int slop = dp(IslandTouch.HIT_SLOP_DP);
        int extraBelow = dp(IslandTouch.HIT_BELOW_DP);
        int visualH = dp(38);
        int winW = width + slop * 2;
        int winH = visualH + extraBelow;
        int x = Math.max(0, Math.round(CAMERA_X_PX - holeCenter - slop));
        int y = Math.max(0, Math.round(CAMERA_Y_PX - visualH / 2f));
        int prevW = params.width;
        boolean changed = params.width != winW || params.x != x || params.height != winH || params.y != y;
        params.width = winW;
        params.height = winH;
        params.x = x;
        params.y = y;
        params.gravity = Gravity.TOP | Gravity.START;
        applyScreen(params);
        if (changed) {
            pill.setPivotX(slop + holeCenter);
            pill.setPivotY(visualH / 2f);
            float startScale = prevW > 0 ? Math.max(0.84f, Math.min(1.12f, (float) prevW / winW)) : 0.9f;
            pill.setScaleX(startScale);
            pill.animate()
                    .scaleX(1f)
                    .scaleY(1f)
                    .setDuration(240)
                    .setInterpolator(new OvershootInterpolator(1.6f))
                    .start();
            Log.i(TAG, "pill w=" + width + " x=" + x);
        }
    }

    private void showApps(JSONArray apps) {
        if (iconRow == null) {
            return;
        }
        iconRow.removeAllViews();
        if (apps != null) {
            int count = Math.min(apps.length(), 4);
            for (int i = 0; i < count; i++) {
                JSONObject app = apps.optJSONObject(i);
                if (app == null) {
                    continue;
                }
                Drawable icon = PhoneActions.iconForPackage(this, app.optString("package"));
                if (icon == null) {
                    icon = PhoneActions.iconForName(this, app.optString("name"));
                }
                if (icon == null) {
                    continue;
                }
                ImageView view = new ImageView(this);
                view.setImageDrawable(icon);
                view.setScaleType(ImageView.ScaleType.FIT_CENTER);
                LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(dp(18), dp(18));
                lp.leftMargin = i == 0 ? dp(6) : dp(4);
                view.setScaleX(0f);
                view.setScaleY(0f);
                view.setAlpha(0f);
                iconRow.addView(view, lp);
                view.animate()
                        .scaleX(1f)
                        .scaleY(1f)
                        .alpha(1f)
                        .setStartDelay(i * 55L)
                        .setDuration(240)
                        .setInterpolator(new OvershootInterpolator(2.0f))
                        .start();
            }
        }
        fitPill(lineView == null ? "" : String.valueOf(lineView.getText()));
    }

    private void watchScreen() {
        if (watchingScreen) {
            return;
        }
        watchingScreen = true;
        IntentFilter filter = new IntentFilter();
        filter.addAction(Intent.ACTION_SCREEN_OFF);
        filter.addAction(Intent.ACTION_SCREEN_ON);
        filter.addAction(Intent.ACTION_USER_PRESENT);
        if (Build.VERSION.SDK_INT >= 33) {
            registerReceiver(screenReceiver, filter, Context.RECEIVER_NOT_EXPORTED);
        } else {
            registerReceiver(screenReceiver, filter);
        }
    }

    private void applyScreen() {
        if (pill == null) {
            return;
        }
        applyScreen((WindowManager.LayoutParams) pill.getLayoutParams());
    }

    private void applyScreen(WindowManager.LayoutParams params) {
        boolean lit = screenLit();
        // Keep the pill on the lock screen (and while interactive). Hide only when the
        // display is fully off so it does not wake or block the keyguard.
        pill.setVisibility(lit ? View.VISIBLE : View.INVISIBLE);
        params.alpha = lit ? 1f : 0f;
        params.flags = windowFlags(lit);
        if (!lit && listening) {
            listening = false;
            if (waveView != null) {
                waveView.setMode(false, false);
            }
            if (backdropView != null) {
                backdropView.setState(IslandBackdropView.STATE_IDLE);
            }
            releaseRecognizer();
        }
        if (windowManager != null && pill != null && pill.isAttachedToWindow()) {
            try {
                windowManager.updateViewLayout(pill, params);
            } catch (RuntimeException exc) {
                Log.w(TAG, "applyScreen update failed; recreating pill", exc);
                ensurePillForLockScreen();
            }
        }
    }

    private boolean screenLit() {
        PowerManager power = getSystemService(PowerManager.class);
        return power != null && power.isInteractive();
    }

    private boolean keyguardLocked() {
        KeyguardManager keyguard = getSystemService(KeyguardManager.class);
        return keyguard != null && keyguard.isKeyguardLocked();
    }

    private int windowFlags(boolean lit) {
        int flags = WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
                | WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL
                | WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN
                | WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS
                // Show over the keyguard / lock screen when the display is on.
                | WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED
                | WindowManager.LayoutParams.FLAG_DRAWS_SYSTEM_BAR_BACKGROUNDS
                | WindowManager.LayoutParams.FLAG_HARDWARE_ACCELERATED;
        // Stay touchable on the lock screen whenever the display is interactive.
        if (!lit || onCall) {
            flags |= WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE;
        }
        return flags;
    }

    private void watchCalls() {
        if (telephony != null) {
            return;
        }
        telephony = getSystemService(TelephonyManager.class);
        if (telephony == null) {
            return;
        }
        if (Build.VERSION.SDK_INT >= 31) {
            TelephonyCallback callback = new CallStateCallback();
            callCallback = callback;
            try {
                telephony.registerTelephonyCallback(getMainExecutor(), callback);
            } catch (SecurityException exc) {
                Log.w(TAG, "call watch denied", exc);
                callCallback = null;
            }
            return;
        }
        callListener = new PhoneStateListener() {
            @Override
            @SuppressWarnings("deprecation")
            public void onCallStateChanged(int state, String phoneNumber) {
                mainHandler.post(() -> setOnCall(state));
            }
        };
        try {
            telephony.listen(callListener, PhoneStateListener.LISTEN_CALL_STATE);
        } catch (SecurityException exc) {
            Log.w(TAG, "call watch denied", exc);
            callListener = null;
        }
    }

    @SuppressLint("NewApi")
    private final class CallStateCallback extends TelephonyCallback implements TelephonyCallback.CallStateListener {
        @Override
        public void onCallStateChanged(int state) {
            mainHandler.post(() -> setOnCall(state));
        }
    }

    private void setOnCall(int state) {
        boolean next = state == TelephonyManager.CALL_STATE_OFFHOOK
                || state == TelephonyManager.CALL_STATE_RINGING;
        if (next == onCall) {
            return;
        }
        onCall = next;
        Log.i(TAG, "call " + (onCall ? "active" : "idle"));
        if (onCall && listening) {
            listening = false;
            mainHandler.removeCallbacks(listenWatch);
            releaseRecognizer();
            if (waveView != null) {
                waveView.setMode(false, false);
            }
            if (backdropView != null) {
                backdropView.setState(IslandBackdropView.STATE_IDLE);
            }
            setPhase("Idle");
        }
        applyScreen();
    }

    private void stopWatchCalls() {
        if (telephony == null) {
            return;
        }
        if (Build.VERSION.SDK_INT >= 31 && callCallback instanceof TelephonyCallback) {
            try {
                telephony.unregisterTelephonyCallback((TelephonyCallback) callCallback);
            } catch (RuntimeException ignored) {
            }
            callCallback = null;
        } else if (callListener != null) {
            try {
                telephony.listen(callListener, PhoneStateListener.LISTEN_NONE);
            } catch (RuntimeException ignored) {
            }
            callListener = null;
        }
        telephony = null;
    }

    private boolean addOverlay(View view, WindowManager.LayoutParams params) {
        if (windowManager == null || view == null || params == null) {
            return false;
        }
        if (view.getParent() != null) {
            return true;
        }
        try {
            windowManager.addView(view, params);
            return true;
        } catch (RuntimeException exc) {
            Log.e(TAG, "add overlay type=" + params.type, exc);
            return false;
        }
    }

    private void runMain(Runnable job) {
        if (pill != null && pill.isAttachedToWindow()) {
            pill.post(job);
            return;
        }
        mainHandler.post(job);
    }

    private TextView label(String text) {
        return label(this, text);
    }

    private TextView label(Context context, String text) {
        TextView view = new TextView(context);
        view.setText(text);
        view.setTextColor(0xFFF5F5F7);
        view.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12.5f);
        view.setGravity(Gravity.CENTER_VERTICAL | Gravity.END);
        view.setMaxLines(1);
        view.setEllipsize(android.text.TextUtils.TruncateAt.END);
        view.setIncludeFontPadding(false);
        return view;
    }

    private TextView chipLabel(String text, int bgColor, int textColor) {
        return chipLabel(this, text, bgColor, textColor);
    }

    private TextView chipLabel(Context context, String text, int bgColor, int textColor) {
        TextView view = label(context, text);
        view.setTextColor(textColor);
        view.setGravity(Gravity.CENTER);
        view.setPadding(dp(8), 0, dp(8), 0);
        GradientDrawable chip = new GradientDrawable();
        chip.setColor(bgColor);
        chip.setCornerRadius(dp(12));
        view.setBackground(chip);
        return view;
    }

    private void releaseRecognizer() {
        SpeechRecognizer previous = recognizer;
        recognizer = null;
        if (previous != null) {
            try {
                previous.destroy();
            } catch (Exception ignored) {
            }
        }
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    @Override
    public void onDestroy() {
        inboxWatch.shutdownNow();
        mainHandler.removeCallbacks(listenWatch);
        try {
            unregisterReceiver(screenReceiver);
        } catch (IllegalArgumentException ignored) {
        }
        stopWatchCalls();
        releaseRecognizer();
        if (tts != null) {
            tts.shutdown();
        }
        mainHandler.removeCallbacks(hydrationTick);
        mainHandler.removeCallbacks(pillLongPress);
        if (pill != null && windowManager != null) {
            try {
                windowManager.removeView(pill);
            } catch (RuntimeException ignored) {
            }
            pill = null;
        }
        dropHero();
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private final class Listener implements RecognitionListener {
        private final int gen;
        private final boolean retried;
        private String lastPartial = "";

        Listener(int gen, boolean retried) {
            this.gen = gen;
            this.retried = retried;
        }

        private boolean current() {
            return gen == listenGen;
        }

        @Override
        public void onReadyForSpeech(Bundle params) {
            if (!current()) {
                return;
            }
            Log.i(TAG, "onReadyForSpeech");
            setLine("Listening");
        }

        @Override
        public void onBeginningOfSpeech() {
            if (!current()) {
                return;
            }
            Log.i(TAG, "onBeginningOfSpeech");
        }

        @Override
        public void onRmsChanged(float rmsdB) {
            if (!current()) {
                return;
            }
            float norm = Math.max(0f, Math.min(1f, (rmsdB + 2f) / 10f));
            if (backdropView != null) {
                backdropView.setVoiceLevel(norm);
            }
            if (waveView != null) {
                waveView.setLevel(norm);
            }
        }

        @Override
        public void onBufferReceived(byte[] buffer) { }

        @Override
        public void onEndOfSpeech() {
            if (!current()) {
                return;
            }
            listening = false;
            Log.i(TAG, "onEndOfSpeech partial=" + lastPartial);
        }

        @Override
        public void onError(int error) {
            if (!current()) {
                return;
            }
            listening = false;
            Log.e(TAG, "listen-error " + error + " partial=" + lastPartial);
            if (!lastPartial.isEmpty()) {
                String heard = lastPartial;
                lastPartial = "";
                ask(heard);
                return;
            }
            if (!retried && (error == 11 || error == SpeechRecognizer.ERROR_RECOGNIZER_BUSY
                    || error == SpeechRecognizer.ERROR_CLIENT)) {
                releaseRecognizer();
                mainHandler.postDelayed(() -> startListening(true), 220);
                return;
            }
            if (waveView != null) {
                waveView.setMode(false, false);
            }
            if (backdropView != null) {
                backdropView.setState(IslandBackdropView.STATE_ERROR);
            }
            setLine(error == SpeechRecognizer.ERROR_NO_MATCH || error == SpeechRecognizer.ERROR_SPEECH_TIMEOUT
                    ? "Didn't catch that"
                    : "Tap again");
            setPhase("Idle");
        }

        @Override
        public void onResults(Bundle results) {
            if (!current()) {
                return;
            }
            listening = false;
            ArrayList<String> matches = results == null
                    ? null
                    : results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
            Log.i(TAG, "onResults " + matches + " partial=" + lastPartial);
            String best = "";
            if (matches != null && !matches.isEmpty() && matches.get(0) != null) {
                best = matches.get(0).trim();
            }
            if (best.isEmpty() && !lastPartial.isEmpty()) {
                best = lastPartial;
            }
            lastPartial = "";
            if (best.isEmpty()) {
                if (waveView != null) {
                    waveView.setMode(false, false);
                }
                if (backdropView != null) {
                    backdropView.setState(IslandBackdropView.STATE_ERROR);
                }
                setLine("Didn't catch that");
                return;
            }
            ask(best);
        }

        @Override
        public void onPartialResults(Bundle partial) {
            if (!current() || partial == null) {
                return;
            }
            ArrayList<String> matches = partial.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
            if (matches != null && !matches.isEmpty() && matches.get(0) != null) {
                String p = matches.get(0).trim();
                if (!p.isEmpty()) {
                    lastPartial = p;
                    if (lineView != null) {
                        lineView.setText(p);
                    }
                }
            }
        }

        @Override
        public void onEvent(int eventType, Bundle params) { }
    }
}
