package se.agevik.ollectl;

import java.util.UUID;

/**
 * IRCA / Zoppas BLE towel-rail protocol.
 *
 * Pure byte manipulation, no Android dependencies, so it mirrors the Python
 * reference implementation one-to-one and can be reasoned about on its own.
 *
 * Frame, always exactly 20 bytes written to the CMD characteristic:
 *   [0]     opcode
 *   [1]     sequence id (echoed back in RESULT)
 *   [2..18] payload, right padded with 0xFF
 *   [19]    checksum = XOR of bytes 0..18
 */
public final class Protocol {

    private Protocol() {}

    // ---- GATT -----------------------------------------------------------
    public static final UUID SERVICE =
            UUID.fromString("35ba1523-94f5-9052-4cd4-f102b6580adf");
    public static final UUID CHAR_STATUS =
            UUID.fromString("35ba1524-94f5-9052-4cd4-f102b6580adf");
    public static final UUID CHAR_CMD =
            UUID.fromString("35ba1525-94f5-9052-4cd4-f102b6580adf");
    public static final UUID CHAR_RESULT =
            UUID.fromString("35ba1526-94f5-9052-4cd4-f102b6580adf");
    public static final UUID CHAR_MODEL =
            UUID.fromString("35ba1529-94f5-9052-4cd4-f102b6580adf");
    public static final UUID CHAR_SERIAL =
            UUID.fromString("35ba1530-94f5-9052-4cd4-f102b6580adf");
    public static final UUID CHAR_FIRMWARE =
            UUID.fromString("35ba1531-94f5-9052-4cd4-f102b6580adf");
    public static final UUID CHAR_DEVICE_NAME =
            UUID.fromString("35ba1532-94f5-9052-4cd4-f102b6580adf");
    public static final UUID CCCD =
            UUID.fromString("00002902-0000-1000-8000-00805f9b34fb");

    public static final int FRAME_LEN = 20;
    private static final byte PAD = (byte) 0xFF;

    // ---- opcodes --------------------------------------------------------
    public static final byte SET_MODE          = 0x02;
    public static final byte SET_TEMP_MANUAL   = 0x03;
    public static final byte SET_TEMP_ECO      = 0x04;
    public static final byte SET_TEMP_COMFORT  = 0x05;
    public static final byte SET_TEMP_ANTIFREEZE = 0x06;
    public static final byte SET_PERIOD_BOOST  = 0x07;
    public static final byte REFRESH_STATUS    = 0x08;
    public static final byte SET_ON            = 0x0D;
    public static final byte SET_OFF           = 0x0E;
    public static final byte AUTH_DEVICE       = 0x11;
    public static final byte SET_LOCK          = 0x15;
    // FACTORY_RESET (0x16) is deliberately not exposed.

    // ---- modes (ModoOperativo) -----------------------------------------
    public static final int MODE_OFF        = 0;
    public static final int MODE_BOOST      = 1;
    public static final int MODE_COMFORT    = 2;
    public static final int MODE_ECO        = 3;
    public static final int MODE_ANTIFREEZE = 4;
    public static final int MODE_SCHEDULE   = 5;
    public static final int MODE_MANUAL     = 6;

    public static String modeName(int m) {
        switch (m) {
            case MODE_OFF:        return "Off";
            case MODE_BOOST:      return "Boost";
            case MODE_COMFORT:    return "Comfort";
            case MODE_ECO:        return "Eco";
            case MODE_ANTIFREEZE: return "Antifreeze";
            case MODE_SCHEDULE:   return "Schedule";
            case MODE_MANUAL:     return "Manual";
            default:              return "Unknown(0x" + Integer.toHexString(m) + ")";
        }
    }

    // ---- unit families (mode_settings, STATUS[9]) ----------------------
    public static final int MS_POWER      = 0x55;
    public static final int MS_CELSIUS    = 0xAA;
    public static final int MS_FAHRENHEIT = 0xA5;

    // ---- setpoint sentinels --------------------------------------------
    public static final int SENTINEL_ANTIFREEZE = 0xFD;
    public static final int SENTINEL_STANDBY    = 0xFE;

    // ---- command status --------------------------------------------------
    public static final int STATUS_OK = 4;

    public static String statusName(int s) {
        switch (s) {
            case 1: return "Invalid CRC";
            case 2: return "Invalid data";
            case 3: return "Unable to update";
            case 4: return "OK";
            case 5: return "Device id not supported";
            case 6: return "Device id already registered";
            case 0xFF: return "Operation undefined";
            default: return "Unknown(0x" + Integer.toHexString(s) + ")";
        }
    }

    public static String alarmName(int a) {
        switch (a) {
            case 0: return "OK";
            case 1: return "NTC sensor fault";
            case 2: return "Load fault";
            case 3: return "Date fault";
            case 4: return "EEPROM fault";
            default: return "Unknown(0x" + Integer.toHexString(a) + ")";
        }
    }

    // ---- framing ---------------------------------------------------------
    public static byte checksum(byte[] data, int len) {
        byte c = 0;
        for (int i = 0; i < len; i++) c ^= data[i];
        return c;
    }

    public static byte[] frame(byte opcode, byte seq, byte[] payload) {
        if (payload != null && payload.length > 17) {
            throw new IllegalArgumentException("payload exceeds 17 bytes");
        }
        byte[] f = new byte[FRAME_LEN];
        f[0] = opcode;
        f[1] = seq;
        for (int i = 2; i < 19; i++) f[i] = PAD;
        if (payload != null) System.arraycopy(payload, 0, f, 2, payload.length);
        f[19] = checksum(f, 19);
        return f;
    }

    public static boolean verify(byte[] f) {
        return f != null && f.length == FRAME_LEN && checksum(f, 19) == f[19];
    }

    /** Drop the trailing checksum if this is a full, valid 20-byte frame. */
    public static byte[] stripFrame(byte[] data) {
        if (data != null && data.length == FRAME_LEN && checksum(data, 19) == data[19]) {
            byte[] out = new byte[19];
            System.arraycopy(data, 0, out, 0, 19);
            return out;
        }
        return data;
    }

    // ---- setpoint encoding ----------------------------------------------
    /**
     * Encode a setpoint for the given unit family.
     * Celsius travels as tenths of a degree with a -70 bias; Fahrenheit and
     * POWER levels travel raw.
     */
    public static byte encodeSetpoint(double value, int modeSettings) {
        int b;
        if (modeSettings == MS_CELSIUS) {
            b = (int) Math.round(value * 10.0) - 70;
        } else {
            b = (int) Math.round(value);
        }
        if (b < 0 || b > 255) {
            throw new IllegalArgumentException("setpoint " + value + " does not fit a byte");
        }
        return (byte) b;
    }

    public static double decodeSetpoint(int b, int modeSettings) {
        if (modeSettings == MS_CELSIUS) return (b + 70) / 10.0;
        return b;
    }

    // ---- command builders -----------------------------------------------
    public static byte[] cmdOn(byte seq)            { return frame(SET_ON, seq, null); }
    public static byte[] cmdOff(byte seq)           { return frame(SET_OFF, seq, null); }
    public static byte[] cmdRefresh(byte seq)       { return frame(REFRESH_STATUS, seq, null); }

    public static byte[] cmdSetMode(int mode, byte seq) {
        return frame(SET_MODE, seq, new byte[]{(byte) mode});
    }

    public static byte[] cmdSetpoint(byte opcode, double value, int modeSettings, byte seq) {
        return frame(opcode, seq, new byte[]{encodeSetpoint(value, modeSettings)});
    }

    public static byte[] cmdBoostHours(int hours, byte seq) {
        return frame(SET_PERIOD_BOOST, seq, new byte[]{(byte) hours});
    }

    /** SET_LOCK uses 0x55 to lock and 0xAA to unlock, not 1/0. */
    public static byte[] cmdLock(boolean locked, byte seq) {
        return frame(SET_LOCK, seq, new byte[]{(byte) (locked ? 0x55 : 0xAA)});
    }

    public static byte[] cmdAuth(String deviceId, byte seq) {
        byte[] p = new byte[16];
        java.util.Arrays.fill(p, PAD);
        if (deviceId != null) {
            byte[] raw;
            try {
                raw = deviceId.getBytes("UTF-8");
            } catch (java.io.UnsupportedEncodingException e) {
                raw = deviceId.getBytes();
            }
            System.arraycopy(raw, 0, p, 0, Math.min(16, raw.length));
        }
        return frame(AUTH_DEVICE, seq, p);
    }

    // ---- parsing ---------------------------------------------------------
    /** RESULT: [status][opcode echo][seq echo][payload...] */
    public static final class Result {
        public final int status, action, seq;
        public Result(int status, int action, int seq) {
            this.status = status; this.action = action; this.seq = seq;
        }
        public boolean ok() { return status == STATUS_OK; }
    }

    public static Result parseResult(byte[] raw) {
        byte[] d = stripFrame(raw);
        int st = d.length > 0 ? (d[0] & 0xFF) : -1;
        int ac = d.length > 1 ? (d[1] & 0xFF) : -1;
        int sq = d.length > 2 ? (d[2] & 0xFF) : -1;
        return new Result(st, ac, sq);
    }

    /** STATUS, as decoded by DeviceStatus.fromBytesArray. All fields guarded. */
    public static final class Status {
        public int setpointRaw = -1;
        public String setpointSentinel;
        public double setpoint = Double.NaN;
        public int cip = -1;
        public int mode = -1;
        public double eco = Double.NaN, comfort = Double.NaN, antifreeze = Double.NaN;
        public int boostHours = -1;
        public int alarm = -1;
        public int modeSettings = -1;
        public boolean holiday, lock;
        public int windowDetection = -1;
        public byte[] raw;

        public boolean isPowerLevel() { return modeSettings == MS_POWER; }

        public String unit() {
            if (modeSettings == MS_CELSIUS) return "°C";
            if (modeSettings == MS_FAHRENHEIT) return "°F";
            if (modeSettings == MS_POWER) return "";
            return "?";
        }

        /** Render a setpoint the way this unit family means it. */
        public String fmt(double v) {
            if (Double.isNaN(v)) return "-";
            if (isPowerLevel()) return "level " + (int) v;
            return String.format(java.util.Locale.US, "%.1f%s", v, unit());
        }

        public String setpointText() {
            if (setpointSentinel != null) return setpointSentinel;
            return fmt(setpoint);
        }
    }

    public static Status parseStatus(byte[] rawIn) {
        byte[] d = stripFrame(rawIn);
        Status s = new Status();
        s.raw = rawIn;
        int n = d.length;

        s.modeSettings = n > 9 ? (d[9] & 0xFF) : -1;

        if (n > 0) {
            int b = d[0] & 0xFF;
            s.setpointRaw = b;
            if (b == SENTINEL_ANTIFREEZE)      s.setpointSentinel = "Antifreeze";
            else if (b == SENTINEL_STANDBY)    s.setpointSentinel = "Standby";
            else                               s.setpoint = decodeSetpoint(b, s.modeSettings);
        }
        if (n > 2) s.cip = ((d[1] & 0xFF) << 8) | (d[2] & 0xFF);   // big-endian
        if (n > 3) s.mode = d[3] & 0xFF;
        if (n > 4) s.eco = decodeSetpoint(d[4] & 0xFF, s.modeSettings);
        if (n > 5) s.comfort = decodeSetpoint(d[5] & 0xFF, s.modeSettings);
        if (n > 6) s.antifreeze = decodeSetpoint(d[6] & 0xFF, s.modeSettings);
        if (n > 7) s.boostHours = d[7] & 0xFF;
        if (n > 8) s.alarm = d[8] & 0xFF;
        if (n > 10) s.holiday = (d[10] & 0xFF) != 0;
        if (n > 13) s.lock = (d[13] & 0xFF) > 0;
        if (n > 14) s.windowDetection = d[14] & 0xFF;
        return s;
    }

    /** Identity characteristics are frames too: strip checksum and 0xFF padding. */
    public static String textValue(byte[] raw) {
        byte[] d = stripFrame(raw);
        int end = d.length;
        while (end > 0 && (d[end - 1] & 0xFF) == 0xFF) end--;
        return new String(d, 0, end).trim();
    }

    /** FIRMWARE_VERSION is binary [major, minor, patch], not ASCII. */
    public static String versionValue(byte[] raw) {
        byte[] d = stripFrame(raw);
        int end = d.length;
        while (end > 0 && (d[end - 1] & 0xFF) == 0xFF) end--;
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < end; i++) {
            if (i > 0) sb.append('.');
            sb.append(d[i] & 0xFF);
        }
        return sb.toString();
    }

    public static String hex(byte[] b) {
        if (b == null) return "null";
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < b.length; i++) {
            if (i > 0) sb.append(' ');
            sb.append(String.format("%02x", b[i] & 0xFF));
        }
        return sb.toString();
    }
}
