#!/usr/bin/env python3
"""Exercise Steam curve conversion, scale detection, and backlight permissions."""

from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / "system_files/usr/libexec/armada"
CONVERTER = HELPERS / "steam-backlight-value"
convert = runpy.run_path(str(CONVERTER))["brightness_value"]


class SteamBacklightTest(unittest.TestCase):
    def test_inspected_steam_curve(self):
        # Captured on Nova using exact Steam SetBrightness inputs, 2026-10-25.
        # Steam truncates to integers before calling the helper, so inversion
        # cannot recover all precision, especially near the dim end.
        for raw, percent in ((67, 10), (187, 25), (1024, 50), (1961, 75),
                             (2896, 90), (3445, 100)):
            with self.subTest(percent=percent):
                self.assertAlmostEqual(convert(raw, 3445, 3445, "non-linear"),
                                       173 + (3445 - 173) * percent / 100, delta=10)

    def test_monotonic_and_bounded(self):
        values = [convert(v, 3445, 3445, "non-linear") for v in range(3446)]
        self.assertEqual(values, sorted(values))
        self.assertEqual(values[0], 173)
        self.assertEqual(values[-1], 3445)
        self.assertGreater(values[1], 0)

    def test_minimum_brightness(self):
        # Steam's 0% slider produces raw 34, not zero. Both must stay visible.
        for value in (0, 1, 34):
            self.assertEqual(convert(value, 3445, 3445, "non-linear"), 173)
        self.assertEqual(convert(0, 3445, 255, "non-linear"), 13)
        self.assertEqual(convert(0, 3445, 1, "non-linear"), 1)

    def test_low_slider_steps_have_no_clamped_region(self):
        # Steam's integer outputs at 0%, 1%, 2%, and 5% slider positions.
        values = [convert(v, 3445, 3445, "non-linear") for v in (34, 36, 39, 48)]
        self.assertTrue(all(left < right for left, right in zip(values, values[1:])))

    def test_passthrough_and_primary_rescaling(self):
        for scale in ("linear", "unknown", ""):
            self.assertEqual(convert(250, 1000, 2000, scale), 500)
        self.assertAlmostEqual(convert(1024, 3445, 1000, "non-linear"),
                               525, delta=1)

    def test_invalid_ranges(self):
        for value, source, target in ((-1, 3445, 3445), (3446, 3445, 3445),
                                      (1, 0, 3445), (1, 3445, 0)):
            with self.assertRaises(ValueError):
                convert(value, source, target, "non-linear")

    def test_sysfs_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "max_brightness").write_text("3445\n")
            args = [str(CONVERTER), "1024", tmp, tmp]
            self.assertEqual(subprocess.check_output(args, text=True).strip(), "1024")
            (path / "scale").write_text("non-linear\n")
            self.assertAlmostEqual(int(subprocess.check_output(args, text=True)), 1809, delta=1)
            args[1] = "3446"
            result = subprocess.run(args, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")

    def test_acl_policy(self):
        # Substitute only device discovery and the sysfs root; chmod/chgrp
        # operate on a temporary regular file, never on a real backlight.
        source = (HELPERS / "backlight-acl").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            brightness = path / "panel/brightness"
            brightness.parent.mkdir()
            brightness.touch()
            for primary, scale, writable in (("", "linear", True),
                                              ("", "non-linear", False),
                                              ("", "unknown", True), ("", None, True),
                                              ("primary", "linear", False)):
                scale_path = brightness.parent / "scale"
                if scale is None:
                    scale_path.unlink(missing_ok=True)
                else:
                    scale_path.write_text(scale + "\n")
                brightness.chmod(0o666)
                script = source.replace('eval "$(/usr/libexec/armada/device-env)"',
                                        f'ARMADA_PRIMARY_BACKLIGHT={primary}')
                script = script.replace("/sys/class/backlight", tmp)
                subprocess.run(["bash", "-s", "--", "panel"], input=script,
                               text=True, check=True)
                self.assertEqual(bool(brightness.stat().st_mode & 0o020), writable)
                if not writable:
                    self.assertEqual(brightness.stat().st_mode & 0o022, 0)

    def test_priv_write_integration(self):
        source = (ROOT / "system_files/usr/bin/steamos-polkit-helpers/steamos-priv-write").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            for name in ("primary", "secondary"):
                panel = path / name
                panel.mkdir()
                (panel / "brightness").write_text("200\n")
                (panel / "max_brightness").write_text("3445\n")
                (panel / "scale").write_text("non-linear\n" if name == "primary" else "linear\n")
            # Exercise the real shell branch without pkexec, sysfs or journald.
            source = source.replace('if [[ $EUID -ne 0 ]]; then', 'if false; then')
            source = source.replace('eval "$(/usr/libexec/armada/device-env)"',
                                    'ARMADA_PRIMARY_BACKLIGHT=primary')
            source = source.replace('/usr/libexec/armada/steam-backlight-value', str(CONVERTER))
            source = source.replace('/sys/class/backlight', tmp)
            source = source.replace('systemd-cat -t armada-steamos-priv-write -p info', 'cat >/dev/null')
            target = path / "secondary/brightness"
            result = subprocess.run(["bash", "-s", "--", str(target), "1024"],
                                    input=source, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertAlmostEqual(int((path / "primary/brightness").read_text()), 1809, delta=1)
            self.assertEqual(target.read_text(), "200\n")
            previous = (path / "primary/brightness").read_text()
            result = subprocess.run(["bash", "-s", "--", str(target), "3446"],
                                    input=source, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((path / "primary/brightness").read_text(), previous)


if __name__ == "__main__":
    unittest.main()
