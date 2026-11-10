package com.marc.island;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.RectF;
import android.view.View;

/**
 * 5-bar voice/thinking equalizer inside the Dynamic Island.
 * Driven by onRmsChanged during LISTENING (zero continuous loop overhead during mic capture)
 * and a gentle 30fps pulse during THINKING.
 */
public final class IslandWaveView extends View {
    private static final int BARS = 5;
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final RectF barRect = new RectF();
    private final float[] heights = new float[BARS];

    private boolean active;
    private boolean thinking;
    private float level;
    private float phase;

    public IslandWaveView(Context context) {
        super(context);
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(0xFFFFFFFF);
    }

    public void setMode(boolean active, boolean thinking) {
        this.active = active;
        this.thinking = thinking;
        paint.setColor(thinking ? 0xFFFFFFFF : 0xFFFFFFFF);
        setVisibility(active ? VISIBLE : GONE);
        if (active) {
            invalidate();
        }
    }

    public void setLevel(float rmsLevel) {
        float clamped = Math.max(0f, Math.min(1f, rmsLevel));
        this.level = this.level * 0.55f + clamped * 0.45f;
        this.phase += 0.45f + this.level * 0.35f;
        if (active) {
            invalidate();
        }
    }

    @Override
    protected void onDraw(Canvas canvas) {
        if (!active) {
            return;
        }
        int w = getWidth();
        int h = getHeight();
        if (w <= 0 || h <= 0) {
            return;
        }
        float d = getResources().getDisplayMetrics().density;
        if (thinking) {
            phase += 0.32f;
        }

        float barW = 2.6f * d;
        float gap = 2.2f * d;
        float totalW = BARS * barW + (BARS - 1) * gap;
        float startX = (w - totalW) / 2f;
        float cy = h / 2f;
        float minH = 3.2f * d;
        float maxH = h - 4f * d;

        for (int i = 0; i < BARS; i++) {
            float wave = 0.5f + 0.5f * (float) Math.sin(phase + i * 0.9f);
            float centerBoost = (i == 2) ? 1.15f : (i == 1 || i == 3) ? 0.95f : 0.7f;
            float drive = thinking ? (0.35f + 0.45f * wave) : (0.20f * wave + level * 0.85f * (0.4f + 0.6f * wave));
            float target = minH + Math.min(1f, drive * centerBoost) * (maxH - minH);
            heights[i] = heights[i] == 0f ? target : (heights[i] * 0.5f + target * 0.5f);

            float bh = heights[i];
            float x = startX + i * (barW + gap);
            barRect.set(x, cy - bh / 2f, x + barW, cy + bh / 2f);
            canvas.drawRoundRect(barRect, barW / 2f, barW / 2f, paint);
        }

        if (thinking) {
            postInvalidateDelayed(36);
        }
    }
}
