package se.agevik.ollectl;

import android.content.Context;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.graphics.drawable.Drawable;
import android.content.res.ColorStateList;

/** Colours, spacing and the handful of drawables the UI needs. */
public final class Theme {

    private Theme() {}

    // Deep, slightly warm dark ground so the heat accent reads as the only
    // saturated thing on screen.
    public static final int BG            = 0xFF0B0D10;
    public static final int SURFACE       = 0xFF15181E;
    public static final int SURFACE_HIGH  = 0xFF1D222A;
    public static final int STROKE        = 0xFF262C36;

    public static final int TEXT          = 0xFFF4F6F9;
    public static final int TEXT_DIM      = 0xFF8D99AC;
    public static final int TEXT_FAINT    = 0xFF5A6474;

    // Heat ramp, used for the active dial and the power button.
    public static final int HEAT_LO       = 0xFFFFC14D;
    public static final int HEAT_HI       = 0xFFFF5E3A;
    public static final int HEAT_SOFT     = 0x33FF7A45;

    public static final int IDLE          = 0xFF39414D;
    public static final int OK            = 0xFF4ADE80;
    public static final int WARN          = 0xFFFFB020;
    public static final int DANGER        = 0xFFFF5A5F;

    public static int dp(Context c, float v) {
        return Math.round(v * c.getResources().getDisplayMetrics().density);
    }

    public static int sp(Context c, float v) {
        return Math.round(v * c.getResources().getDisplayMetrics().scaledDensity);
    }

    /** Rounded filled rect, optionally outlined. */
    public static GradientDrawable round(int fill, int radiusPx, int strokePx, int strokeColor) {
        GradientDrawable g = new GradientDrawable();
        g.setShape(GradientDrawable.RECTANGLE);
        g.setColor(fill);
        g.setCornerRadius(radiusPx);
        if (strokePx > 0) g.setStroke(strokePx, strokeColor);
        return g;
    }

    public static GradientDrawable circle(int fill) {
        GradientDrawable g = new GradientDrawable();
        g.setShape(GradientDrawable.OVAL);
        g.setColor(fill);
        return g;
    }

    /** Wrap a drawable so taps get a visible ripple. */
    public static Drawable ripple(Drawable content, int rippleColor) {
        return new RippleDrawable(
                ColorStateList.valueOf(rippleColor), content, null);
    }

    /** Blend two colours; t = 0 gives a, t = 1 gives b. */
    public static int mix(int a, int b, float t) {
        t = Math.max(0f, Math.min(1f, t));
        return Color.argb(
                (int) (Color.alpha(a) + (Color.alpha(b) - Color.alpha(a)) * t),
                (int) (Color.red(a)   + (Color.red(b)   - Color.red(a))   * t),
                (int) (Color.green(a) + (Color.green(b) - Color.green(a)) * t),
                (int) (Color.blue(a)  + (Color.blue(b)  - Color.blue(a))  * t));
    }

    public static int alpha(int color, float a) {
        return (color & 0x00FFFFFF) | (((int) (255 * a)) << 24);
    }
}
