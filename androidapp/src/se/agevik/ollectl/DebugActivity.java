package se.agevik.ollectl;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.graphics.Typeface;
import android.os.Bundle;
import android.text.method.ScrollingMovementMethod;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup.LayoutParams;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.SeekBar;
import android.widget.TextView;
import android.widget.Toast;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * Raw protocol view: every frame in and out, plus direct command buttons.
 *
 * Shares the one connection owned by Controller, so opening this screen does
 * not fight the main screen for the heater's single GATT slot.
 */
@SuppressLint("MissingPermission")
public class DebugActivity extends Activity implements Controller.Observer {

    private Controller ctl;
    private TextView tvState, tvStatus, tvIdentity, tvLog, tvSeek;
    private SeekBar seek;
    private final List<Button> modeButtons = new ArrayList<>();
    private final List<Button> cmdButtons = new ArrayList<>();

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        ctl = Controller.get(this);
        setContentView(buildUi());
        setTitle("Debug");
        getWindow().setStatusBarColor(Theme.BG);
    }

    @Override protected void onResume() { super.onResume(); ctl.addObserver(this); }
    @Override protected void onPause()  { ctl.removeObserver(this); super.onPause(); }

    private View buildUi() {
        int pad = Theme.dp(this, 16);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Theme.BG);
        root.setPadding(pad, Theme.dp(this, 32), pad, pad);

        TextView h = new TextView(this);
        h.setText("Protocol debug");
        h.setTextSize(20);
        h.setTextColor(Theme.TEXT);
        h.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        root.addView(h);

        tvState = small("Not connected", Theme.TEXT_DIM);
        root.addView(tvState);

        LinearLayout r0 = row();
        r0.addView(btn("Scan & connect", new View.OnClickListener() {
            public void onClick(View v) { ctl.scanAndConnect(); }
        }, false), eq());
        r0.addView(btn("Disconnect", new View.OnClickListener() {
            public void onClick(View v) { ctl.disconnect(); }
        }, false), eq());
        root.addView(r0);

        root.addView(label("RAW STATUS"));
        tvStatus = new TextView(this);
        tvStatus.setTextSize(12);
        tvStatus.setTypeface(Typeface.MONOSPACE);
        tvStatus.setTextColor(Theme.TEXT);
        tvStatus.setBackground(Theme.round(Theme.SURFACE, Theme.dp(this, 10), 0, 0));
        tvStatus.setPadding(pad, pad, pad, pad);
        tvStatus.setText("—");
        root.addView(tvStatus);

        root.addView(label("COMMANDS"));
        LinearLayout r1 = row();
        r1.addView(btn("SET_ON\n0x0D", new View.OnClickListener() {
            public void onClick(View v) { ctl.on(); }
        }, true), eq());
        r1.addView(btn("SET_OFF\n0x0E", new View.OnClickListener() {
            public void onClick(View v) { ctl.off(); }
        }, true), eq());
        r1.addView(btn("REFRESH\n0x08", new View.OnClickListener() {
            public void onClick(View v) { ctl.refresh(); }
        }, true), eq());
        root.addView(r1);

        root.addView(label("SET_MODE  0x02"));
        LinearLayout r2 = row();
        addMode(r2, "Comfort", Protocol.MODE_COMFORT);
        addMode(r2, "Eco", Protocol.MODE_ECO);
        addMode(r2, "Antifr.", Protocol.MODE_ANTIFREEZE);
        root.addView(r2);
        LinearLayout r3 = row();
        addMode(r3, "Boost", Protocol.MODE_BOOST);
        addMode(r3, "Sched.", Protocol.MODE_SCHEDULE);
        addMode(r3, "Manual", Protocol.MODE_MANUAL);
        root.addView(r3);

        root.addView(label("SET_TEMP_MANUAL  0x03"));
        tvSeek = small("—", Theme.TEXT);
        tvSeek.setGravity(Gravity.CENTER);
        root.addView(tvSeek);
        seek = new SeekBar(this);
        seek.setMax(9);
        seek.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            public void onProgressChanged(SeekBar s, int p, boolean u) { updateSeekLabel(); }
            public void onStartTrackingTouch(SeekBar s) {}
            public void onStopTrackingTouch(SeekBar s) {}
        });
        root.addView(seek);
        Button apply = btn("Send setpoint", new View.OnClickListener() {
            public void onClick(View v) { ctl.setManualSetpoint(seekValue()); }
        }, true);
        root.addView(apply);

        root.addView(label("CHILD LOCK  0x15"));
        LinearLayout r4 = row();
        r4.addView(btn("Lock", new View.OnClickListener() {
            public void onClick(View v) { ctl.setLock(true); }
        }, true), eq());
        r4.addView(btn("Unlock", new View.OnClickListener() {
            public void onClick(View v) { ctl.setLock(false); }
        }, true), eq());
        root.addView(r4);

        tvIdentity = small("", Theme.TEXT_FAINT);
        tvIdentity.setPadding(0, Theme.dp(this, 14), 0, 0);
        root.addView(tvIdentity);

        root.addView(label("FRAME LOG"));
        tvLog = new TextView(this);
        tvLog.setTextSize(10);
        tvLog.setTypeface(Typeface.MONOSPACE);
        tvLog.setTextColor(0xFF7F8C9B);
        tvLog.setBackground(Theme.round(Theme.SURFACE, Theme.dp(this, 10), 0, 0));
        tvLog.setPadding(pad, pad, pad, pad);
        tvLog.setMovementMethod(new ScrollingMovementMethod());
        tvLog.setHeight(Theme.dp(this, 220));
        root.addView(tvLog);

        TextView note = small(
                "FACTORY_RESET (0x16) is intentionally not implemented anywhere "
                + "in this app.", Theme.TEXT_FAINT);
        note.setPadding(0, Theme.dp(this, 12), 0, 0);
        root.addView(note);

        ScrollView sv = new ScrollView(this);
        sv.setBackgroundColor(Theme.BG);
        sv.addView(root);
        return sv;
    }

    private void addMode(LinearLayout parent, String name, final int mode) {
        Button b = btn(name, new View.OnClickListener() {
            public void onClick(View v) { ctl.setMode(mode); }
        }, true);
        b.setTag(mode);
        modeButtons.add(b);
        parent.addView(b, eq());
    }

    // ---- setpoint mapping (same families as the main screen) -------------
    private int modeSettings() {
        return ctl.status != null ? ctl.status.modeSettings : Protocol.MS_POWER;
    }

    private double seekValue() {
        switch (modeSettings()) {
            case Protocol.MS_CELSIUS:    return 15.0 + seek.getProgress() * 0.5;
            case Protocol.MS_FAHRENHEIT: return 45 + seek.getProgress();
            default:                     return seek.getProgress() + 1;
        }
    }

    private void updateSeekLabel() {
        double v = seekValue();
        switch (modeSettings()) {
            case Protocol.MS_CELSIUS:
                tvSeek.setText(String.format(Locale.US, "%.1f °C", v)); break;
            case Protocol.MS_FAHRENHEIT:
                tvSeek.setText(String.format(Locale.US, "%.0f °F", v)); break;
            default:
                tvSeek.setText("power level " + (int) v);
        }
    }

    // ---- Controller.Observer ---------------------------------------------
    public void onConnectionChanged(String text, boolean connected) {
        tvState.setText(text);
        tvState.setTextColor(connected ? Theme.OK : Theme.TEXT_DIM);
        for (Button b : cmdButtons) { b.setEnabled(connected); b.setAlpha(connected ? 1f : .4f); }
    }

    public void onStatusChanged(Protocol.Status s) {
        if (s == null) { tvStatus.setText("—"); return; }
        StringBuilder sb = new StringBuilder();
        sb.append(Protocol.hex(s.raw)).append("\n\n");
        sb.append("setpoint   ").append(s.setpointText())
          .append("  (raw 0x").append(String.format("%02X", s.setpointRaw)).append(")\n");
        sb.append("mode       ").append(Protocol.modeName(s.mode))
          .append("  (").append(s.mode).append(")\n");
        sb.append("eco        ").append(s.fmt(s.eco)).append('\n');
        sb.append("comfort    ").append(s.fmt(s.comfort)).append('\n');
        sb.append("antifreeze ").append(s.fmt(s.antifreeze)).append('\n');
        sb.append("boost      ").append(s.boostHours).append(" h\n");
        sb.append("alarm      ").append(Protocol.alarmName(s.alarm)).append('\n');
        sb.append("unit       0x").append(String.format("%02X", s.modeSettings));
        if (s.modeSettings == Protocol.MS_POWER) sb.append("  POWER (levels 1-10)");
        else if (s.modeSettings == Protocol.MS_CELSIUS) sb.append("  CELSIUS");
        else if (s.modeSettings == Protocol.MS_FAHRENHEIT) sb.append("  FAHRENHEIT");
        sb.append('\n');
        sb.append("CIP        ").append(s.cip).append("  (meaning unconfirmed)\n");
        sb.append("lock       ").append(s.lock).append('\n');
        sb.append("holiday    ").append(s.holiday).append('\n');
        sb.append("window     0x").append(String.format("%02X", s.windowDetection));
        tvStatus.setText(sb.toString());

        switch (modeSettings()) {
            case Protocol.MS_CELSIUS:    seek.setMax(30); break;
            case Protocol.MS_FAHRENHEIT: seek.setMax(45); break;
            default:                     seek.setMax(9);
        }
        updateSeekLabel();

        for (Button b : modeButtons) {
            boolean sel = b.getTag() != null && ((Integer) b.getTag()) == s.mode;
            b.setTextColor(sel ? Theme.HEAT_LO : Theme.TEXT);
        }
    }

    public void onIdentityChanged(String line) { tvIdentity.setText(line); }

    public void onLogChanged(String fullLog) {
        tvLog.setText(fullLog);
    }

    public void onCommandResult(Protocol.Result r) {
        Toast.makeText(this,
                "RESULT " + Protocol.statusName(r.status)
                        + "  seq 0x" + String.format("%02X", r.seq),
                Toast.LENGTH_SHORT).show();
    }

    // ---- helpers ----------------------------------------------------------
    private LinearLayout row() {
        LinearLayout l = new LinearLayout(this);
        l.setOrientation(LinearLayout.HORIZONTAL);
        return l;
    }

    private LinearLayout.LayoutParams eq() {
        LinearLayout.LayoutParams p =
                new LinearLayout.LayoutParams(0, LayoutParams.WRAP_CONTENT, 1f);
        p.rightMargin = Theme.dp(this, 6);
        return p;
    }

    private TextView small(String s, int color) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(12);
        t.setTextColor(color);
        return t;
    }

    private TextView label(String s) {
        TextView t = small(s, Theme.TEXT_FAINT);
        t.setTextSize(11);
        t.setLetterSpacing(0.1f);
        t.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        t.setPadding(0, Theme.dp(this, 18), 0, Theme.dp(this, 6));
        return t;
    }

    private Button btn(String text, View.OnClickListener l, boolean needsConnection) {
        Button b = new Button(this);
        b.setText(text);
        b.setAllCaps(false);
        b.setTextSize(12);
        b.setTextColor(Theme.TEXT);
        b.setBackground(Theme.ripple(
                Theme.round(Theme.SURFACE_HIGH, Theme.dp(this, 10),
                        Theme.dp(this, 1), Theme.STROKE), 0x33FFFFFF));
        b.setOnClickListener(l);
        if (needsConnection) cmdButtons.add(b);
        return b;
    }
}
