package com.marc.island;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import android.util.Log;

import java.nio.charset.StandardCharsets;
import java.security.KeyStore;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/**
 * Encrypted key vault via Android Keystore AES-GCM (EncryptedSharedPreferences
 * equivalent without an extra Gradle artifact). Never logs Bearer tokens.
 */
public final class MuseStore {
    private static final String TAG = "MuseStore";
    public static final String SPARK_MODEL = "muse-spark-1.3";
    public static final String WONDER_MODEL = "muse-wonder-1.0";
    public static final String VOICE_MODEL = "muse-voice-transcribe-1.0";
    private static final String PREFS = "bee_muse";
    private static final String KEY = "api_key";
    private static final String MASK = "key_mask";
    private static final String MODE = "marc_mode";
    private static final String DRIVING = "driving";
    private static final String MODEL_SLOT = "model_slot";
    private static final String ANDROID_KEYSTORE = "AndroidKeyStore";
    private static final String MASTER = "bee_muse_master";

    private MuseStore() {
    }

    public static boolean needleEnabled() {
        return false;
    }

    public static String maskKey(String key) {
        if (key == null || key.isEmpty()) {
            return "";
        }
        if (key.length() <= 4) {
            return "\u2026";
        }
        if (key.length() <= 8) {
            return "\u2026" + key.substring(key.length() - 4);
        }
        return key.substring(0, 4) + "\u2026" + key.substring(key.length() - 4);
    }

    public static void saveKey(Context context, String key) {
        if (key == null || key.trim().isEmpty()) {
            throw new IllegalArgumentException("key must be a non-empty string");
        }
        String trimmed = key.trim();
        prefs(context).edit()
                .putString(KEY, seal(trimmed))
                .putString(MASK, maskKey(trimmed))
                .apply();
    }

    public static String getKey(Context context) {
        return open(prefs(context).getString(KEY, ""));
    }

    public static boolean hasKey(Context context) {
        String key = getKey(context);
        return key != null && !key.trim().isEmpty();
    }

    public static String getMask(Context context) {
        String stored = prefs(context).getString(MASK, "");
        if (stored != null && !stored.isEmpty()) {
            return stored;
        }
        return maskKey(getKey(context));
    }

    public static void saveMode(Context context, String mode) {
        prefs(context).edit().putString(MODE, mode == null ? "sandbox" : mode).apply();
    }

    public static String getMode(Context context) {
        return prefs(context).getString(MODE, "sandbox");
    }

    public static void saveDriving(Context context, boolean driving) {
        prefs(context).edit().putBoolean(DRIVING, driving).apply();
    }

    public static boolean isDriving(Context context) {
        return prefs(context).getBoolean(DRIVING, false);
    }

    public static void saveModelSlot(Context context, String slot) {
        prefs(context).edit().putString(MODEL_SLOT, slot == null ? "spark" : slot).apply();
    }

    public static String getModelSlot(Context context) {
        return prefs(context).getString(MODEL_SLOT, "spark");
    }

    public static String modelName(String slot) {
        if ("wonder".equals(slot)) {
            return WONDER_MODEL;
        }
        if ("voice".equals(slot)) {
            return VOICE_MODEL;
        }
        return SPARK_MODEL;
    }

    static SharedPreferences prefs(Context context) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    private static String seal(String plain) {
        try {
            SecretKey secret = master();
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, secret);
            byte[] iv = cipher.getIV();
            byte[] packed = cipher.doFinal(plain.getBytes(StandardCharsets.UTF_8));
            byte[] all = new byte[iv.length + packed.length];
            System.arraycopy(iv, 0, all, 0, iv.length);
            System.arraycopy(packed, 0, all, iv.length, packed.length);
            return Base64.encodeToString(all, Base64.NO_WRAP);
        } catch (Exception exc) {
            Log.w(TAG, "seal fallback");
            return plain;
        }
    }

    private static String open(String stored) {
        if (stored == null || stored.isEmpty()) {
            return "";
        }
        try {
            byte[] all = Base64.decode(stored, Base64.NO_WRAP);
            if (all.length < 13) {
                return stored;
            }
            byte[] iv = new byte[12];
            byte[] packed = new byte[all.length - 12];
            System.arraycopy(all, 0, iv, 0, 12);
            System.arraycopy(all, 12, packed, 0, packed.length);
            SecretKey secret = master();
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, secret, new GCMParameterSpec(128, iv));
            return new String(cipher.doFinal(packed), StandardCharsets.UTF_8);
        } catch (Exception exc) {
            return stored;
        }
    }

    private static SecretKey master() throws Exception {
        KeyStore store = KeyStore.getInstance(ANDROID_KEYSTORE);
        store.load(null);
        if (store.containsAlias(MASTER)) {
            return (SecretKey) store.getKey(MASTER, null);
        }
        KeyGenerator gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE);
        gen.init(new KeyGenParameterSpec.Builder(MASTER,
                KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .build());
        return gen.generateKey();
    }
}
