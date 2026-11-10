package com.marc.island;

import android.bluetooth.BluetoothAdapter;
import android.content.Context;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraManager;
import android.media.AudioManager;
import android.net.wifi.WifiManager;
import android.os.Handler;
import android.os.Looper;

import java.util.Locale;

/** Radios and the flashlight. One new control is one branch here. Apps stay on open_app. */
final class PhoneControls {
    private static boolean torch;

    private PhoneControls() {}

    static String handle(Context context, String phrase) {
        String low = phrase == null ? "" : phrase.toLowerCase(Locale.US);
        if (low.contains("bluetooth")) {
            return radio(context, "Bluetooth", bluetoothOn(context), low, "Bluetooth");
        }
        if (low.contains("wifi") || low.contains("wi-fi")) {
            return radio(context, "Wi-Fi", wifiOn(context), low, "Wi-Fi", "WLAN", "Wifi");
        }
        if (low.contains("internet") || low.contains("mobile data")) {
            tapTile("Internet", "Mobile data");
            return low.contains("off") ? "Internet off." : "Internet on.";
        }
        if (low.contains("flash") || low.contains("torch")) {
            boolean want = want(low, torch);
            if (!setTorch(context, want)) {
                return "I couldn't use the flashlight.";
            }
            torch = want;
            return want ? "Flash on." : "Flash off.";
        }
        if (low.contains("volume") || low.contains("louder") || low.contains("quieter")) {
            boolean down = low.contains("down") || low.contains("quieter");
            AudioManager audio = (AudioManager) context.getSystemService(Context.AUDIO_SERVICE);
            audio.adjustStreamVolume(
                    AudioManager.STREAM_MUSIC,
                    down ? AudioManager.ADJUST_LOWER : AudioManager.ADJUST_RAISE,
                    AudioManager.FLAG_SHOW_UI);
            return down ? "Volume down." : "Volume up.";
        }
        return null;
    }

    private static String radio(Context context, String name, boolean current, String phrase, String... labels) {
        boolean want = want(phrase, !current);
        if (current == want) {
            return want ? name + " on." : name + " off.";
        }
        tapTile(labels);
        return want ? name + " on." : name + " off.";
    }

    private static boolean want(String phrase, boolean fallback) {
        if (phrase.contains("off") || phrase.contains("disable")) {
            return false;
        }
        if (phrase.contains("on") || phrase.contains("enable")) {
            return true;
        }
        return fallback;
    }

    private static void tapTile(String... labels) {
        if (!IslandAccess.quickSettings()) {
            PhoneActions.fail("I couldn't open quick settings.");
            return;
        }
        Handler handler = new Handler(Looper.getMainLooper());
        handler.postDelayed(() -> {
            if (!ScreenHands.clickAny(labels)) {
                IslandAccess.closeShade();
                PhoneActions.fail("I couldn't find " + labels[0] + ".");
                return;
            }
            handler.postDelayed(IslandAccess::closeShade, 450);
        }, 700);
    }

    private static boolean bluetoothOn(Context context) {
        try {
            BluetoothAdapter adapter = BluetoothAdapter.getDefaultAdapter();
            return adapter != null && adapter.isEnabled();
        } catch (SecurityException ignored) {
            return false;
        }
    }

    private static boolean wifiOn(Context context) {
        try {
            WifiManager wifi = (WifiManager) context.getSystemService(Context.WIFI_SERVICE);
            return wifi != null && wifi.isWifiEnabled();
        } catch (SecurityException ignored) {
            return false;
        }
    }

    private static boolean setTorch(Context context, boolean on) {
        try {
            CameraManager cameras = (CameraManager) context.getSystemService(Context.CAMERA_SERVICE);
            if (cameras == null) {
                return false;
            }
            for (String id : cameras.getCameraIdList()) {
                Boolean flash = cameras.getCameraCharacteristics(id).get(CameraCharacteristics.FLASH_INFO_AVAILABLE);
                if (Boolean.TRUE.equals(flash)) {
                    cameras.setTorchMode(id, on);
                    return true;
                }
            }
        } catch (Exception ignored) {
            return false;
        }
        return false;
    }
}
