package com.marc.island;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.RectF;
import android.util.AttributeSet;
import android.view.Choreographer;
import android.view.View;

/** A sport dial. A needle and a sharp light band share one scale, with the figure in the middle. */
public class StatusRing extends View {
    private static final float START = 150f;
    private static final float SWEEP = 240f;
    private static final int AMBER = 0xFFE8B15A;
    private static final int RED = 0xFFFF453A;
    private static final int WHITE = 0xFFF5F5F7;

    private final Paint bezel = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint tick = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint zone = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint band = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint needle = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint tip = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint hub = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint valuePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint captionPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final RectF oval = new RectF();
    private final Choreographer.FrameCallback tickFrame = this::onFrame;
    private float shown;
    private float target;
    private float velocity;
    private boolean rising = true;
    private boolean held;
    private boolean spinning;
    private boolean satellite;
    private long lastFrame;
    private String value = "—";
    private String caption = "";

    public StatusRing(Context context) {
        this(context, null);
    }

    public StatusRing(Context context, AttributeSet attrs) {
        super(context, attrs);
        setLongClickable(true);
        bezel.setStyle(Paint.Style.STROKE);
        bezel.setColor(WHITE);
        tick.setStyle(Paint.Style.STROKE);
        tick.setStrokeCap(Paint.Cap.ROUND);
        zone.setStyle(Paint.Style.STROKE);
        zone.setStrokeCap(Paint.Cap.BUTT);
        band.setStyle(Paint.Style.STROKE);
        band.setStrokeCap(Paint.Cap.BUTT);
        needle.setStyle(Paint.Style.STROKE);
        needle.setStrokeCap(Paint.Cap.ROUND);
        needle.setColor(WHITE);
        tip.setStyle(Paint.Style.STROKE);
        tip.setStrokeCap(Paint.Cap.ROUND);
        hub.setColor(WHITE);
        valuePaint.setColor(WHITE);
        valuePaint.setTextAlign(Paint.Align.CENTER);
        valuePaint.setFakeBoldText(true);
        captionPaint.setColor(AMBER);
        captionPaint.setTextAlign(Paint.Align.CENTER);
    }

    void setSatellite(boolean on) {
        satellite = on;
        invalidate();
    }

    void setReading(float fraction, String center, String label, int ignored) {
        value = center == null || center.isEmpty() ? "—" : center;
        caption = label == null ? "" : label;
        float next = Math.max(0f, Math.min(1f, fraction));
        if (!held) {
            shown = 0f;
            velocity = 0f;
            held = true;
        }
        float delta = next - shown;
        rising = delta >= 0f;
        target = next;
        if (Math.abs(delta) < 0.003f && Math.abs(velocity) < 0.02f) {
            shown = target;
            invalidate();
            return;
        }
        velocity += delta * 6f;
        kick();
    }

    private void kick() {
        if (spinning) {
            return;
        }
        spinning = true;
        lastFrame = 0L;
        Choreographer.getInstance().postFrameCallback(tickFrame);
    }

    private void onFrame(long now) {
        float dt = lastFrame == 0L ? 0.016f : (now - lastFrame) / 1_000_000_000f;
        lastFrame = now;
        if (dt > 0.05f) {
            dt = 0.05f;
        }
        float stiff = rising ? 340f : 72f;
        float damp = rising ? 13.5f : 8.5f;
        velocity += (stiff * (target - shown) - damp * velocity) * dt;
        shown += velocity * dt;
        if (Math.abs(target - shown) < 0.008f && Math.abs(velocity) < 0.03f) {
            shown = target;
            velocity = 0f;
            spinning = false;
        } else {
            Choreographer.getInstance().postFrameCallback(tickFrame);
        }
        invalidate();
    }

    @Override
    protected void onDetachedFromWindow() {
        spinning = false;
        Choreographer.getInstance().removeFrameCallback(tickFrame);
        super.onDetachedFromWindow();
    }

    @Override
    protected void onDraw(Canvas canvas) {
        float density = getResources().getDisplayMetrics().density;
        float pad = 4f * density;
        float size = Math.min(getWidth(), getHeight()) - pad * 2f;
        if (size <= 8f) {
            return;
        }
        float cx = getWidth() / 2f;
        float cy = getHeight() / 2f;
        float radius = size / 2f;
        float draw = Math.max(0f, Math.min(1f, shown));
        boolean hot = draw >= 0.82f;
        int lit = hot ? RED : AMBER;

        bezel.setStrokeWidth(Math.max(2.5f * density, radius * 0.035f));
        tick.setStrokeWidth(Math.max(1.2f * density, radius * 0.02f));
        zone.setStrokeWidth(Math.max(3f * density, radius * 0.07f));
        band.setStrokeWidth(Math.max(2.5f * density, radius * (satellite ? 0.055f : 0.07f)));
        needle.setStrokeWidth(Math.max(2f * density, radius * (satellite ? 0.03f : 0.028f)));
        tip.setStrokeWidth(Math.max(2.4f * density, radius * (satellite ? 0.04f : 0.038f)));

        float bezelR = radius * 0.96f;
        oval.set(cx - bezelR, cy - bezelR, cx + bezelR, cy + bezelR);
        canvas.drawCircle(cx, cy, bezelR, bezel);

        float bandR = radius * 0.78f;
        oval.set(cx - bandR, cy - bandR, cx + bandR, cy + bandR);
        zone.setColor(0x66FF453A);
        canvas.drawArc(oval, START + SWEEP * 0.82f, SWEEP * 0.18f, false, zone);
        for (int i = 0; i <= 12; i++) {
            float t = i / 12f;
            double ang = Math.toRadians(START + SWEEP * t);
            tick.setColor(t >= 0.82f ? RED : 0x66E8B15A);
            float inner = radius * 0.86f;
            float outer = radius * 0.93f;
            canvas.drawLine(
                    cx + (float) Math.cos(ang) * inner,
                    cy + (float) Math.sin(ang) * inner,
                    cx + (float) Math.cos(ang) * outer,
                    cy + (float) Math.sin(ang) * outer,
                    tick);
        }
        if (draw > 0.004f) {
            band.setColor(lit);
            canvas.drawArc(oval, START, SWEEP * draw, false, band);
        }
        double ang = Math.toRadians(START + SWEEP * draw);
        float reach = radius * (satellite ? 0.70f : 0.76f);
        float tail = radius * 0.12f;
        float cos = (float) Math.cos(ang);
        float sin = (float) Math.sin(ang);
        canvas.drawLine(cx - cos * tail, cy - sin * tail, cx + cos * reach, cy + sin * reach, needle);
        tip.setColor(lit);
        canvas.drawLine(cx + cos * reach * 0.72f, cy + sin * reach * 0.72f, cx + cos * reach, cy + sin * reach, tip);
        canvas.drawCircle(cx, cy, radius * (satellite ? 0.055f : 0.048f), hub);
        hub.setColor(0xFF101010);
        canvas.drawCircle(cx, cy, radius * (satellite ? 0.028f : 0.024f), hub);
        hub.setColor(WHITE);
        valuePaint.setTextSize(radius * (satellite ? 0.28f : 0.40f));
        captionPaint.setTextSize(radius * (satellite ? 0.12f : 0.11f));
        Paint.FontMetrics valueMetrics = valuePaint.getFontMetrics();
        float valueY = cy - (valueMetrics.ascent + valueMetrics.descent) / 2f - radius * 0.06f;
        canvas.drawText(value, cx, valueY, valuePaint);
        canvas.drawText(caption, cx, valueY + radius * (satellite ? 0.22f : 0.20f), captionPaint);
    }
}
