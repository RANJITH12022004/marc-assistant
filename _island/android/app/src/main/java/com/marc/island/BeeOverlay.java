package com.marc.island;

import java.lang.reflect.Method;

/**
 * Bee overlay contract (no Android imports; java.lang/reflect only).
 *
 * <p>Mirrors apps/bee-android/bee_overlay.py.
 * Hit overlay type MUST equal hero overlay type (crash fix).
 * Hourly cadence: unseen pills wait a full hour (never 8000ms).
 */
public final class BeeOverlay {

    /** Cutout center X in device px. Never change. */
    public static final float CAMERA_X = 540f;

    /** Cutout center Y in device px. Never change. */
    public static final float CAMERA_Y = 68.6f;

    /** Hourly cadence window (ms). */
    public static final long HOUR_MS = 3600000L;

    /** Whether to play on open; always false. */
    public static final boolean PLAY_ON_OPEN = false;

    private BeeOverlay() {
    }

    /**
     * Overlay type for the hero.
     *
     * @param hostBound true when host-bound via accessibility, false for application
     * @return "accessibility" if bound, else "application"
     */
    public static String overlayType(boolean hostBound) {
        return hostBound ? "accessibility" : "application";
    }

    /** Null-safe overload: null is treated as not bound. */
    public static String overlayType(Boolean hostBound) {
        return (hostBound != null && hostBound.booleanValue()) ? "accessibility" : "application";
    }

    /**
     * Hit overlay type; MUST equal {@link #overlayType(boolean)} (crash fix).
     */
    public static String hitOverlayType(boolean hostBound) {
        return overlayType(hostBound);
    }

    /** Null-safe overload: delegates to {@link #overlayType(Boolean)}. */
    public static String hitOverlayType(Boolean hostBound) {
        return overlayType(hostBound);
    }

    /**
     * Safely add a view via reflection; never throws.
     *
     * <p>Tries {@code add_view(name)} then {@code addView(name)}, falling back
     * to no-arg variants. Returns true on success, false on any failure.
     */
    public static boolean addViewSafe(Object wm, Object name) {
        try {
            if (wm == null) {
                return false;
            }
            String[] candidates = {"add_view", "addView"};
            for (int c = 0; c < candidates.length; c++) {
                String cand = candidates[c];
                Method[] methods;
                try {
                    methods = wm.getClass().getMethods();
                } catch (Throwable ignore) {
                    return false;
                }
                for (int i = 0; i < methods.length; i++) {
                    Method m = methods[i];
                    if (m == null || !cand.equals(m.getName())) {
                        continue;
                    }
                    try {
                        Class<?>[] ps = m.getParameterTypes();
                        if (ps.length == 1) {
                            try {
                                m.invoke(wm, new Object[]{name});
                                return true;
                            } catch (Throwable ignore) {
                                // fall through to try string form below
                            }
                            if (name != null) {
                                try {
                                    m.invoke(wm, new Object[]{String.valueOf(name)});
                                    return true;
                                } catch (Throwable ignore) {
                                    // continue searching
                                }
                            }
                        } else if (ps.length == 0) {
                            try {
                                m.invoke(wm, new Object[0]);
                                return true;
                            } catch (Throwable ignore) {
                                // continue searching
                            }
                        }
                    } catch (Throwable ignore) {
                        // continue searching
                    }
                }
            }
            return false;
        } catch (Throwable t) {
            return false;
        }
    }

    /** String overload delegates to the Object version. */
    public static boolean addViewSafe(Object wm, String name) {
        try {
            return addViewSafe(wm, (Object) name);
        } catch (Throwable t) {
            return false;
        }
    }

    /**
     * Hourly delay helper.
     *
     * <ul>
     *   <li>if not seen return HOUR_MS (never 8000)</li>
     *   <li>if now-last &lt; HOUR_MS return remaining</li>
     *   <li>else return 0 meaning due</li>
     * </ul>
     */
    public static long nextDelayMs(boolean seen, long lastMs, long nowMs) {
        if (!seen) {
            return HOUR_MS;
        }
        long elapsed = nowMs - lastMs;
        if (elapsed < 0L) {
            return HOUR_MS;
        }
        if (elapsed < HOUR_MS) {
            return HOUR_MS - elapsed;
        }
        return 0L;
    }

    /** Int overload delegates to the long version. */
    public static long nextDelayMs(boolean seen, int lastMs, int nowMs) {
        return nextDelayMs(seen, (long) lastMs, (long) nowMs);
    }

    /** Null-safe overload: null seen is treated as not seen. */
    public static long nextDelayMs(Boolean seen, long lastMs, long nowMs) {
        boolean s = (seen != null && seen.booleanValue());
        return nextDelayMs(s, lastMs, nowMs);
    }

    /** Whether to play on open; always false. */
    public static boolean playOnOpen() {
        return false;
    }
}
