package com.marc.island;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;
import android.os.SystemClock;
import android.view.View;
import android.view.animation.AccelerateInterpolator;
import android.view.animation.DecelerateInterpolator;
import android.view.animation.OvershootInterpolator;

/**
 * Hourly water reminder: a spider-suited hero climbs out of the punch-hole
 * on a web, asks for a drink, then swings back in.
 */
public final class HydrationHeroView extends View {
    interface Host {
        void onOffer();

        void onOffering(boolean offering);

        void onFinished(boolean drank);
    }

    static final int BEAT_IDLE = 0;
    private static final int BEAT_PEEK = 1;
    private static final int BEAT_CLIMB = 2;
    private static final int BEAT_SWING = 3;
    private static final int BEAT_POINT = 4;
    private static final int BEAT_OFFER = 5;
    private static final int BEAT_CELEBRATE = 6;
    private static final int BEAT_SHOOT = 7;
    private static final int BEAT_RETURN = 8;

    private static final float CAMERA_X = 540f;
    private static final float CAMERA_Y = 68.6f;
    private static final long OFFER_MS = 12000L;

    private final Paint fill = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint stroke = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint webGlow = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint webCore = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint textPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Path path = new Path();
    private final RectF oval = new RectF();
    private final OvershootInterpolator overshoot = new OvershootInterpolator(1.7f);
    private final DecelerateInterpolator decelerate = new DecelerateInterpolator();
    private final AccelerateInterpolator accelerate = new AccelerateInterpolator();

    private Host host;
    private int beat = BEAT_IDLE;
    private long beatStart;
    private boolean drank;
    private boolean spoken;
    private float density = 2.625f;

    public HydrationHeroView(Context context) {
        super(context);
        setWillNotDraw(false);
        webGlow.setStyle(Paint.Style.STROKE);
        webGlow.setStrokeCap(Paint.Cap.ROUND);
        webCore.setStyle(Paint.Style.STROKE);
        webCore.setStrokeCap(Paint.Cap.ROUND);
        webCore.setColor(0xFFF4FBFF);
        stroke.setStyle(Paint.Style.STROKE);
        stroke.setStrokeJoin(Paint.Join.ROUND);
        stroke.setStrokeCap(Paint.Cap.ROUND);
        textPaint.setColor(0xFF1A2232);
        textPaint.setFakeBoldText(true);
        setClickable(false);
    }

    void setHost(Host host) {
        this.host = host;
    }

    boolean isPlaying() {
        return beat != BEAT_IDLE;
    }

    boolean isOffering() {
        return beat == BEAT_OFFER;
    }

    void play() {
        drank = false;
        spoken = false;
        go(BEAT_PEEK);
        setClickable(false);
        invalidate();
    }

    void stopQuiet() {
        boolean offering = beat == BEAT_OFFER;
        beat = BEAT_IDLE;
        setClickable(false);
        if (offering && host != null) {
            host.onOffering(false);
        }
        invalidate();
    }

    void acceptDrink() {
        if (beat != BEAT_OFFER) {
            return;
        }
        drank = true;
        go(BEAT_CELEBRATE);
        invalidate();
    }

    private void go(int next) {
        boolean offering = next == BEAT_OFFER;
        boolean wasOffering = beat == BEAT_OFFER;
        beat = next;
        beatStart = SystemClock.uptimeMillis();
        setClickable(offering);
        if (host != null && offering != wasOffering) {
            host.onOffering(offering);
        }
    }

    private long elapsed() {
        return SystemClock.uptimeMillis() - beatStart;
    }

    private float unit(float t, long duration) {
        return Math.max(0f, Math.min(1f, t / duration));
    }

    @Override
    protected void onDraw(Canvas canvas) {
        density = getResources().getDisplayMetrics().density;
        if (beat == BEAT_IDLE) {
            return;
        }
        long ms = elapsed();
        switch (beat) {
            case BEAT_PEEK:
                if (ms >= 300) {
                    go(BEAT_CLIMB);
                    ms = 0;
                }
                break;
            case BEAT_CLIMB:
                if (ms >= 320) {
                    go(BEAT_SWING);
                    ms = 0;
                }
                break;
            case BEAT_SWING:
                if (ms >= 420) {
                    go(BEAT_POINT);
                    ms = 0;
                }
                break;
            case BEAT_POINT:
                if (ms >= 480) {
                    go(BEAT_OFFER);
                    ms = 0;
                }
                break;
            case BEAT_OFFER:
                if (!spoken) {
                    spoken = true;
                    if (host != null) {
                        host.onOffer();
                    }
                }
                if (ms >= OFFER_MS) {
                    drank = false;
                    go(BEAT_SHOOT);
                    ms = 0;
                }
                break;
            case BEAT_CELEBRATE:
                if (ms >= 700) {
                    go(BEAT_SHOOT);
                    ms = 0;
                }
                break;
            case BEAT_SHOOT:
                if (ms >= 420) {
                    go(BEAT_RETURN);
                    ms = 0;
                }
                break;
            case BEAT_RETURN:
                if (ms >= 620) {
                    beat = BEAT_IDLE;
                    setClickable(false);
                    if (host != null) {
                        host.onFinished(drank);
                    }
                    return;
                }
                break;
            default:
                break;
        }
        drawScene(canvas, ms);
        postInvalidateOnAnimation();
    }

    private void drawScene(Canvas canvas, long ms) {
        float d = density;
        float hx = heroX();
        float hy = heroY();
        float scale = heroScale();
        float rot = heroRot();
        float squash = heroSquash();
        int face = heroFace();
        boolean bottle = beat == BEAT_OFFER || beat == BEAT_POINT || beat == BEAT_CELEBRATE;
        float webLen = webLength();

        float handX = hx + 22f * d * scale * (float) Math.sin(Math.toRadians(rightArm()));
        float handY = hy - 18f * d * scale + 26f * d * scale * (float) Math.cos(Math.toRadians(rightArm()));
        if (beat == BEAT_SWING || beat == BEAT_CLIMB || beat == BEAT_SHOOT || beat == BEAT_RETURN) {
            handX = hx - 8f * d * scale;
            handY = hy - 36f * d * scale;
        }

        if (webLen > 0.04f) {
            float endX = CAMERA_X + (handX - CAMERA_X) * webLen;
            float endY = CAMERA_Y + (handY - CAMERA_Y) * webLen;
            webGlow.setStrokeWidth(4.2f * d);
            webGlow.setColor(0xAA7EC8FF);
            canvas.drawLine(CAMERA_X, CAMERA_Y, endX, endY, webGlow);
            webCore.setStrokeWidth(1.6f * d);
            canvas.drawLine(CAMERA_X, CAMERA_Y, endX, endY, webCore);
        }

        canvas.save();
        canvas.translate(hx, hy);
        canvas.rotate(rot);
        canvas.scale(scale, scale * squash);
        drawHero(canvas, face, bottle, beat == BEAT_POINT, beat == BEAT_CELEBRATE);
        canvas.restore();

        if (beat == BEAT_OFFER) {
            drawBubble(canvas, hx, hy - 78f * d, impatient() ? "Drink water!" : "Drink water!");
            drawHint(canvas, hx, hy + 78f * d);
        } else if (beat == BEAT_POINT) {
            float u = decelerate.getInterpolation(unit(ms, 480));
            if (u > 0.35f) {
                drawBubble(canvas, hx, hy - 78f * d, "Water break?");
            }
        } else if (beat == BEAT_CELEBRATE) {
            drawBubble(canvas, hx, hy - 82f * d, "Nice.");
        }
    }

    private boolean impatient() {
        return beat == BEAT_OFFER && elapsed() > 3500;
    }

    private float heroX() {
        float d = density;
        switch (beat) {
            case BEAT_PEEK:
                return CAMERA_X;
            case BEAT_CLIMB:
                return CAMERA_X + 8f * d * decelerate.getInterpolation(unit(elapsed(), 320));
            case BEAT_SWING: {
                float u = decelerate.getInterpolation(unit(elapsed(), 420));
                float theta = (float) Math.toRadians(48f - 62f * u);
                return CAMERA_X + (float) Math.sin(theta) * 118f * d;
            }
            case BEAT_RETURN: {
                float u = accelerate.getInterpolation(unit(elapsed(), 620));
                return lerp(CAMERA_X + 18f * d, CAMERA_X, u);
            }
            default:
                return CAMERA_X + 18f * d;
        }
    }

    private float heroY() {
        float d = density;
        float island = CAMERA_Y + 22f * d;
        switch (beat) {
            case BEAT_PEEK: {
                float u = overshoot.getInterpolation(unit(elapsed(), 300));
                return island + lerp(4f * d, 36f * d, u);
            }
            case BEAT_CLIMB: {
                float u = decelerate.getInterpolation(unit(elapsed(), 320));
                return island + lerp(36f * d, 92f * d, u);
            }
            case BEAT_SWING: {
                float u = decelerate.getInterpolation(unit(elapsed(), 420));
                float theta = (float) Math.toRadians(48f - 62f * u);
                return CAMERA_Y + 10f * d + (float) Math.cos(theta) * 118f * d;
            }
            case BEAT_POINT: {
                float u = overshoot.getInterpolation(unit(elapsed(), 480));
                float bounce = (1f - u) * 10f * d;
                return CAMERA_Y + 148f * d + bounce;
            }
            case BEAT_OFFER: {
                float bob = (float) Math.sin(elapsed() * 0.007) * 3.2f * d;
                float tap = impatient() ? (float) Math.abs(Math.sin(elapsed() * 0.02)) * 4f * d : 0f;
                return CAMERA_Y + 152f * d + bob + tap;
            }
            case BEAT_CELEBRATE: {
                float hop = (float) Math.abs(Math.sin(elapsed() * 0.014)) * 16f * d;
                return CAMERA_Y + 148f * d - hop;
            }
            case BEAT_SHOOT:
                return CAMERA_Y + 148f * d;
            case BEAT_RETURN: {
                float u = accelerate.getInterpolation(unit(elapsed(), 620));
                return lerp(CAMERA_Y + 148f * d, CAMERA_Y + 4f * d, u);
            }
            default:
                return CAMERA_Y;
        }
    }

    private float heroScale() {
        switch (beat) {
            case BEAT_PEEK:
                return 0.42f + 0.18f * overshoot.getInterpolation(unit(elapsed(), 300));
            case BEAT_CLIMB:
                return 0.62f + 0.18f * unit(elapsed(), 320);
            case BEAT_SWING:
                return 0.82f;
            case BEAT_RETURN:
                return lerp(0.86f, 0.18f, accelerate.getInterpolation(unit(elapsed(), 620)));
            default:
                return 0.86f;
        }
    }

    private float heroRot() {
        switch (beat) {
            case BEAT_SWING:
                return 18f - 38f * unit(elapsed(), 420);
            case BEAT_SHOOT:
                return -8f;
            case BEAT_RETURN:
                return lerp(-12f, 28f, unit(elapsed(), 620));
            case BEAT_CELEBRATE:
                return (float) Math.sin(elapsed() * 0.02) * 8f;
            default:
                return 0f;
        }
    }

    private float heroSquash() {
        if (beat == BEAT_PEEK) {
            return 0.82f + 0.18f * unit(elapsed(), 300);
        }
        if (beat == BEAT_POINT && elapsed() < 160) {
            return 0.88f;
        }
        return 1f;
    }

    private int heroFace() {
        if (beat == BEAT_PEEK || beat == BEAT_CLIMB) {
            return 1;
        }
        if (beat == BEAT_OFFER && impatient()) {
            return 2;
        }
        if (beat == BEAT_CELEBRATE) {
            return 3;
        }
        return 0;
    }

    private float rightArm() {
        if (beat == BEAT_POINT) {
            return -70f;
        }
        if (beat == BEAT_OFFER) {
            return -40f;
        }
        if (beat == BEAT_CELEBRATE) {
            return -150f;
        }
        if (beat == BEAT_SHOOT || beat == BEAT_CLIMB || beat == BEAT_SWING || beat == BEAT_RETURN) {
            return -160f;
        }
        return -20f;
    }

    private float webLength() {
        switch (beat) {
            case BEAT_PEEK:
                return 0.35f * unit(elapsed(), 300);
            case BEAT_CLIMB:
                return 0.35f + 0.4f * unit(elapsed(), 320);
            case BEAT_SHOOT:
                return unit(elapsed(), 420);
            case BEAT_RETURN:
                return 1f;
            case BEAT_IDLE:
                return 0f;
            default:
                return 1f;
        }
    }

    private void drawHero(Canvas canvas, int face, boolean bottle, boolean pointing, boolean celebrate) {
        float d = density;
        fill.setStyle(Paint.Style.FILL);
        stroke.setStrokeWidth(1.35f * d);
        stroke.setColor(0xFF1A1F33);

        // shadow
        fill.setColor(0x33000000);
        canvas.drawOval(-22f * d, 46f * d, 22f * d, 54f * d, fill);

        // legs
        drawLimb(canvas, -9f * d, 18f * d, 9f * d, 44f * d, 0xFF141414, 7.2f * d);
        drawLimb(canvas, 9f * d, 18f * d, celebrate ? 16f * d : -2f * d, 44f * d, 0xFF141414, 7.2f * d);
        fill.setColor(0xFFD32F2F);
        canvas.drawRoundRect(-16f * d, 40f * d, -2f * d, 48f * d, 3f * d, 3f * d, fill);
        canvas.drawRoundRect(2f * d, 40f * d, 16f * d, 48f * d, 3f * d, 3f * d, fill);
        fill.setColor(0xFFF5F5F7);
        canvas.drawRoundRect(-16f * d, 45.5f * d, -2f * d, 48f * d, 2f * d, 2f * d, fill);
        canvas.drawRoundRect(2f * d, 45.5f * d, 16f * d, 48f * d, 2f * d, 2f * d, fill);

        // torso — blue with red sides
        path.reset();
        path.moveTo(-17f * d, -6f * d);
        path.quadTo(-22f * d, 10f * d, -16f * d, 22f * d);
        path.lineTo(16f * d, 22f * d);
        path.quadTo(22f * d, 10f * d, 17f * d, -6f * d);
        path.close();
        fill.setColor(0xFF1E56C8);
        canvas.drawPath(path, fill);
        canvas.drawPath(path, stroke);
        fill.setColor(0xFFC62828);
        path.reset();
        path.moveTo(-17f * d, -6f * d);
        path.lineTo(-9f * d, -4f * d);
        path.lineTo(-11f * d, 22f * d);
        path.lineTo(-16f * d, 22f * d);
        path.close();
        canvas.drawPath(path, fill);
        path.reset();
        path.moveTo(17f * d, -6f * d);
        path.lineTo(9f * d, -4f * d);
        path.lineTo(11f * d, 22f * d);
        path.lineTo(16f * d, 22f * d);
        path.close();
        canvas.drawPath(path, fill);

        drawWebOnTorso(canvas);
        drawDrop(canvas, 0, 6f * d, 6.5f * d);

        // arms
        float la = celebrate ? -150f : (pointing ? 18f : -28f);
        float ra = rightArm();
        canvas.save();
        canvas.translate(-15f * d, -2f * d);
        canvas.rotate(la);
        fill.setColor(0xFFC62828);
        canvas.drawRoundRect(-5f * d, 0, 5f * d, 24f * d, 5f * d, 5f * d, fill);
        canvas.restore();
        canvas.save();
        canvas.translate(15f * d, -2f * d);
        canvas.rotate(ra);
        fill.setColor(0xFFC62828);
        canvas.drawRoundRect(-5f * d, 0, 5f * d, 24f * d, 5f * d, 5f * d, fill);
        if (bottle) {
            drawBottle(canvas, 2f * d, 18f * d);
        } else if (pointing) {
            fill.setColor(0xFFE8B896);
            canvas.drawCircle(0, 26f * d, 4.2f * d, fill);
        }
        canvas.restore();

        // head / hood
        fill.setColor(0xFFC62828);
        oval.set(-20f * d, -48f * d, 20f * d, -10f * d);
        canvas.drawOval(oval, fill);
        canvas.drawOval(oval, stroke);
        fill.setColor(0xFFE8B896);
        oval.set(-13f * d, -36f * d, 13f * d, -12f * d);
        canvas.drawOval(oval, fill);

        // white lenses
        fill.setColor(0xFFF7FCFF);
        canvas.save();
        canvas.rotate(-12f, -8f * d, -30f * d);
        oval.set(-16.5f * d, -35f * d, -1.5f * d, -24f * d);
        canvas.drawOval(oval, fill);
        canvas.restore();
        canvas.save();
        canvas.rotate(12f, 8f * d, -30f * d);
        oval.set(1.5f * d, -35f * d, 16.5f * d, -24f * d);
        canvas.drawOval(oval, fill);
        canvas.restore();
        fill.setColor(0xFF1A120C);
        canvas.drawCircle(-8.2f * d, -29.2f * d, 1.7f * d, fill);
        canvas.drawCircle(8.2f * d, -29.2f * d, 1.7f * d, fill);

        drawHair(canvas);
        drawMouth(canvas, face);
        if (face == 2) {
            stroke.setStrokeWidth(1.6f * d);
            stroke.setColor(0xFF1A120C);
            canvas.drawLine(-12f * d, -38f * d, -2f * d, -35f * d, stroke);
        }
    }

    private void drawHair(Canvas canvas) {
        float d = density;
        fill.setColor(0xFF1A120C);
        canvas.drawCircle(-12f * d, -46f * d, 7.5f * d, fill);
        canvas.drawCircle(-4f * d, -51f * d, 8.2f * d, fill);
        canvas.drawCircle(6f * d, -50f * d, 7.8f * d, fill);
        canvas.drawCircle(13f * d, -44f * d, 7.2f * d, fill);
        canvas.drawCircle(-16f * d, -38f * d, 5.4f * d, fill);
        canvas.drawCircle(16f * d, -37f * d, 5.2f * d, fill);
        canvas.drawCircle(0f * d, -46f * d, 6.5f * d, fill);
    }

    private void drawMouth(Canvas canvas, int face) {
        float d = density;
        stroke.setColor(0xFF7A3E2A);
        stroke.setStrokeWidth(1.5f * d);
        if (face == 1) {
            oval.set(-4f * d, -18f * d, 4f * d, -12f * d);
            stroke.setStyle(Paint.Style.STROKE);
            canvas.drawOval(oval, stroke);
        } else if (face == 2) {
            canvas.drawLine(-5f * d, -15f * d, 5f * d, -16.5f * d, stroke);
        } else if (face == 3) {
            fill.setColor(0xFF7A3E2A);
            oval.set(-7f * d, -20f * d, 7f * d, -11f * d);
            canvas.drawArc(oval, 10, 160, true, fill);
        } else {
            oval.set(-6.5f * d, -19f * d, 6.5f * d, -12f * d);
            canvas.drawArc(oval, 20, 140, false, stroke);
        }
        stroke.setStyle(Paint.Style.STROKE);
    }

    private void drawDrop(Canvas canvas, float x, float y, float r) {
        float d = density;
        path.reset();
        path.moveTo(x, y - r);
        path.quadTo(x + r, y, x, y + r * 0.85f);
        path.quadTo(x - r, y, x, y - r);
        fill.setColor(0xFF4FC3F7);
        canvas.drawPath(path, fill);
        fill.setColor(0x66FFFFFF);
        canvas.drawCircle(x - 1.4f * d, y - 0.8f * d, 1.4f * d, fill);
    }

    private void drawBottle(Canvas canvas, float x, float y) {
        float d = density;
        fill.setColor(0xAA4FC3F7);
        canvas.drawRoundRect(x - 7f * d, y - 16f * d, x + 7f * d, y + 8f * d, 3.5f * d, 3.5f * d, fill);
        fill.setColor(0xFF29B6F6);
        canvas.drawRoundRect(x - 7f * d, y - 2f * d, x + 7f * d, y + 8f * d, 3.5f * d, 3.5f * d, fill);
        fill.setColor(0xFFE3F2FD);
        canvas.drawRoundRect(x - 3.2f * d, y - 20f * d, x + 3.2f * d, y - 14f * d, 1.4f * d, 1.4f * d, fill);
        stroke.setColor(0xFF1565C0);
        stroke.setStrokeWidth(1.1f * d);
        canvas.drawRoundRect(x - 7f * d, y - 16f * d, x + 7f * d, y + 8f * d, 3.5f * d, 3.5f * d, stroke);
    }

    private void drawWebOnTorso(Canvas canvas) {
        float d = density;
        stroke.setColor(0x66211A2C);
        stroke.setStrokeWidth(0.9f * d);
        canvas.drawLine(-8f * d, -2f * d, 8f * d, 16f * d, stroke);
        canvas.drawLine(8f * d, -2f * d, -8f * d, 16f * d, stroke);
        canvas.drawLine(0, -4f * d, 0, 18f * d, stroke);
        canvas.drawLine(-12f * d, 8f * d, 12f * d, 8f * d, stroke);
    }

    private void drawLimb(Canvas canvas, float x0, float y0, float x1, float y1, int color, float width) {
        stroke.setColor(color);
        stroke.setStrokeWidth(width);
        canvas.drawLine(x0, y0, x1, y1, stroke);
    }

    private void drawBubble(Canvas canvas, float x, float y, String line) {
        float d = density;
        textPaint.setTextSize(13.5f * d);
        float tw = textPaint.measureText(line);
        float left = x - tw / 2f - 12f * d;
        float right = x + tw / 2f + 12f * d;
        float top = y - 16f * d;
        float bottom = y + 12f * d;
        fill.setColor(0xFFF6F8FF);
        canvas.drawRoundRect(left, top, right, bottom, 14f * d, 14f * d, fill);
        path.reset();
        path.moveTo(x - 6f * d, bottom - 1f);
        path.lineTo(x, bottom + 8f * d);
        path.lineTo(x + 6f * d, bottom - 1f);
        canvas.drawPath(path, fill);
        canvas.drawText(line, x - tw / 2f, y + 5f * d, textPaint);
    }

    private void drawHint(Canvas canvas, float x, float y) {
        float d = density;
        textPaint.setTextSize(10.5f * d);
        textPaint.setColor(0xCCF5F5F7);
        String line = impatient() ? "Tap him — drink up" : "Tap him when you drink";
        float tw = textPaint.measureText(line);
        canvas.drawText(line, x - tw / 2f, y, textPaint);
        textPaint.setColor(0xFF1A2232);
    }

    private static float lerp(float a, float b, float t) {
        return a + (b - a) * t;
    }
}
