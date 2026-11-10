package com.marc.island;

import java.util.Collections;
import java.util.LinkedHashSet;
import java.util.Set;

/**
 * IslandTouch pure touch contract (no Android imports; java.lang/java.util only).
 *
 * <p>Visual pill origin is fixed at CAMERA_X/CAMERA_Y (device px from the
 * display-cutout path on a 1080-wide Nothing panel). Hit expands by HIT_SLOP_DP
 * left/right and HIT_BELOW_DP below without moving the visual origin.
 */
public final class IslandTouch {

    /** Cutout center X in device px (path M540,…). Never change. */
    public static final float CAMERA_X = 540f;

    /** Cutout center Y in device px (path M540,68.6). Never change. */
    public static final float CAMERA_Y = 68.6f;

    /** Touch slop expansion applied on left/right (dp). Keep tiny — hit must match the drawn pill. */
    public static final int HIT_SLOP_DP = 8;

    /**
     * Extra tappable strip below the visual pill (dp).
     * Must stay 0: a non-zero strip made taps land under the island, not on it.
     */
    public static final int HIT_BELOW_DP = 0;

    /** Long-press duration before the app opens (ms). */
    public static final int LONG_PRESS_MS = 450;

    /** Listening tap debounce window (ms). */
    public static final int LISTEN_TIMEOUT_MS = 8000;

    private IslandTouch() {
    }

    /**
     * Overlay type for the pill.
     *
     * @param a11yBound true when bound via accessibility, false for application overlay
     * @return "accessibility" if bound, else "application"
     */
    public static String overlayType(boolean a11yBound) {
        return a11yBound ? "accessibility" : "application";
    }

    /** Null-safe overload: null is treated as not bound. */
    public static String overlayType(Boolean a11yBound) {
        return (a11yBound != null && a11yBound.booleanValue()) ? "accessibility" : "application";
    }

    /**
     * Window flags for the pill. The pill always receives taps, so the result
     * never includes "not_touchable" (any casing).
     *
     * @param screenOn true to keep screen on, false otherwise
     * @return unmodifiable set of flag tokens; always contains "touchable"
     */
    public static Set<String> windowFlags(boolean screenOn) {
        Set<String> flags = new LinkedHashSet<String>();
        flags.add("touchable");
        flags.add("not_focusable");
        flags.add("layout_in_screen");
        flags.add("watch_outside_touch");
        if (screenOn) {
            flags.add("keep_screen_on");
        }
        return Collections.unmodifiableSet(flags);
    }

    /** No-arg overload defaults to screenOn=false. */
    public static Set<String> windowFlags() {
        return windowFlags(false);
    }

    /**
     * Convenience mirror of the Python {@code window_flags_touchable} contract:
     * the pill is always touchable.
     */
    public static boolean windowFlagsTouchable(boolean screenOn) {
        return true;
    }

    /** No-arg overload: always true. */
    public static boolean windowFlagsTouchable() {
        return true;
    }

    /** Gesture onDown: always consumes (returns true). */
    public static boolean onDown() {
        return true;
    }

    /** Gesture onDown with coordinates: always true. */
    public static boolean onDown(float x, float y) {
        return true;
    }

    /** Gesture onDown with state hints: always true. */
    public static boolean onDown(boolean listening, boolean confirming) {
        return true;
    }

    /**
     * Tap dispatch.
     *
     * <ul>
     *   <li>if confirming return "cancel"</li>
     *   <li>else if listening return "stop_listen"</li>
     *   <li>else return "start_listen"</li>
     * </ul>
     */
    public static String onTap(boolean listening, boolean confirming, long listeningAgeMs) {
        if (confirming) {
            return "cancel";
        }
        if (listening) {
            return "stop_listen";
        }
        return "start_listen";
    }

    /** Long-press always opens the app unless a confirm prompt is showing. */
    public static String onLongPress(boolean confirming) {
        return confirming ? "ignore" : "open_app";
    }

    /** Listening-state overload. Confirm wins. */
    public static String onLongPress(boolean listening, boolean confirming) {
        return onLongPress(confirming);
    }

    /** Int overload delegates to the long version. */
    public static String onTap(boolean listening, boolean confirming, int listeningAgeMs) {
        return onTap(listening, confirming, (long) listeningAgeMs);
    }

    /** No-age overload defaults age to 0. */
    public static String onTap(boolean listening, boolean confirming) {
        return onTap(listening, confirming, 0L);
    }

    /**
     * Hit box centered on the camera cutout (matches IslandService layout).
     *
     * <p>cameraX/Y are the cutout center. The box is the visual capsule only
     * (pillW × pillH) plus optional left/right slop — never a strip below.
     *
     * @return float array {left, top, right, bottom}
     */
    public static float[] hitBox(float cameraX, float cameraY, float pillW, float pillH) {
        float slop = (float) HIT_SLOP_DP;
        float left = cameraX - pillW / 2f - slop;
        float top = cameraY - pillH / 2f;
        float right = cameraX + pillW / 2f + slop;
        float bottom = cameraY + pillH / 2f + (float) HIT_BELOW_DP;
        return new float[]{left, top, right, bottom};
    }

    /** Double overload delegates to the float version. */
    public static float[] hitBox(double cameraX, double cameraY, double pillW, double pillH) {
        return hitBox((float) cameraX, (float) cameraY, (float) pillW, (float) pillH);
    }

    /**
     * Named view of {@link #hitBox(float, float, float, float)}.
     *
     * @return map with left/top/right/bottom, visual x/y origin (== cameraX/cameraY),
     *         and expanded width/height (pill + 2*slop)
     */
    public static java.util.Map<String, Float> hitBoxMap(float cameraX, float cameraY, float pillW, float pillH) {
        float[] b = hitBox(cameraX, cameraY, pillW, pillH);
        float width = b[2] - b[0];
        float height = b[3] - b[1];
        java.util.Map<String, Float> m = new java.util.LinkedHashMap<String, Float>();
        m.put("left", Float.valueOf(b[0]));
        m.put("top", Float.valueOf(b[1]));
        m.put("right", Float.valueOf(b[2]));
        m.put("bottom", Float.valueOf(b[3]));
        m.put("x", Float.valueOf(cameraX));
        m.put("y", Float.valueOf(cameraY));
        m.put("originX", Float.valueOf(cameraX));
        m.put("originY", Float.valueOf(cameraY));
        m.put("width", Float.valueOf(width));
        m.put("height", Float.valueOf(height));
        return Collections.unmodifiableMap(m);
    }
}
