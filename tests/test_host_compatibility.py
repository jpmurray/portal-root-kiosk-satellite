"""Focused offline host compatibility regressions."""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import provision_portal as portal


class HostCompatibilityTest(unittest.TestCase):
    def test_native_host_selection(self):
        for system, machine, expected in (
            ("Darwin", "arm64", "darwin-x86_64"),
            ("Darwin", "x86_64", "darwin-x86_64"),
            ("Linux", "x86_64", "linux-x86_64"),
        ):
            with self.subTest(system=system, machine=machine), \
                    mock.patch.object(portal.platform, "system", return_value=system), \
                    mock.patch.object(portal.platform, "machine", return_value=machine):
                self.assertEqual(portal.ndk_host_tag(), expected)
        with mock.patch.object(portal.platform, "system", return_value="Windows"):
            with self.assertRaisesRegex(portal.ProvisionError, "unsupported build host"):
                portal.ndk_host_tag()

    @staticmethod
    def fake_sdk(root, tag):
        sdk = root / "Android SDK"
        ndk = sdk / "ndk" / portal.ANDROID_NDK_VERSION
        toolchain = ndk / "toolchains/llvm/prebuilt" / tag
        tools = sdk / "build-tools" / portal.ANDROID_BUILD_TOOLS_VERSION
        for name in (
            "aarch64-linux-android29-clang",
            "armv7a-linux-androideabi28-clang",
            "armv7a-linux-androideabi29-clang",
        ):
            path = toolchain / "bin" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        for name in ("aapt", "d8", "apksigner", "zipalign"):
            path = tools / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        jar = sdk / "platforms" / portal.ANDROID_PLATFORM_VERSION / "android.jar"
        jar.parent.mkdir(parents=True)
        jar.touch()
        return sdk, toolchain

    def test_environment_keeps_overrides_spaced_paths_and_java_home(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary).resolve()
            sdk, toolchain = self.fake_sdk(root, "darwin-x86_64")
            custom = root / "custom toolchain"
            toolchain.rename(custom)
            custom_d8 = root / "custom d8"
            custom_d8.touch()
            java_home = root / "custom JDK"
            with mock.patch.dict(os.environ, {
                "SDK": str(sdk),
                "ANDROID_SDK_ROOT": str(root / "unused SDK"),
                "NDK": str(root / "custom NDK"),
                "NDK_HOST_TAG": "darwin-x86_64",
                "TOOLCHAIN": str(custom),
                "JAVA_HOME": str(java_home),
                "PATH": os.defpath,
                "D8": str(custom_d8),
            }, clear=True), mock.patch.object(
                portal, "ndk_host_tag",
                side_effect=AssertionError("explicit host tag must take precedence"),
            ) as host_tag:
                # The explicit host tag is read directly; no host probing is needed.
                with mock.patch.object(shutil, "which", return_value="/usr/bin/tool"):
                    environment = portal.android_build_environment()
            host_tag.assert_not_called()

        self.assertEqual(environment["SDK"], str(sdk))
        self.assertEqual(environment["NDK"], str(root / "custom NDK"))
        self.assertEqual(environment["TOOLCHAIN"], str(custom))
        self.assertEqual(environment["NDK_HOST_TAG"], "darwin-x86_64")
        self.assertEqual(environment["D8"], str(custom_d8))
        self.assertTrue(environment["PATH"].startswith(str(java_home / "bin") + os.pathsep))

    def test_sdk_override_precedence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary).resolve()
            environment = {
                name: str(root / name)
                for name in ("SDK", "ANDROID_SDK_ROOT", "ANDROID_HOME")
            }
            for name in ("SDK", "ANDROID_SDK_ROOT", "ANDROID_HOME"):
                self.assertEqual(portal.android_sdk_directory(environment), root / name)
                del environment[name]

    def test_make_and_python_choose_same_sdk_defaults(self):
        for system, tag in (("Darwin", "darwin-x86_64"), ("Linux", "linux-x86_64")):
            with self.subTest(system=system), tempfile.TemporaryDirectory() as temporary:
                home = pathlib.Path(temporary).resolve()
                (home / "Library/Android/sdk").mkdir(parents=True)
                (home / "Android/Sdk").mkdir(parents=True)
                with mock.patch.object(pathlib.Path, "home", return_value=home), \
                        mock.patch.object(portal.platform, "system", return_value=system):
                    sdk = portal.android_sdk_directory({})
                makefile = ('include android-env.mk\nshow:\n'
                            '\t@printf "%s\\n" "$(SDK)" "$(TOOLCHAIN)"\n')
                result = subprocess.run(
                    ["make", "--no-print-directory", "-s", "-f", "-",
                     f"HOST_OS={system}", "show"],
                    cwd=ROOT,
                    env={"PATH": os.defpath, "HOME": str(home),
                         "TMPDIR": tempfile.gettempdir()},
                    input=makefile,
                    text=True,
                    capture_output=True,
                    check=True,
                )
                self.assertEqual(result.stdout.splitlines(), [
                    str(sdk),
                    str(sdk / "ndk" / portal.ANDROID_NDK_VERSION /
                        "toolchains/llvm/prebuilt" / tag),
                ])

    def _kaslr_with_simpleperf(self, root, environment, system="Linux"):
        provisioner = portal.PortalProvisioner("serial", 1, root)
        provisioner.target = SimpleNamespace(
            bundled_simpleperf=True,
            kaslr_strategy="simpleperf",
            kaslr_pc_offsets=(0x3354,),
        )
        calls = []

        def adb_run(command, **kwargs):
            calls.append(command)
            stdout = ""
            if command[0] == "shell" and "report-sample" in command[1]:
                stdout = "vaddr_in_file: ffffff8008083354"
            return subprocess.CompletedProcess(command, 0, stdout=stdout)

        with mock.patch.dict(os.environ, environment, clear=True), \
                mock.patch.object(portal.platform, "system", return_value=system), \
                mock.patch.object(pathlib.Path, "home", return_value=root), \
                mock.patch.object(provisioner, "adb_run", side_effect=adb_run):
            base = provisioner.kaslr_base("test")
        return base, calls

    def test_simpleperf_preserves_historical_ndk_precedence_and_versions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary).resolve()
            home_ndk = root / "home NDK"
            root_ndk = root / "root NDK"
            plain_ndk = root / "plain NDK"
            first = home_ndk / "2.0" / "simpleperf/bin/android/arm64/simpleperf"
            second = home_ndk / "1.0" / "simpleperf/bin/android/arm64/simpleperf"
            for path in (first, second,
                         root_ndk / "simpleperf/bin/android/arm64/simpleperf",
                         plain_ndk / "simpleperf/bin/android/arm64/simpleperf"):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            base, calls = self._kaslr_with_simpleperf(root, {
                "ANDROID_NDK_HOME": str(home_ndk),
                "ANDROID_NDK_ROOT": str(root_ndk),
                "NDK": str(plain_ndk),
            })

        self.assertEqual(base, 0xFFFFFF8008080000)
        self.assertEqual(calls[0], [
            "push", str(first), "/data/local/tmp/portal-simpleperf"
        ])

    def test_simpleperf_keeps_independent_sdk_and_darwin_fallbacks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary).resolve()
            for variable in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
                with self.subTest(variable=variable):
                    sdk_root = root / variable / "ndk"
                    sdk_binary = sdk_root / "simpleperf/bin/android/arm64/simpleperf"
                    sdk_binary.parent.mkdir(parents=True)
                    sdk_binary.touch()
                    _, calls = self._kaslr_with_simpleperf(
                        root, {variable: str(root / variable)}
                    )
                    self.assertEqual(calls[0][1], str(sdk_binary))
                    sdk_binary.unlink()

            existing_sdk = root / "existing SDK"
            home_sdk = root / "home SDK"
            existing_sdk.mkdir()
            home_binary = home_sdk / "ndk/simpleperf/bin/android/arm64/simpleperf"
            home_binary.parent.mkdir(parents=True)
            home_binary.touch()
            _, calls = self._kaslr_with_simpleperf(root, {
                "ANDROID_SDK_ROOT": str(existing_sdk),
                "ANDROID_HOME": str(home_sdk),
            })
            self.assertEqual(calls[0][1], str(home_binary))

            darwin_binary = root / "Library/Android/sdk/ndk" / \
                "simpleperf/bin/android/arm64/simpleperf"
            darwin_binary.parent.mkdir(parents=True)
            darwin_binary.touch()
            _, calls = self._kaslr_with_simpleperf(root, {}, system="Darwin")
            self.assertEqual(calls[0][1], str(darwin_binary))

    def test_simpleperf_missing_binary_fails_without_device_calls(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary).resolve()
            provisioner = portal.PortalProvisioner("serial", 1, root)
            provisioner.target = SimpleNamespace(
                bundled_simpleperf=True,
                kaslr_strategy="simpleperf",
                kaslr_pc_offsets=(0x3354,),
            )
            with mock.patch.dict(os.environ, {}, clear=True), \
                    mock.patch.object(portal.platform, "system", return_value="Darwin"), \
                    mock.patch.object(pathlib.Path, "home", return_value=root), \
                    mock.patch.object(provisioner, "adb_run") as adb_run:
                with self.assertRaisesRegex(portal.ProvisionError, "simpleperf binary"):
                    provisioner.kaslr_base("test")
            adb_run.assert_not_called()

    def test_hook_size_limits_with_native_make_and_spaced_toolchain(self):
        for target, limit in (("portal-uid1000-hook.bin", 316),
                              ("portal-uid1000-hook-aloha.bin", 32768)):
            for size in (limit, limit + 1):
                with self.subTest(target=target, size=size), tempfile.TemporaryDirectory() as temporary:
                    root = pathlib.Path(temporary).resolve()
                    helper = root / "uid1000-helper"
                    (helper / "native").mkdir(parents=True)
                    shutil.copy2(ROOT / "android-env.mk", root)
                    shutil.copy2(ROOT / "uid1000-helper/Makefile", helper)
                    for source in ("boot_hook.S", "boot_hook_runtime.S"):
                        shutil.copy2(ROOT / "uid1000-helper/native" / source, helper / "native")
                    toolchain = root / "tool chain"
                    (toolchain / "bin").mkdir(parents=True)
                    for name in ("aarch64-linux-android29-clang", "llvm-objcopy"):
                        path = toolchain / "bin" / name
                        path.write_text(f"#!{sys.executable}\n"
                            "import os, pathlib, sys\n"
                            "args = sys.argv[1:]\n"
                            "output = args[args.index('-o') + 1] if '-o' in args else args[-1]\n"
                            "pathlib.Path(output).write_bytes(b'x' * int(os.environ['HOOK_BYTES']))\n")
                        path.chmod(0o755)
                    environment = dict(os.environ, HOOK_BYTES=str(size))
                    for name in ("JAVA_HOME", "MAKEFLAGS", "MFLAGS"):
                        environment.pop(name, None)
                    result = subprocess.run(["make", "--no-print-directory", "-s",
                        f"TOOLCHAIN={toolchain}", f"build/{target}"], cwd=helper,
                        env=environment, capture_output=True, text=True)
                    if size <= limit:
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual((helper / "build" / target).stat().st_size, size)
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertFalse((helper / "build" / target).exists())


if __name__ == "__main__":
    unittest.main()
