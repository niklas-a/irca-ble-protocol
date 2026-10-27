package se.agevik.ollectl;

import android.annotation.SuppressLint;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothGatt;
import android.bluetooth.BluetoothGattCallback;
import android.bluetooth.BluetoothGattCharacteristic;
import android.bluetooth.BluetoothGattDescriptor;
import android.bluetooth.BluetoothGattService;
import android.bluetooth.BluetoothProfile;
import android.content.Context;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;

import java.util.ArrayDeque;
import java.util.UUID;

/**
 * Minimal GATT client for the IRCA/Zoppas service.
 *
 * Android drops GATT operations that overlap, so everything goes through a
 * single-slot queue: one operation in flight, next one starts from the
 * completion callback. The vendor app does the same thing with a semaphore.
 */
@SuppressLint("MissingPermission")
public class OlleGatt {

    private static final String TAG = "OlleGatt";

    public interface Listener {
        void onState(String text, boolean connected);
        void onStatus(Protocol.Status status, byte[] raw);
        void onResult(Protocol.Result result, byte[] raw);
        void onIdentity(String model, String serial, String firmware, String name);
        void onLog(String line);
    }

    private final Context ctx;
    private final Listener listener;
    private final Handler main = new Handler(Looper.getMainLooper());

    private BluetoothGatt gatt;
    private BluetoothGattCharacteristic cmdChar;
    private boolean ready;
    private byte seq = 0;

    private String model = "-", serial = "-", firmware = "-", devName = "-";

    // ---- operation queue -------------------------------------------------
    private abstract static class Op { abstract boolean run(); }
    private final ArrayDeque<Op> queue = new ArrayDeque<>();
    private boolean busy;

    public OlleGatt(Context ctx, Listener listener) {
        this.ctx = ctx;
        this.listener = listener;
    }

    public boolean isReady() { return ready; }

    private void enqueue(Op op) {
        synchronized (queue) {
            queue.add(op);
            if (!busy) next();
        }
    }

    private void next() {
        synchronized (queue) {
            if (busy) return;
            Op op = queue.poll();
            if (op == null) return;
            busy = true;
            if (!op.run()) {          // failed to even start: skip it
                busy = false;
                next();
            }
        }
    }

    private void opDone() {
        synchronized (queue) {
            busy = false;
        }
        next();
    }

    private byte nextSeq() { seq = (byte) ((seq + 1) & 0xFF); return seq; }

    private void log(final String s) {
        Log.d(TAG, s);
        main.post(new Runnable() { public void run() { listener.onLog(s); } });
    }

    private void state(final String s, final boolean c) {
        main.post(new Runnable() { public void run() { listener.onState(s, c); } });
    }

    // ---- lifecycle -------------------------------------------------------
    public void connect(BluetoothDevice device) {
        connect(device, false);
    }

    /**
     * @param autoConnect hand the retry to the Bluetooth stack instead of
     *     attempting a single direct connection. Direct connects fail quickly
     *     if the peripheral is not advertising right now, which is exactly the
     *     case just after this heater drops an idle link - so reconnects use
     *     autoConnect and simply wait for it to show up again.
     */
    public void connect(BluetoothDevice device, boolean autoConnect) {
        close();
        state(autoConnect ? "Reconnecting…"
                          : "Connecting to " + device.getAddress() + " …", false);
        gatt = device.connectGatt(ctx, autoConnect, callback, BluetoothDevice.TRANSPORT_LE);
    }

    public void close() {
        ready = false;
        synchronized (queue) { queue.clear(); busy = false; }
        if (gatt != null) {
            try { gatt.disconnect(); } catch (Exception ignored) {}
            try { gatt.close(); } catch (Exception ignored) {}
            gatt = null;
        }
        cmdChar = null;
    }

    // ---- commands --------------------------------------------------------
    public void send(final byte[] frame, final String label) {
        if (!ready || cmdChar == null) { log("not connected; " + label + " dropped"); return; }
        if (!Protocol.verify(frame)) { log("checksum self-check failed; refusing " + label); return; }
        log("-> " + label + "  " + Protocol.hex(frame));
        enqueue(new Op() {
            boolean run() { return writeChar(cmdChar, frame); }
        });
    }

    public void refresh()                { send(Protocol.cmdRefresh(nextSeq()), "REFRESH_STATUS"); }
    public void on()                     { send(Protocol.cmdOn(nextSeq()), "SET_ON"); }
    public void off()                    { send(Protocol.cmdOff(nextSeq()), "SET_OFF"); }
    public void setMode(int m)           { send(Protocol.cmdSetMode(m, nextSeq()), "SET_MODE " + Protocol.modeName(m)); }
    public void setLock(boolean locked)  { send(Protocol.cmdLock(locked, nextSeq()), "SET_LOCK " + (locked ? "on" : "off")); }
    public void setBoostHours(int h)     { send(Protocol.cmdBoostHours(h, nextSeq()), "SET_PERIOD_BOOST " + h + "h"); }

    public void setpoint(byte opcode, double value, int modeSettings, String label) {
        send(Protocol.cmdSetpoint(opcode, value, modeSettings, nextSeq()), label);
    }

    public void auth(String deviceId) {
        send(Protocol.cmdAuth(deviceId, nextSeq()), "AUTH_DEVICE");
    }

    // ---- version-tolerant GATT primitives --------------------------------
    private boolean writeChar(BluetoothGattCharacteristic c, byte[] value) {
        if (gatt == null) return false;
        if (Build.VERSION.SDK_INT >= 33) {
            return gatt.writeCharacteristic(c, value,
                    BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT) == BluetoothGatt.GATT_SUCCESS;
        } else {
            c.setValue(value);
            c.setWriteType(BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT);
            return gatt.writeCharacteristic(c);
        }
    }

    private boolean writeDesc(BluetoothGattDescriptor d, byte[] value) {
        if (gatt == null) return false;
        if (Build.VERSION.SDK_INT >= 33) {
            return gatt.writeDescriptor(d, value) == BluetoothGatt.GATT_SUCCESS;
        } else {
            d.setValue(value);
            return gatt.writeDescriptor(d);
        }
    }

    private void queueEnableNotify(final BluetoothGattCharacteristic c) {
        if (c == null) return;
        enqueue(new Op() {
            boolean run() {
                if (gatt == null) return false;
                gatt.setCharacteristicNotification(c, true);
                BluetoothGattDescriptor d = c.getDescriptor(Protocol.CCCD);
                if (d == null) return false;
                return writeDesc(d, BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE);
            }
        });
    }

    private void queueRead(final BluetoothGattCharacteristic c) {
        if (c == null) return;
        enqueue(new Op() {
            boolean run() { return gatt != null && gatt.readCharacteristic(c); }
        });
    }

    // ---- callback --------------------------------------------------------
    private final BluetoothGattCallback callback = new BluetoothGattCallback() {

        @Override
        public void onConnectionStateChange(BluetoothGatt g, int status, int newState) {
            if (newState == BluetoothProfile.STATE_CONNECTED) {
                state("Connected, discovering services …", false);
                main.post(new Runnable() { public void run() { if (gatt != null) gatt.discoverServices(); } });
            } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                ready = false;
                synchronized (queue) { queue.clear(); busy = false; }
                state(status == BluetoothGatt.GATT_SUCCESS
                        ? "Disconnected" : "Disconnected (status " + status + ")", false);
            }
        }

        @Override
        public void onServicesDiscovered(BluetoothGatt g, int status) {
            BluetoothGattService svc = g.getService(Protocol.SERVICE);
            if (svc == null) {
                state("Zoppas service not found on this device", false);
                return;
            }
            cmdChar = svc.getCharacteristic(Protocol.CHAR_CMD);

            // Only STATUS and RESULT are genuinely notifiable; the identity
            // characteristics are read-only even though the vendor app tries
            // to subscribe to them.
            queueEnableNotify(svc.getCharacteristic(Protocol.CHAR_STATUS));
            queueEnableNotify(svc.getCharacteristic(Protocol.CHAR_RESULT));

            queueRead(svc.getCharacteristic(Protocol.CHAR_MODEL));
            queueRead(svc.getCharacteristic(Protocol.CHAR_SERIAL));
            queueRead(svc.getCharacteristic(Protocol.CHAR_FIRMWARE));
            queueRead(svc.getCharacteristic(Protocol.CHAR_DEVICE_NAME));
            queueRead(svc.getCharacteristic(Protocol.CHAR_STATUS));

            enqueue(new Op() {
                boolean run() {
                    ready = true;
                    state("Connected", true);
                    main.post(new Runnable() { public void run() { refresh(); } });
                    main.post(new Runnable() { public void run() { opDone(); } });
                    return true;
                }
            });
        }

        @Override public void onDescriptorWrite(BluetoothGatt g, BluetoothGattDescriptor d, int s) { opDone(); }
        @Override public void onCharacteristicWrite(BluetoothGatt g, BluetoothGattCharacteristic c, int s) {
            if (s != BluetoothGatt.GATT_SUCCESS) log("write failed, status " + s);
            opDone();
        }

        // API 33+ delivers the value directly; older versions use getValue().
        @Override
        public void onCharacteristicChanged(BluetoothGatt g, BluetoothGattCharacteristic c, byte[] value) {
            dispatchNotify(c.getUuid(), value);
        }

        @Override
        @SuppressWarnings("deprecation")
        public void onCharacteristicChanged(BluetoothGatt g, BluetoothGattCharacteristic c) {
            if (Build.VERSION.SDK_INT < 33) dispatchNotify(c.getUuid(), c.getValue());
        }

        @Override
        public void onCharacteristicRead(BluetoothGatt g, BluetoothGattCharacteristic c, byte[] value, int s) {
            if (s == BluetoothGatt.GATT_SUCCESS) dispatchRead(c.getUuid(), value);
            opDone();
        }

        @Override
        @SuppressWarnings("deprecation")
        public void onCharacteristicRead(BluetoothGatt g, BluetoothGattCharacteristic c, int s) {
            if (Build.VERSION.SDK_INT < 33) {
                if (s == BluetoothGatt.GATT_SUCCESS) dispatchRead(c.getUuid(), c.getValue());
                opDone();
            }
        }
    };

    private void dispatchRead(UUID uuid, byte[] value) {
        if (value == null) return;
        if (Protocol.CHAR_MODEL.equals(uuid))          model = Protocol.textValue(value);
        else if (Protocol.CHAR_SERIAL.equals(uuid))    serial = Protocol.textValue(value);
        else if (Protocol.CHAR_FIRMWARE.equals(uuid))  firmware = Protocol.versionValue(value);
        else if (Protocol.CHAR_DEVICE_NAME.equals(uuid)) devName = Protocol.textValue(value);
        else if (Protocol.CHAR_STATUS.equals(uuid))    { dispatchNotify(uuid, value); return; }
        else return;
        main.post(new Runnable() {
            public void run() { listener.onIdentity(model, serial, firmware, devName); }
        });
    }

    private void dispatchNotify(UUID uuid, final byte[] value) {
        if (value == null) return;
        if (Protocol.CHAR_STATUS.equals(uuid)) {
            final Protocol.Status st = Protocol.parseStatus(value);
            log("<STATUS> " + Protocol.hex(value));
            main.post(new Runnable() { public void run() { listener.onStatus(st, value); } });
        } else if (Protocol.CHAR_RESULT.equals(uuid)) {
            final Protocol.Result r = Protocol.parseResult(value);
            log("<RESULT> " + Protocol.statusName(r.status) + "  " + Protocol.hex(value));
            main.post(new Runnable() { public void run() { listener.onResult(r, value); } });
        }
    }
}
