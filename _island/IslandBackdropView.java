package com.marc.island;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Matrix;
import android.graphics.Paint;
import android.graphics.RectF;
import android.graphics.SweepGradient;
import android.os.SystemClock;
import android.view.View;

/**
 * Animated capsule backdrop for the Dynamic Island.
 * During LISTENING, redraws are driven strictly by SpeechRecognizer onRmsChanged callbacks
 * so the main thread and Binder stay completely free for audio capture.
 * During THINKING / ACTING / CONFIRM, animates smoothly on the RenderThread/vsync.
 */
public final class IslandBackdropView extends View {
    public static final int STATE_IDLE = 0;
    public static final int STATE_LISTENING = 1;
    public static final int STATE_THINKING = 2;
    public static final int STATE_ACTING = 3;
    public static final int STATE_CONFIRM = 4;
    public static final int STATE_ERROR = 5;

    private final Paint fillPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint rimPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint glowPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final RectF rect = new RectF();
    private final RectF glowRect = new RectF();
    private final Matrix shaderMatrix = new Matrix();

    private SweepGradient listenShader;
    private SweepGradient thinkShader;
    private int lastW;
    private int lastH;

    private final Paint facePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private int state = STATE_IDLE;
    private float voiceLevel;
    private float angle;
    private long stateStartMs;
    private long faceStart = -1;

    public IslandBackdropView(Context context) {
        super(context);
        fillPaint.setStyle(Paint.Style.FILL);
        fillPaint.setColor(0xF5040507);

        rimPaint.setStyle(Paint.Style.STROKE);
        glowPaint.setStyle(Paint.Style.STROKE);
        facePaint.setColor(0xFFF5F5F7);
    }

    public void showFace() {
        faceStart = SystemClock.uptimeMillis();
        invalidate();
    }

    public void setState(int newState) {
        if (this.state == newState && newState != STATE_ACTING && newState != STATE_ERROR) {
            return;
        }
        this.state = newState;
        this.stateStartMs = SystemClock.uptimeMillis();
        if (newState != STATE_LISTENING) {
            this.voiceLevel = 0f;
        }
        invalidate();
    }

    public int getState() {
        return state;
    }

    public void setVoiceLevel(float level) {
        float clamped = Math.max(0f, Math.min(1f, level));
        this.voiceLevel = this.voiceLevel * 0.6f + clamped * 0.4f;
        this.angle = (this.angle + 8f + this.voiceLevel * 14f) % 360f;
        if (state == STATE_LISTENING) {
            invalidate();
        }
    }

    private void ensureShaders(int w, int h) {
        if (w == lastW && h == lastH && listenShader != null && thinkShader != null) {
            return;
        }
        lastW = w;
        lastH = h;
        float cx = w / 2f;
        float cy = h / 2f;
        listenShader = new SweepGradient(
                cx, cy,
                new int[]{0xFFFFFFFF, 0xFFD1D1D6, 0xFFFFFFFF, 0x33FFFFFF, 0xFFFFFFFF},
                new float[]{0f, 0.28f, 0.55f, 0.82f, 1f});
        thinkShader = new SweepGradient(
                cx, cy,
                new int[]{0xFFFFFFFF, 0xFFE5E5EA, 0xFFFFFFFF, 0x33FFFFFF, 0xFFFFFFFF},
                new float[]{0f, 0.3f, 0.6f, 0.85f, 1f});
    }

    @Override
    protected void onDraw(Canvas canvas) {
        int w = getWidth();
        int h = getHeight();
        if (w <= 0 || h <= 0) {
            return;
        }
        float d = getResources().getDisplayMetrics().density;
        ensureShaders(w, h);

        float inset = 2.0f * d;
        rect.set(inset, inset, w - inset, h - inset);
        float radius = rect.height() / 2f;

        long now = SystemClock.uptimeMillis();
        long elapsed = now - stateStartMs;

        if (state == STATE_LISTENING) {
            shaderMatrix.setRotate(angle, w / 2f, h / 2f);
            listenShader.setLocalMatrix(shaderMatrix);

            glowPaint.setShader(null);
            glowPaint.setColor(0x33FFFFFF);
            glowPaint.setAlpha(Math.min(160, Math.round(55 + voiceLevel * 95)));
            glowPaint.setStrokeWidth((2.2f + voiceLevel * 2.0f) * d);
            float gInset = 1.0f * d;
            glowRect.set(gInset, gInset, w - gInset, h - gInset);
            canvas.drawRoundRect(glowRect, glowRect.height() / 2f, glowRect.height() / 2f, glowPaint);

            canvas.drawRoundRect(rect, radius, radius, fillPaint);

            rimPaint.setShader(listenShader);
            rimPaint.setStrokeWidth((1.6f + voiceLevel * 0.8f) * d);
            rimPaint.setAlpha(245);
            canvas.drawRoundRect(rect, radius, radius, rimPaint);
            // Note: do NOT loop postInvalidateOnAnimation during LISTENING; onRmsChanged drives redraws!
        } else if (state == STATE_THINKING) {
            angle = (angle + 5.0f) % 360f;
            shaderMatrix.setRotate(angle, w / 2f, h / 2f);
            thinkShader.setLocalMatrix(shaderMatrix);

            canvas.drawRoundRect(rect, radius, radius, fillPaint);

            rimPaint.setShader(thinkShader);
            rimPaint.setStrokeWidth(1.7f * d);
            rimPaint.setAlpha(240);
            canvas.drawRoundRect(rect, radius, radius, rimPaint);
            postInvalidateDelayed(32);
        } else if (state == STATE_ACTING || state == STATE_ERROR) {
            float t = Math.min(1f, elapsed / 600f);
            float fade = 1f - t;
            int baseColor = state == STATE_ERROR ? 0xFFFF453A : 0xFF30D158;

            canvas.drawRoundRect(rect, radius, radius, fillPaint);

            rimPaint.setShader(null);
            rimPaint.setColor(baseColor);
            rimPaint.setStrokeWidth(1.6f * d);
            rimPaint.setAlpha(Math.max(40, Math.round(235 * fade)));
            canvas.drawRoundRect(rect, radius, radius, rimPaint);
            if (t < 1f) {
                postInvalidateDelayed(32);
            } else {
                state = STATE_IDLE;
                invalidate();
            }
        } else if (state == STATE_CONFIRM) {
            float pulse = 0.5f + 0.5f * (float) Math.sin(now * 0.008);
            canvas.drawRoundRect(rect, radius, radius, fillPaint);
            rimPaint.setShader(null);
            rimPaint.setColor(0xFFFF9F0A);
            rimPaint.setStrokeWidth(1.6f * d);
            rimPaint.setAlpha(120 + Math.round(120 * pulse));
            canvas.drawRoundRect(rect, radius, radius, rimPaint);
            postInvalidateDelayed(40);
        } else {
            canvas.drawRoundRect(rect, radius, radius, fillPaint);
            rimPaint.setShader(null);
            rimPaint.setColor(0x22FFFFFF);
            rimPaint.setStrokeWidth(0.9f * d);
            canvas.drawRoundRect(rect, radius, radius, rimPaint);
        }
        drawFace(canvas, w, h);
    }

    private void drawFace(Canvas canvas, int w, int h) {
        if (faceStart < 0) {
            return;
        }
        long elapsed = SystemClock.uptimeMillis() - faceStart;
        if (elapsed > 1100) {
            faceStart = -1;
            return;
        }
        float alpha;
        if (elapsed < 180) {
            alpha = elapsed / 180f;
        } else if (elapsed < 820) {
            alpha = 1f;
        } else {
            alpha = 1f - (elapsed - 820) / 280f;
        }
        facePaint.setAlpha(Math.max(0, Math.round(255 * alpha)));
        facePaint.setStyle(Paint.Style.FILL);
        float cx = w / 2f;
        float cy = h / 2f;
        float scale = Math.min(w, h) / 43f;
        canvas.drawCircle(cx - 7f * scale, cy - 3f * scale, 1.7f * scale, facePaint);
        canvas.drawCircle(cx + 7f * scale, cy - 3f * scale, 1.7f * scale, facePaint);
        facePaint.setStyle(Paint.Style.STROKE);
        facePaint.setStrokeWidth(Math.max(1.2f, 1.4f * scale));
        facePaint.setStrokeCap(Paint.Cap.ROUND);
        RectF mouth = new RectF(cx - 6f * scale, cy + 1f * scale, cx + 6f * scale, cy + 9f * scale);
        canvas.drawArc(mouth, 15, 150, false, facePaint);
        facePaint.setStyle(Paint.Style.FILL);
        postInvalidateDelayed(32);
    }
}
