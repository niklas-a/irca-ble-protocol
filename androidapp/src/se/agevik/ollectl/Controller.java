package se.agevik.ollectl;

import android.annotation.SuppressLint;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothManager;
import android.bluetooth.le.BluetoothLeScanner;
import android.bluetooth.le.ScanCallback;
import android.bluetooth.le.ScanResult;
import android.bluetooth.le.ScanSettings;
import android.content.Context;
import android.content.SharedPreferences;
import android.os.Handler;
import android.os.Looper;

import java.util.ArrayList;
import java.util.List;

/**
 * Single owner of the BLE connection, shared by every screen.
 *
 * The heater accepts one connection at a time, so the main UI and the debug
 * screen must not each hold their own. They observe this instead.
 */
@SuppressLint("MissingPermission")
public final class Controller implements OlleGatt.Listener {

    private static final String PREFS = "ollectl";
    private static final String KEY_ADDR = "last_address";
    private static Controller instance;

    public interface Observer {
        void onConnectionChanged(String text, boolean connected);
        void onStatusChanged(Protocol.Status status);
        void onIdentityChanged(String line);
        void onLogChanged(String fullLog);
        void onCommandResult(Protocol.Result result);
    }

    private final Context app;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final List<Observer> observers = new ArrayList<>();
    private final StringBuilder log = new StringBuilder();

    private OlleGatt gatt;
    private BluetoothAdapter adapter;
    private BluetoothLeScanner scanner;
    private boolean scanning;

    // The heater drops idle links by itself (seen as GATT status 59,
    // "unacceptable connection parameters"), so treat an unexpected
    // disconnect as routine and come back automatically.
    private BluetoothDevice lastDevice;
    private boolean userDisconnected;
    private int reconnectAttempts;
    private static final int MAX_RECONNECT = 4;
    private static final long POLL_MS = 20000;

    private final Runnable poller = new Runnable() {
        public void run() {
            if (gatt.isReady()) {
                gatt.refresh();
                main.postDelayed(this, POLL_MS);
            }
        }
    };

    public Protocol.Status status;
    public String identity = "";
    public String connectionText = "Not connected";
    public boolean connected;
    public String lastAddress;

    public static synchronized Controller get(Context ctx) {
        if (instance == null) instance = new Controller(ctx.getApplicationContext());
        return instance;
    }

    private Controller(Context app) {
        this.app = app;
        BluetoothManager bm = (BluetoothManager) app.getSystemService(Context.BLUETOOTH_SERVICE);
        adapter = bm != null ? bm.getAdapter() : null;
        gatt = new OlleGatt(app, this);
        lastAddress = prefs().getString(KEY_ADDR, null);
    }

    private SharedPreferences prefs() {
        return app.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    // ---- observers -------------------------------------------------------
    public void addObserver(Observer o) {
        if (!observers.contains(o)) observers.add(o);
        // Replay current state so a newly attached screen is never blank.
        o.onConnectionChanged(connectionText, connected);
        if (status != null) o.onStatusChanged(status);
        if (!identity.isEmpty()) o.onIdentityChanged(identity);
        o.onLogChanged(log.toString());
    }

    public void removeObserver(Observer o) { observers.remove(o); }

    public boolean bluetoothOn() { return adapter != null && adapter.isEnabled(); }
    public boolean isReady()     { return gatt.isReady(); }
    public boolean isScanning()  { return scanning; }
    public String  logText()     { return log.toString(); }

    // ---- connection ------------------------------------------------------
    public void scanAndConnect() {
        if (adapter == null || !adapter.isEnabled()) {
            pushConnection("Bluetooth is off", false);
            return;
        }
        if (scanning || gatt.isReady()) return;
        userDisconnected = false;
        reconnectAttempts = 0;

        // Once we know the address, go straight back to it instead of
        // scanning - much faster, and the device is not always advertising.
        if (lastAddress != null) {
            try {
                lastDevice = adapter.getRemoteDevice(lastAddress);
                onLog("connecting directly to " + lastAddress);
                pushConnection("Connecting…", false);
                gatt.connect(lastDevice);
                return;
            } catch (IllegalArgumentException ignored) {
                // stored address is not valid any more; fall through to a scan
            }
        }
        scanner = adapter.getBluetoothLeScanner();
        if (scanner == null) { pushConnection("No BLE scanner", false); return; }

        scanning = true;
        pushConnection("Searching…", false);
        onLog("scanning for \"Olle\" …");
        ScanSettings s = new ScanSettings.Builder()
                .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build();
        scanner.startScan(null, s, scanCallback);

        main.postDelayed(new Runnable() {
            public void run() {
                if (scanning) {
                    stopScan();
                    pushConnection("No heater found", false);
                    onLog("scan timed out after 15s");
                }
            }
        }, 15000);
    }

    private void stopScan() {
        if (scanning && scanner != null) {
            try { scanner.stopScan(scanCallback); } catch (Exception ignored) {}
        }
        scanning = false;
    }

    private final ScanCallback scanCallback = new ScanCallback() {
        @Override public void onScanResult(int type, ScanResult r) {
            BluetoothDevice d = r.getDevice();
            String name = null;
            try { name = d.getName(); } catch (Exception ignored) {}
            if (name == null && r.getScanRecord() != null) name = r.getScanRecord().getDeviceName();
            boolean match = (name != null && name.toLowerCase().startsWith("olle"))
                    || (lastAddress != null && lastAddress.equals(d.getAddress()));
            if (!match) return;
            stopScan();
            onLog("found " + name + " @ " + d.getAddress() + "  rssi " + r.getRssi());
            lastAddress = d.getAddress();
            lastDevice = d;
            prefs().edit().putString(KEY_ADDR, lastAddress).apply();
            gatt.connect(d);
        }
        @Override public void onScanFailed(int code) {
            scanning = false;
            pushConnection("Scan failed (" + code + ")", false);
        }
    };

    public void disconnect() {
        userDisconnected = true;
        main.removeCallbacks(poller);
        stopScan();
        gatt.close();
        status = null;
        pushConnection("Not connected", false);
        for (Observer o : new ArrayList<>(observers)) o.onStatusChanged(null);
    }

    // ---- commands --------------------------------------------------------
    public void refresh()              { gatt.refresh(); }
    public void on()                   { gatt.on(); scheduleRefresh(); }
    public void off()                  { gatt.off(); scheduleRefresh(); }
    public void setMode(int m)         { gatt.setMode(m); scheduleRefresh(); }
    public void setLock(boolean b)     { gatt.setLock(b); scheduleRefresh(); }
    public void setBoostHours(int h)   { gatt.setBoostHours(h); scheduleRefresh(); }

    public void setManualSetpoint(double value) {
        int ms = status != null ? status.modeSettings : Protocol.MS_POWER;
        gatt.setpoint(Protocol.SET_TEMP_MANUAL, value, ms, "SET_TEMP_MANUAL " + value);
        scheduleRefresh();
    }

    /**
     * SET_ON resumes the stored mode rather than a neutral "on", so never
     * render an optimistic state - always re-read.
     */
    private void scheduleRefresh() {
        main.postDelayed(new Runnable() {
            public void run() { if (gatt.isReady()) gatt.refresh(); }
        }, 1500);
    }

    // ---- OlleGatt.Listener ------------------------------------------------
    public void onState(String text, boolean isConnected) {
        if (isConnected) {
            reconnectAttempts = 0;
            main.removeCallbacks(poller);
            main.postDelayed(poller, POLL_MS);
            pushConnection(text, true);
            return;
        }

        main.removeCallbacks(poller);
        boolean wasConnected = connected;

        if (!userDisconnected && lastDevice != null && reconnectAttempts < MAX_RECONNECT) {
            reconnectAttempts++;
            long delay = 1500L * reconnectAttempts;        // gentle backoff
            onLog("link dropped (" + text + "); reconnecting in "
                    + delay / 1000 + "s, attempt " + reconnectAttempts
                    + "/" + MAX_RECONNECT);
            pushConnection("Reconnecting…", false);
            main.postDelayed(new Runnable() {
                public void run() {
                    if (!userDisconnected && !gatt.isReady() && lastDevice != null) {
                        gatt.connect(lastDevice);
                    }
                }
            }, delay);
            return;
        }

        if (wasConnected && !userDisconnected) {
            onLog("giving up after " + reconnectAttempts + " reconnect attempts");
        }
        pushConnection(text, false);
    }

    private void pushConnection(String text, boolean isConnected) {
        connectionText = text;
        connected = isConnected;
        for (Observer o : new ArrayList<>(observers)) o.onConnectionChanged(text, isConnected);
    }

    public void onStatus(Protocol.Status s, byte[] raw) {
        status = s;
        for (Observer o : new ArrayList<>(observers)) o.onStatusChanged(s);
    }

    public void onResult(Protocol.Result r, byte[] raw) {
        for (Observer o : new ArrayList<>(observers)) o.onCommandResult(r);
    }

    public void onIdentity(String model, String serial, String firmware, String name) {
        identity = "model " + model + "  ·  serial " + serial
                 + "  ·  fw " + firmware + "  ·  " + name;
        for (Observer o : new ArrayList<>(observers)) o.onIdentityChanged(identity);
    }

    public void onLog(String line) {
        log.append(line).append('\n');
        if (log.length() > 12000) log.delete(0, log.length() - 9000);
        String full = log.toString();
        for (Observer o : new ArrayList<>(observers)) o.onLogChanged(full);
    }
}
