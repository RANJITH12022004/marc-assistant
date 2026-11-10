package com.marc.island;

import android.content.Context;
import android.content.Intent;
import android.media.AudioManager;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Log;
import android.view.KeyEvent;

/**
 * An empty request resumes Spotify. A song name asks Spotify to play that title.
 */
final class SpotifyPlay {
    private static final String TAG = "MarcIsland";

    private SpotifyPlay() {}

    static void request(Context context, String query) {
        Context app = context.getApplicationContext();
        String asked = query == null ? "" : query.trim();
        if (asked.isEmpty()) {
            pressPlay(app);
            return;
        }
        if (playNamed(app, asked)) {
            return;
        }
        Log.i(TAG, "spotify named search missed");
    }

    static void pressPlay(Context context) {
        media(context, "play");
    }

    static void media(Context context, String action) {
        int code = KeyEvent.KEYCODE_MEDIA_PLAY;
        if ("next".equals(action)) {
            code = KeyEvent.KEYCODE_MEDIA_NEXT;
        } else if ("previous".equals(action)) {
            code = KeyEvent.KEYCODE_MEDIA_PREVIOUS;
        } else if ("pause".equals(action) || "stop".equals(action)) {
            code = KeyEvent.KEYCODE_MEDIA_PAUSE;
        }
        AudioManager audio = (AudioManager) context.getSystemService(Context.AUDIO_SERVICE);
        long time = SystemClock.uptimeMillis();
        audio.dispatchMediaKeyEvent(new KeyEvent(time, time, KeyEvent.ACTION_DOWN, code, 0));
        audio.dispatchMediaKeyEvent(new KeyEvent(time, time, KeyEvent.ACTION_UP, code, 0));
        Log.i(TAG, "media " + action);
    }

    /** Open the song, then tap it and Play. Search alone does not start audio. */
    private static boolean playNamed(Context context, String query) {
        Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse("spotify:search:" + Uri.encode(query)));
        intent.setPackage("com.spotify.music");
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        try {
            context.startActivity(intent);
            Log.i(TAG, "spotify play " + query);
        } catch (RuntimeException exc) {
            Log.e(TAG, "spotify play", exc);
            return false;
        }
        Handler handler = new Handler(Looper.getMainLooper());
        handler.postDelayed(() -> finishPlay(context, query, 0), 900);
        return true;
    }

    private static void finishPlay(Context context, String query, int attempt) {
        if (ScreenHands.clickSong(query)) {
            new Handler(Looper.getMainLooper()).postDelayed(() -> {
                if (!ScreenHands.clickAny("Play " + query, "Play", "play")) {
                    pressPlay(context);
                }
            }, 700);
            return;
        }
        if (ScreenHands.clickAny("Play " + query, "Play " + query.toLowerCase())) {
            return;
        }
        if (attempt >= 8) {
            Log.i(TAG, "spotify row missed");
            return;
        }
        new Handler(Looper.getMainLooper()).postDelayed(() -> finishPlay(context, query, attempt + 1), 500);
    }
}
