package com.marc.island;

import android.accessibilityservice.AccessibilityService;
import android.content.Intent;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;

import java.lang.ref.WeakReference;

/**
 * Hosts the island window. A normal overlay sits under the status bar, so a
 * tap on the camera opens the shade instead of Marc. This service is what
 * lets the pill sit above that bar and take the tap.
 */
public class IslandAccess extends AccessibilityService {
    private static WeakReference<IslandAccess> self;
    private static volatile String foreground = "";

    @Override
    protected void onServiceConnected() {
        self = new WeakReference<>(this);
        IslandService.bindHost(this);
        Intent intent = new Intent(this, IslandService.class);
        startForegroundService(intent);
    }

    static String foreground() {
        return foreground == null ? "" : foreground;
    }

    static boolean quickSettings() {
        return global(GLOBAL_ACTION_QUICK_SETTINGS);
    }

    static void closeShade() {
        if (android.os.Build.VERSION.SDK_INT >= 31) {
            global(android.accessibilityservice.AccessibilityService.GLOBAL_ACTION_DISMISS_NOTIFICATION_SHADE);
            return;
        }
        global(GLOBAL_ACTION_BACK);
    }

    private static boolean global(int action) {
        IslandAccess service = self == null ? null : self.get();
        return service != null && service.performGlobalAction(action);
    }

    static AccessibilityNodeInfo root() {
        IslandAccess service = self == null ? null : self.get();
        if (service == null) {
            return null;
        }
        return service.getRootInActiveWindow();
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        if (event == null || event.getEventType() != AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) {
            return;
        }
        CharSequence pkg = event.getPackageName();
        if (pkg == null || "com.marc.island".equals(pkg.toString())) {
            return;
        }
        foreground = pkg.toString();
        if (PaymentApps.isPayment(foreground)) {
            MarcPresence.stepAside(this);
        }
    }

    @Override
    public void onInterrupt() {
    }

    @Override
    public void onDestroy() {
        self = null;
        IslandService.bindHost(null);
        super.onDestroy();
    }
}
