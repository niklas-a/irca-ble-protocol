#!/usr/bin/env bash
# Build, sign and (optionally) install the Olle Control APK without Gradle.
#
#   ./build.sh            build + sign
#   ./build.sh install    build + sign + adb install -r
#
# Pipeline: aapt2 link -> javac -> d8 -> add classes.dex -> zipalign -> apksigner
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SDK="${ANDROID_SDK:-$HERE/../tools/android-sdk}"
BT="$SDK/build-tools/35.0.0"
PLATFORM="$SDK/platforms/android-35/android.jar"
JAVA_HOME="${JAVA_HOME:-/c/Program Files/Microsoft/jdk-21.0.13.21-hotspot}"
JAVAC="$JAVA_HOME/bin/javac"
KEYTOOL="$JAVA_HOME/bin/keytool"

OUT="$HERE/build"
KS="$HERE/debug.keystore"
APK_UNSIGNED="$OUT/app-unsigned.apk"
APK_ALIGNED="$OUT/app-aligned.apk"
APK="$OUT/olle-control.apk"

for f in "$BT/aapt2.exe" "$BT/d8.bat" "$BT/zipalign.exe" "$BT/apksigner.bat" "$PLATFORM" "$JAVAC"; do
  [ -e "$f" ] || { echo "missing: $f" >&2; exit 1; }
done

rm -rf "$OUT"; mkdir -p "$OUT/classes" "$OUT/dex"

echo "== 1/6 aapt2 compile + link =="
# The only resources are the launcher icon (an adaptive vector plus bitmap
# fallbacks). There is no layout XML - the UI is built in code - so nothing
# here needs an R class.
"$BT/aapt2.exe" compile --dir "$(cygpath -m "$HERE/res")" \
  -o "$(cygpath -m "$OUT/res.zip")"
"$BT/aapt2.exe" link \
  --manifest "$HERE/AndroidManifest.xml" \
  -I "$PLATFORM" \
  --min-sdk-version 26 --target-sdk-version 35 \
  -o "$APK_UNSIGNED" \
  "$(cygpath -m "$OUT/res.zip")"

echo "== 2/6 javac =="
# javac/d8 are Windows binaries: argfiles must hold Windows paths, and they
# treat backslash as an escape, so use cygpath -m (C:/style/forward/slashes).
find "$HERE/src" -name '*.java' -exec cygpath -m {} \; > "$OUT/sources.txt"
"$JAVAC" -nowarn -source 11 -target 11 \
  -classpath "$(cygpath -m "$PLATFORM")" \
  -d "$(cygpath -m "$OUT/classes")" \
  "@$(cygpath -m "$OUT/sources.txt")" 2>&1 \
  | grep -v -e 'bootstrap class path' -e 'source value 11' -e 'target value 11' -e 'deprecat' || true

echo "== 3/6 d8 =="
export JAVA_HOME="$(cygpath -w "$JAVA_HOME")"
find "$OUT/classes" -name '*.class' -exec cygpath -m {} \; > "$OUT/classes.txt"
"$BT/d8.bat" --lib "$(cygpath -m "$PLATFORM")" \
  --min-api 26 \
  --output "$(cygpath -m "$OUT/dex")" \
  "@$(cygpath -m "$OUT/classes.txt")"

echo "== 4/6 add classes.dex to the apk =="
python - "$APK_UNSIGNED" "$OUT/dex/classes.dex" <<'PY'
import sys, zipfile, shutil, os
apk, dex = sys.argv[1], sys.argv[2]
tmp = apk + ".tmp"
with zipfile.ZipFile(apk) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
    for item in zin.infolist():
        if item.filename != "classes.dex":
            zout.writestr(item, zin.read(item.filename))
    zout.write(dex, "classes.dex")
os.replace(tmp, apk)
print("   classes.dex added (%d bytes)" % os.path.getsize(dex))
PY

echo "== 5/6 zipalign =="
"$BT/zipalign.exe" -f -p 4 "$(cygpath -w "$APK_UNSIGNED")" "$(cygpath -w "$APK_ALIGNED")"

if [ ! -f "$KS" ]; then
  echo "== creating debug keystore =="
  "$KEYTOOL" -genkeypair -v -keystore "$(cygpath -w "$KS")" \
    -storepass android -keypass android -alias ollectl \
    -keyalg RSA -keysize 2048 -validity 10000 \
    -dname "CN=Olle Control Debug, O=local, C=SE" >/dev/null
fi

echo "== 6/6 apksigner =="
"$BT/apksigner.bat" sign \
  --ks "$(cygpath -w "$KS")" --ks-pass pass:android --key-pass pass:android \
  --ks-key-alias ollectl \
  --out "$(cygpath -w "$APK")" "$(cygpath -w "$APK_ALIGNED")"

"$BT/apksigner.bat" verify --print-certs "$(cygpath -w "$APK")" | head -3

echo
echo "BUILT: $APK  ($(stat -c %s "$APK") bytes)"

if [ "${1:-}" = "install" ]; then
  ADB="${ADB:-$HOME/AppData/Local/Microsoft/WinGet/Packages/Google.PlatformTools_Microsoft.Winget.Source_8wekyb3d8bbwe/platform-tools/adb.exe}"
  echo "== installing =="
  "$ADB" install -r "$(cygpath -w "$APK")"
fi
