# Native macOS builds

The build selects Google's `darwin-x86_64` NDK tools on Apple silicon and
Intel Macs. The host toolchain is macOS-native; compiled outputs remain the
same Android ARM and ARM64 artifacts used by the supported Portal targets.

## Install the host requirements

Install Git, GNU Make, `unzip`, Python 3.9 or newer, a working JDK (17
recommended), and the [Android SDK command-line tools for Mac](https://developer.android.com/studio#command-line-tools-only).
Android Studio is optional. Install these pinned Android packages:

- Android SDK Platform 36
- Android Build Tools 37.0.0
- Android NDK 28.2.13676358
- Android platform-tools

Configure the JDK and SDK in the terminal used for builds:

```sh
export JAVA_HOME="$(/usr/libexec/java_home -v 17)"
export PATH="$JAVA_HOME/bin:$PATH"
export ANDROID_SDK_ROOT="$HOME/Library/Android/sdk"

sdkmanager --sdk_root="$ANDROID_SDK_ROOT" \
  "platform-tools" "platforms;android-36" \
  "build-tools;37.0.0" "ndk;28.2.13676358"

export PATH="$ANDROID_SDK_ROOT/platform-tools:$PATH"
```

If Homebrew's OpenJDK is not registered with macOS, set `JAVA_HOME` directly:

```sh
export JAVA_HOME="$(brew --prefix openjdk)/libexec/openjdk.jdk/Contents/Home"
export PATH="$JAVA_HOME/bin:$PATH"
```

## Configuration

Overrides are optional. Set them before running Python or Make when the SDK is
installed elsewhere:

```sh
export SDK="$HOME/Library/Android/sdk"
export NDK="$SDK/ndk/28.2.13676358"
export TOOLCHAIN="$NDK/toolchains/llvm/prebuilt/darwin-x86_64"
export BUILD_TOOLS="$SDK/build-tools/37.0.0"
export ANDROID_JAR="$SDK/platforms/android-36/android.jar"
export D8="$BUILD_TOOLS/d8"
```

- SDK precedence is `SDK`, `ANDROID_SDK_ROOT`, `ANDROID_HOME`, then the first
  existing default (`$HOME/Library/Android/sdk`, `$HOME/Android/Sdk`,
  `$HOME/Android/sdk`, `$HOME/android-sdk`).
- NDK precedence is `NDK`, `ANDROID_NDK_HOME`, `ANDROID_NDK_ROOT`, then the
  pinned SDK-relative NDK.
- `NDK_HOST_TAG` defaults to `darwin-x86_64` on macOS and can be overridden.
- SDK, NDK, toolchain, build-tools and JDK paths may contain spaces. Repository
  paths with spaces are supported; keep an overridden `KEYSTORE` path without
  spaces because the key-generation prerequisite still has that limitation.

## Offline checks and builds

From the repository root, run the offline unit tests:

```sh
python3 -m unittest discover -s tests -q
```

Build the exact-target payloads and helpers without contacting a Portal:

```sh
(
set -e
for target in \
  portal-terry-5051355900018050 portal-aloha-1041515800015050 \
  portal-cipher-4051355900018050 portal-omni-3051355900018050 \
  portal-ripley-2041515800015050; do
  make -C exploit "$target"
done
make -C exploit-sentinel
make -C helper all native-java
make -C exploit PORTAL_TARGET=portal-aloha-1041515800015050 \
  audio-ctl account-ctl component-ctl
make -C presence-helper
make -C shizuku-helper
make -C uid1000-helper all aloha
)
```

The sentinel build creates the Android debug keystore if absent; later APK
builds reuse it. Do not use `make -B` on targets that generate or consume the
signing key: forcing the key-generation recipe can fail when its alias already
exists. A normal build reuses the existing key.

For USB authorization, wireless ADB, exact model checks, and supported firmware
requirements, follow the [README device setup instructions](../README.md).
Native host compatibility does not expand the supported device or firmware
list.
