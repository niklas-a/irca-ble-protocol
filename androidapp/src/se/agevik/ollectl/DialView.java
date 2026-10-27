package se.agevik.ollectl;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.RectF;
import android.graphics.SweepGradient;
import android.graphics.Matrix;
import android.graphics.Typeface;
import android.view.MotionEvent;
import android.view.View;

/**
 * Circular setpoint dial: a 260 degree arc you can drag, with the current
 * value in the middle.
 *
 * Deliberately value-agnostic - it works in integer "steps" and lets the host
 * decide what a step means, because this device family uses °C, °F or an
 * abstract 1-10 power level depending on the unit.
 */
public class DialView extends View {

    public interface OnChange {
        void onPreview(int step);   // dragging
        void onCommit(int step);    // finger lifted
    }

    private static final float START_ANGLE = 140f;
    private static final float SWEEP       = 260f;

    private final Paint track = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint progress = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint glow = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint thumb = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint bigText = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint midText = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint smallText = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final RectF arcRect = new RectF();

    private int maxStep = 9;
    private int step = 0;
    private boolean active = true;
    private boolean enabledControl = true;
    private String valueText = "—";
    private String captionText = "";
    private String footerText = "";
    private OnChange listener;
    private boolean dragging;

    public DialView(Context c) {
        super(c);
        float strokeW = Theme.dp(c, 16);

        track.setStyle(Paint.Style.STROKE);
        track.setStrokeWidth(strokeW);
        track.setStrokeCap(Paint.Cap.ROUND);
        track.setColor(Theme.STROKE);

        progress.setStyle(Paint.Style.STROKE);
        progress.setStrokeWidth(strokeW);
        progress.setStrokeCap(Paint.Cap.ROUND);

        glow.setStyle(Paint.Style.STROKE);
        glow.setStrokeWidth(strokeW * 2.2f);
        glow.setStrokeCap(Paint.Cap.ROUND);

        thumb.setStyle(Paint.Style.FILL);

        bigText.setColor(Theme.TEXT);
        bigText.setTextAlign(Paint.Align.CENTER);
        bigText.setTypeface(Typeface.create("sans-serif-light", Typeface.NORMAL));

        midText.setColor(Theme.TEXT_DIM);
        midText.setTextAlign(Paint.Align.CENTER);
        midText.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));

        smallText.setColor(Theme.TEXT_FAINT);
        smallText.setTextAlign(Paint.Align.CENTER);
    }

    public void setListener(OnChange l) { listener = l; }

    public void setRange(int maxStepInclusive) {
        maxStep = Math.max(1, maxStepInclusive);
        if (step > maxStep) step = maxStep;
        invalidate();
    }

    public void setStep(int s) {
        step = Math.max(0, Math.min(maxStep, s));
        invalidate();
    }

    public int getStep() { return step; }

    /** active = heater is running (warm colours); false = idle grey. */
    public void setActive(boolean a) { active = a; invalidate(); }

    public void setControlEnabled(boolean e) { enabledControl = e; invalidate(); }

    public void setTexts(String value, String caption, String footer) {
        valueText = value;
        captionText = caption == null ? "" : caption;
        footerText = footer == null ? "" : footer;
        invalidate();
    }

    @Override
    protected void onMeasure(int wSpec, int hSpec) {
        int w = MeasureSpec.getSize(wSpec);
        int size = Math.min(w, Theme.dp(getContext(), 276));
        setMeasuredDimension(w, size);
    }

    @Override
    protected void onDraw(Canvas canvas) {
        int w = getWidth(), h = getHeight();
        float pad = Theme.dp(getContext(), 26);
        float d = Math.min(w, h) - pad * 2;
        float cx = w / 2f, cy = h / 2f;
        arcRect.set(cx - d / 2, cy - d / 2, cx + d / 2, cy + d / 2);

        canvas.drawArc(arcRect, START_ANGLE, SWEEP, false, track);

        float frac = maxStep == 0 ? 0 : (float) step / maxStep;
        float sweep = Math.max(frac * SWEEP, 0.01f);

        int lo = active ? Theme.HEAT_LO : Theme.IDLE;
        int hi = active ? Theme.HEAT_HI : Theme.IDLE;

        // Sweep gradient rotated so the ramp starts where the arc starts.
        SweepGradient sg = new SweepGradient(cx, cy,
                new int[]{lo, hi, hi}, new float[]{0f, SWEEP / 360f, 1f});
        Matrix m = new Matrix();
        m.setRotate(START_ANGLE, cx, cy);
        sg.setLocalMatrix(m);
        progress.setShader(sg);

        if (active) {
            glow.setShader(sg);
            glow.setAlpha(46);
            canvas.drawArc(arcRect, START_ANGLE, sweep, false, glow);
            glow.setAlpha(255);
        }
        canvas.drawArc(arcRect, START_ANGLE, sweep, false, progress);

        // thumb
        double a = Math.toRadians(START_ANGLE + sweep);
        float tx = cx + (float) Math.cos(a) * d / 2;
        float ty = cy + (float) Math.sin(a) * d / 2;
        thumb.setColor(active ? Theme.HEAT_HI : Theme.IDLE);
        if (enabledControl) {
            thumb.setAlpha(60);
            canvas.drawCircle(tx, ty, Theme.dp(getContext(), 16), thumb);
            thumb.setAlpha(255);
            canvas.drawCircle(tx, ty, Theme.dp(getContext(), 9), thumb);
            thumb.setColor(0xFFFFFFFF);
            canvas.drawCircle(tx, ty, Theme.dp(getContext(), 3.5f), thumb);
        }

        // Centre text block. The three baselines are spaced off the centre
        // rather than stacked, so the big value never collides with the
        // caption above it at any font scale.
        midText.setTextSize(Theme.sp(getContext(), 12));
        midText.setLetterSpacing(0.14f);
        midText.setColor(active ? Theme.HEAT_LO : Theme.TEXT_FAINT);
        canvas.drawText(captionText.toUpperCase(), cx,
                cy - Theme.dp(getContext(), 46), midText);

        bigText.setTextSize(Theme.sp(getContext(), 46));
        bigText.setColor(active ? Theme.TEXT : Theme.TEXT_DIM);
        canvas.drawText(valueText, cx, cy + Theme.dp(getContext(), 14), bigText);

        smallText.setTextSize(Theme.sp(getContext(), 11));
        canvas.drawText(footerText, cx, cy + Theme.dp(getContext(), 48), smallText);
    }

    @Override
    public boolean onTouchEvent(MotionEvent e) {
        if (!enabledControl) return false;
        switch (e.getAction()) {
            case MotionEvent.ACTION_DOWN:
            case MotionEvent.ACTION_MOVE: {
                if (e.getAction() == MotionEvent.ACTION_DOWN) {
                    // Ignore touches near the middle so the dial does not jump
                    // when someone taps the value rather than the ring.
                    float cx = getWidth() / 2f, cy = getHeight() / 2f;
                    float r = (float) Math.hypot(e.getX() - cx, e.getY() - cy);
                    float inner = Math.min(getWidth(), getHeight()) * 0.28f;
                    if (r < inner) return false;
                    dragging = true;
                    getParent().requestDisallowInterceptTouchEvent(true);
                }
                if (!dragging) return false;
                int s = stepForTouch(e.getX(), e.getY());
                if (s != step) {
                    step = s;
                    invalidate();
                    if (listener != null) listener.onPreview(step);
                }
                return true;
            }
            case MotionEvent.ACTION_UP:
            case MotionEvent.ACTION_CANCEL:
                if (dragging) {
                    dragging = false;
                    getParent().requestDisallowInterceptTouchEvent(false);
                    if (listener != null) listener.onCommit(step);
                }
                return true;
        }
        return super.onTouchEvent(e);
    }

    private int stepForTouch(float x, float y) {
        float cx = getWidth() / 2f, cy = getHeight() / 2f;
        double deg = Math.toDegrees(Math.atan2(y - cy, x - cx));
        if (deg < 0) deg += 360;
        double rel = deg - START_ANGLE;
        if (rel < 0) rel += 360;
        if (rel > SWEEP) {
            // Past the end of the arc: clamp to whichever end is nearer.
            return (rel - SWEEP) < (360 - rel) ? maxStep : 0;
        }
        return (int) Math.round(rel / SWEEP * maxStep);
    }
}
