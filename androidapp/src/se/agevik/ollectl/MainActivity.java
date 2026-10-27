package se.agevik.ollectl;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Typeface;
import android.os.Build;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup.LayoutParams;
import android.widget.HorizontalScrollView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

@SuppressLint("MissingPermission")
public class MainActivity extends Activity implements Controller.Observer {

    private static final int REQ_PERMS = 1;

    private Controller ctl;

    private TextView tvTitle, tvConn, tvIdentity, tvFlags;
    private View connDot;
    private DialView dial;
    private TextView powerBtn;
    private LinearLayout modeRow;
    private LinearLayout connectCard;
    private LinearLayout content;      // everything that needs a connection
    private TextView connectBtn;
    private final List<TextView> modeChips = new ArrayList<>();

    private boolean previewing;      // user is dragging the dial
    private int previewStep;

    // ------------------------------------------------------------------
    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        ctl = Controller.get(this);
        setContentView(buildUi());
        getWindow().setStatusBarColor(Theme.BG);
        getWindow().setNavigationBarColor(Theme.BG);
        requestPermissionsIfNeeded();
    }

    @Override protected void onResume() {
        super.onResume();
        ctl.addObserver(this);
        if (ctl.isReady()) ctl.refresh();
    }

    @Override protected void onPause() {
        ctl.removeObserver(this);
        super.onPause();
    }

    // ------------------------------------------------------------------
    private View buildUi() {
        int pad = Theme.dp(this, 20);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Theme.BG);
        root.setPadding(pad, Theme.dp(this, 52), pad, pad);

        // ---- header ----
        LinearLayout header = new LinearLayout(this);
        header.setOrientation(LinearLayout.HORIZONTAL);
        header.setGravity(Gravity.CENTER_VERTICAL);

        LinearLayout titles = new LinearLayout(this);
        titles.setOrientation(LinearLayout.VERTICAL);
        tvTitle = new TextView(this);
        tvTitle.setText("Towel rail");
        tvTitle.setTextSize(22);
        tvTitle.setTextColor(Theme.TEXT);
        tvTitle.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        titles.addView(tvTitle);

        LinearLayout connRow = new LinearLayout(this);
        connRow.setOrientation(LinearLayout.HORIZONTAL);
        connRow.setGravity(Gravity.CENTER_VERTICAL);
        connDot = new View(this);
        connDot.setBackground(Theme.circle(Theme.IDLE));
        LinearLayout.LayoutParams dotLp =
                new LinearLayout.LayoutParams(Theme.dp(this, 7), Theme.dp(this, 7));
        dotLp.rightMargin = Theme.dp(this, 7);
        connRow.addView(connDot, dotLp);
        tvConn = new TextView(this);
        tvConn.setText("Not connected");
        tvConn.setTextSize(13);
        tvConn.setTextColor(Theme.TEXT_DIM);
        connRow.addView(tvConn);
        titles.addView(connRow);

        header.addView(titles, new LinearLayout.LayoutParams(0, LayoutParams.WRAP_CONTENT, 1f));

        TextView debugBtn = chip("Debug", Theme.SURFACE, Theme.TEXT_DIM);
        debugBtn.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                startActivity(new Intent(MainActivity.this, DebugActivity.class));
            }
        });
        header.addView(debugBtn);
        root.addView(header);

        // ---- connect card (empty state) ----
        connectCard = new LinearLayout(this);
        connectCard.setOrientation(LinearLayout.VERTICAL);
        connectCard.setGravity(Gravity.CENTER_HORIZONTAL);
        connectCard.setBackground(Theme.round(Theme.SURFACE, Theme.dp(this, 20),
                Theme.dp(this, 1), Theme.STROKE));
        connectCard.setPadding(pad, pad, pad, pad);
        TextView hint = new TextView(this);
        hint.setText("Not connected to the heater");
        hint.setTextColor(Theme.TEXT_DIM);
        hint.setTextSize(14);
        hint.setGravity(Gravity.CENTER);
        connectCard.addView(hint);
        connectBtn = chip("Find my heater", Theme.HEAT_HI, 0xFFFFFFFF);
        connectBtn.setTextSize(15);
        connectBtn.setPadding(Theme.dp(this, 26), Theme.dp(this, 12),
                Theme.dp(this, 26), Theme.dp(this, 12));
        connectBtn.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { doConnect(); }
        });
        LinearLayout.LayoutParams cbLp = new LinearLayout.LayoutParams(
                LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT);
        cbLp.topMargin = Theme.dp(this, 14);
        connectCard.addView(connectBtn, cbLp);
        LinearLayout.LayoutParams ccLp = new LinearLayout.LayoutParams(
                LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT);
        ccLp.topMargin = Theme.dp(this, 48);
        root.addView(connectCard, ccLp);

        // Everything below needs a live connection; hidden entirely when
        // offline so the empty state is a single clear call to action rather
        // than a screen of dead controls.
        content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        root.addView(content, new LinearLayout.LayoutParams(
                LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT));

        // ---- dial ----
        dial = new DialView(this);
        dial.setListener(new DialView.OnChange() {
            public void onPreview(int step) {
                previewing = true;
                previewStep = step;
                dial.setTexts(formatForStep(step), "setting…", footerLine());
            }
            public void onCommit(int step) {
                previewing = false;
                ctl.setManualSetpoint(valueForStep(step));
            }
        });
        LinearLayout.LayoutParams dialLp = new LinearLayout.LayoutParams(
                LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT);
        dialLp.topMargin = Theme.dp(this, 10);
        content.addView(dial, dialLp);

        // ---- power button ----
        powerBtn = new TextView(this);
        powerBtn.setText("Turn on");
        powerBtn.setTextSize(16);
        powerBtn.setGravity(Gravity.CENTER);
        powerBtn.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        powerBtn.setPadding(0, Theme.dp(this, 16), 0, Theme.dp(this, 16));
        powerBtn.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) { togglePower(); }
        });
        LinearLayout.LayoutParams pbLp = new LinearLayout.LayoutParams(
                LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT);
        pbLp.topMargin = Theme.dp(this, 6);
        content.addView(powerBtn, pbLp);
        stylePower(false);

        // ---- modes ----
        content.addView(sectionLabel("MODE"));
        HorizontalScrollView hs = new HorizontalScrollView(this);
        hs.setHorizontalScrollBarEnabled(false);
        modeRow = new LinearLayout(this);
        modeRow.setOrientation(LinearLayout.HORIZONTAL);
        addModeChip("Comfort", Protocol.MODE_COMFORT);
        addModeChip("Eco", Protocol.MODE_ECO);
        addModeChip("Antifreeze", Protocol.MODE_ANTIFREEZE);
        addModeChip("Boost", Protocol.MODE_BOOST);
        addModeChip("Schedule", Protocol.MODE_SCHEDULE);
        addModeChip("Manual", Protocol.MODE_MANUAL);
        hs.addView(modeRow);
        content.addView(hs);

        // ---- flags + identity ----
        tvFlags = new TextView(this);
        tvFlags.setTextSize(13);
        tvFlags.setTextColor(Theme.WARN);
        tvFlags.setPadding(0, Theme.dp(this, 14), 0, 0);
        tvFlags.setVisibility(View.GONE);
        content.addView(tvFlags);

        tvIdentity = new TextView(this);
        tvIdentity.setTextSize(11);
        tvIdentity.setTextColor(Theme.TEXT_FAINT);
        tvIdentity.setPadding(0, Theme.dp(this, 22), 0, 0);
        tvIdentity.setSingleLine(true);
        tvIdentity.setEllipsize(android.text.TextUtils.TruncateAt.END);
        content.addView(tvIdentity);

        ScrollView sv = new ScrollView(this);
        sv.setBackgroundColor(Theme.BG);
        sv.addView(root);
        return sv;
    }

    private TextView sectionLabel(String s) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(11);
        t.setLetterSpacing(0.12f);
        t.setTextColor(Theme.TEXT_FAINT);
        t.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        t.setPadding(0, Theme.dp(this, 22), 0, Theme.dp(this, 10));
        return t;
    }

    private TextView chip(String label, int bg, int fg) {
        TextView t = new TextView(this);
        t.setText(label);
        t.setTextSize(13);
        t.setTextColor(fg);
        t.setGravity(Gravity.CENTER);
        t.setPadding(Theme.dp(this, 16), Theme.dp(this, 9),
                Theme.dp(this, 16), Theme.dp(this, 9));
        t.setBackground(Theme.ripple(
                Theme.round(bg, Theme.dp(this, 999), 0, 0), 0x33FFFFFF));
        t.setClickable(true);
        return t;
    }

    private void addModeChip(String label, final int mode) {
        TextView c = chip(label, Theme.SURFACE, Theme.TEXT_DIM);
        c.setTag(mode);
        c.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                if (!ctl.isReady()) { toast("Not connected"); return; }
                ctl.setMode(mode);
            }
        });
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                LayoutParams.WRAP_CONTENT, LayoutParams.WRAP_CONTENT);
        lp.rightMargin = Theme.dp(this, 8);
        modeRow.addView(c, lp);
        modeChips.add(c);
    }

    // ------------------------------------------------------------------
    private void doConnect() {
        if (missingPermissions().length > 0) { requestPermissionsIfNeeded(); return; }
        if (!ctl.bluetoothOn()) { toast("Turn Bluetooth on first"); return; }
        ctl.scanAndConnect();
    }

    private void togglePower() {
        if (!ctl.isReady()) { toast("Not connected"); return; }
        Protocol.Status s = ctl.status;
        boolean on = s != null && s.mode != Protocol.MODE_OFF && s.mode >= 0;
        if (on) ctl.off(); else ctl.on();
    }

    private void stylePower(boolean on) {
        powerBtn.setText(on ? "Turn off" : "Turn on");
        powerBtn.setTextColor(on ? 0xFFFFFFFF : Theme.TEXT);
        powerBtn.setBackground(Theme.ripple(
                Theme.round(on ? Theme.HEAT_HI : Theme.SURFACE_HIGH,
                        Theme.dp(this, 18),
                        on ? 0 : Theme.dp(this, 1), Theme.STROKE),
                0x33FFFFFF));
    }

    // ---- unit-family aware value mapping -------------------------------
    private int modeSettings() {
        return ctl.status != null ? ctl.status.modeSettings : Protocol.MS_POWER;
    }

    private int maxStepForFamily() {
        switch (modeSettings()) {
            case Protocol.MS_CELSIUS:    return 30;   // 15.0 .. 30.0 step 0.5
            case Protocol.MS_FAHRENHEIT: return 45;   // 45 .. 90 step 1
            default:                     return 9;    // level 1 .. 10
        }
    }

    private double valueForStep(int step) {
        switch (modeSettings()) {
            case Protocol.MS_CELSIUS:    return 15.0 + step * 0.5;
            case Protocol.MS_FAHRENHEIT: return 45 + step;
            default:                     return step + 1;
        }
    }

    private int stepForValue(double v) {
        switch (modeSettings()) {
            case Protocol.MS_CELSIUS:    return (int) Math.round((v - 15.0) / 0.5);
            case Protocol.MS_FAHRENHEIT: return (int) Math.round(v - 45);
            default:                     return (int) Math.round(v) - 1;
        }
    }

    private String formatForStep(int step) {
        double v = valueForStep(step);
        switch (modeSettings()) {
            case Protocol.MS_CELSIUS:    return String.format(Locale.US, "%.1f°", v);
            case Protocol.MS_FAHRENHEIT: return String.format(Locale.US, "%.0f°", v);
            default:                     return String.valueOf((int) v);
        }
    }

    private String footerLine() {
        Protocol.Status s = ctl.status;
        if (s == null) return "";
        if (modeSettings() == Protocol.MS_POWER) return "power level · 1 – 10";
        return "comfort " + s.fmt(s.comfort) + "   eco " + s.fmt(s.eco);
    }

    // ---- Controller.Observer --------------------------------------------
    public void onConnectionChanged(String text, boolean connected) {
        tvConn.setText(text);
        connDot.setBackground(Theme.circle(connected ? Theme.OK
                : (ctl.isScanning() ? Theme.WARN : Theme.IDLE)));
        connectCard.setVisibility(connected ? View.GONE : View.VISIBLE);
        content.setVisibility(connected ? View.VISIBLE : View.GONE);
        dial.setControlEnabled(connected);
        connectBtn.setText(ctl.isScanning() ? "Searching…" : "Find my heater");
        connectBtn.setAlpha(ctl.isScanning() ? 0.6f : 1f);
        if (!connected) {
            dial.setTexts("—", "", "");
            dial.setActive(false);
        }
    }

    public void onStatusChanged(Protocol.Status s) {
        if (s == null) {
            dial.setTexts("—", "", "");
            dial.setActive(false);
            stylePower(false);
            highlightMode(-1);
            tvFlags.setVisibility(View.GONE);
            return;
        }
        boolean on = s.mode != Protocol.MODE_OFF && s.mode >= 0;

        dial.setRange(maxStepForFamily());
        dial.setActive(on);
        if (!previewing) {
            if (!Double.isNaN(s.setpoint)) dial.setStep(stepForValue(s.setpoint));
            String value = on
                    ? (s.setpointSentinel != null ? s.setpointSentinel
                                                  : formatForStep(dial.getStep()))
                    : "Off";
            // When off, "Off" already says it - a "STANDBY" caption on top is
            // just noise.
            dial.setTexts(value, on ? Protocol.modeName(s.mode) : "", footerLine());
        }

        stylePower(on);
        highlightMode(s.mode);

        StringBuilder flags = new StringBuilder();
        if (s.alarm > 0) flags.append("⚠ ").append(Protocol.alarmName(s.alarm));
        if (s.lock) { if (flags.length() > 0) flags.append("   "); flags.append("Child lock on"); }
        if (s.holiday) { if (flags.length() > 0) flags.append("   "); flags.append("Holiday mode"); }
        if (flags.length() > 0) {
            tvFlags.setText(flags.toString());
            tvFlags.setTextColor(s.alarm > 0 ? Theme.DANGER : Theme.WARN);
            tvFlags.setVisibility(View.VISIBLE);
        } else {
            tvFlags.setVisibility(View.GONE);
        }
    }

    private void highlightMode(int mode) {
        for (TextView c : modeChips) {
            boolean sel = c.getTag() != null && ((Integer) c.getTag()) == mode;
            c.setTextColor(sel ? 0xFFFFFFFF : Theme.TEXT_DIM);
            c.setBackground(Theme.ripple(
                    Theme.round(sel ? Theme.HEAT_HI : Theme.SURFACE,
                            Theme.dp(this, 999), 0, 0), 0x33FFFFFF));
        }
    }

    public void onIdentityChanged(String line) { tvIdentity.setText(line); }

    public void onLogChanged(String fullLog) { /* main screen stays quiet */ }

    public void onCommandResult(Protocol.Result r) {
        if (!r.ok()) toast("Heater refused: " + Protocol.statusName(r.status));
    }

    // ---- permissions -----------------------------------------------------
    private String[] missingPermissions() {
        List<String> need = new ArrayList<>();
        if (Build.VERSION.SDK_INT >= 31) {
            if (!granted(Manifest.permission.BLUETOOTH_SCAN)) need.add(Manifest.permission.BLUETOOTH_SCAN);
            if (!granted(Manifest.permission.BLUETOOTH_CONNECT)) need.add(Manifest.permission.BLUETOOTH_CONNECT);
        } else if (!granted(Manifest.permission.ACCESS_FINE_LOCATION)) {
            need.add(Manifest.permission.ACCESS_FINE_LOCATION);
        }
        return need.toArray(new String[0]);
    }

    private boolean granted(String p) {
        return checkSelfPermission(p) == PackageManager.PERMISSION_GRANTED;
    }

    private void requestPermissionsIfNeeded() {
        String[] need = missingPermissions();
        if (need.length > 0) requestPermissions(need, REQ_PERMS);
    }

    private void toast(String s) { Toast.makeText(this, s, Toast.LENGTH_SHORT).show(); }
}
