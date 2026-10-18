"""Protocol-boundary tests: failure handling matters more than UI snapshots."""
import asyncio
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock

from dbus_next import Variant
from gg_hub.hardware import HardwareError, HardwareService, SolaarBackend, ROOT, logitech_model, plain, sysfs_devices
from gg_hub.worker import Worker


DEVICE = ROOT + "/device/event5"
PROFILE = ROOT + "/profile/event5/p0"
RESOLUTION = ROOT + "/resolution/event5/p0/r0"
LED = ROOT + "/led/event5/p0/l0"
BUTTON = ROOT + "/button/event5/p0/b0"


class Daemon:
    """In-memory D-Bus *test fixture*, never used by the shipped backend."""
    def __init__(self):
        self.values = {
            (ROOT, "Manager"): {"APIVersion": 2, "Devices": [DEVICE]},
            (DEVICE, "Device"): {"Name": "Logitech test mouse", "Model": "usb:046d:c539:0", "Profiles": [PROFILE]},
            (PROFILE, "Profile"): {"Index": 0, "IsActive": True, "IsDirty": False, "Disabled": False, "ReportRate": 1000, "ReportRates": [125, 500, 1000], "Resolutions": [RESOLUTION], "Buttons": [BUTTON], "Leds": [LED]},
            (RESOLUTION, "Resolution"): {"Index": 0, "IsActive": True, "Resolution": Variant("v", Variant("(uu)", [800, 800])), "Resolutions": [400, 800, 1600], "Capabilities": [1, 2]},
            (LED, "Led"): {"Index": 0, "Mode": 1, "Modes": [0, 1, 2, 3], "Color": [10, 20, 30], "ColorDepth": 1, "Brightness": 128, "EffectDuration": 1000},
            (BUTTON, "Button"): {"Index": 0, "Mapping": [1, 1], "ActionTypes": [0, 1, 2, 3, 4]},
        }
        self.resync = set()
        self.writes = []
        self.commits = 0
        self.fail_property = None
        self.resync_on_commit = False
        self.keep_dirty = False
        self.ignore_writes = False

    async def connect(self):
        pass

    async def properties(self, path, kind):
        return copy.deepcopy(self.values[(path, kind)])

    async def set(self, path, kind, prop, signature, value):
        self.writes.append((path, prop, signature, value))
        if prop == self.fail_property:
            raise HardwareError("DEVICE_ERROR", "Rejected")
        if not self.ignore_writes:
            self.values[(path, kind)][prop] = Variant("v", value) if prop == "Resolution" else value
        self.values[(PROFILE, "Profile")]["IsDirty"] = True

    async def method(self, path, kind, method):
        if method == "Commit":
            self.commits += 1
            if self.resync_on_commit:
                self.resync.add(path)
            if not self.keep_dirty:
                self.values[(PROFILE, "Profile")]["IsDirty"] = False
        else:
            self.values[(path, kind)]["IsDefault" if method == "SetDefault" else "IsActive"] = True
            self.values[(PROFILE, "Profile")]["IsDirty"] = True


class HardwareTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.daemon = Daemon()
        self.service = HardwareService(self.daemon, platform="linux", commit_timeout=0.02)
        self.service.solaar.executable = None

    async def assert_code(self, code, params):
        with self.assertRaises(HardwareError) as caught:
            await self.service.configure({"deviceId": DEVICE, **params})
        self.assertEqual(caught.exception.code, code)

    async def test_windows_never_connects_or_writes(self):
        self.service.platform = "win32"
        self.daemon.connect = AsyncMock(side_effect=AssertionError("must not access hardware"))
        self.assertFalse((await self.service.status())["supported"])
        await self.assert_code("UNSUPPORTED_PLATFORM", {"dpi": 800})
        self.daemon.connect.assert_not_awaited()

    async def test_unknown_api_fails_closed(self):
        self.daemon.values[(ROOT, "Manager")]["APIVersion"] = 3
        await self.assert_code("UNSUPPORTED_API_VERSION", {"dpi": 800})
        self.assertEqual(self.daemon.writes, [])

    async def test_non_logitech_model_never_exposed_or_written(self):
        self.daemon.values[(DEVICE, "Device")]["Model"] = "usb:1532:0098:0"
        self.assertEqual((await self.service.devices())["devices"], [])
        await self.assert_code("UNSUPPORTED_DEVICE", {"reportRate": 1000})
        self.assertEqual(self.daemon.commits, 0)

    async def test_every_setting_validated_before_any_write(self):
        await self.assert_code("UNSUPPORTED_SETTING", {"reportRate": 500, "dpi": 801})
        self.assertEqual(self.daemon.writes, [])
        await self.assert_code("INVALID_PARAMS", {"reportRate": True})
        await self.assert_code("INVALID_PARAMS", {"color": [255, 256, 0], "led": 0})
        await self.assert_code("INVALID_PARAMS", {"brightness": -1, "led": 0})
        self.assertEqual(self.daemon.writes, [])

    async def test_property_error_does_not_commit(self):
        self.daemon.fail_property = "ReportRate"
        await self.assert_code("DEVICE_ERROR", {"reportRate": 500})
        self.assertEqual(self.daemon.commits, 0)

    async def test_later_failure_leaves_staged_state_and_does_not_commit(self):
        self.daemon.fail_property = "Brightness"
        await self.assert_code("WRITE_FAILED_PENDING_CHANGES", {"reportRate": 500, "led": 0, "brightness": 50})
        self.assertEqual(self.daemon.commits, 0)
        await self.assert_code("PENDING_CHANGES", {"reportRate": 1000})

    async def test_nested_dpi_variant_preserves_xy_type_and_verifies_readback(self):
        result = await self.service.configure({"deviceId": DEVICE, "dpi": [400, 1600]})
        self.assertTrue(result["applied"])
        self.assertTrue(result["readbackVerified"])
        self.assertEqual(self.daemon.writes[0][2], "v")
        self.assertEqual(self.daemon.writes[0][3].signature, "(uu)")
        self.assertEqual(plain(self.daemon.values[(RESOLUTION, "Resolution")]["Resolution"]), [400, 1600])

    async def test_resync_prevents_success(self):
        self.daemon.resync_on_commit = True
        await self.assert_code("WRITE_FAILED", {"reportRate": 500})

    async def test_resync_during_staging_does_not_commit(self):
        original = self.daemon.method
        async def failed_method(path, kind, member):
            await original(path, kind, member)
            if member == "SetActive":
                self.daemon.resync.add(DEVICE)
        self.daemon.method = failed_method
        await self.assert_code("WRITE_FAILED_PENDING_CHANGES", {"activateProfile": True})
        self.assertEqual(self.daemon.commits, 0)

    async def test_dirty_timeout_prevents_success(self):
        self.daemon.keep_dirty = True
        await self.assert_code("COMMIT_TIMEOUT", {"reportRate": 500})

    async def test_readback_mismatch_prevents_success(self):
        self.daemon.ignore_writes = True
        await self.assert_code("READBACK_MISMATCH", {"reportRate": 500})

    async def test_button_key_uses_uv_mapping(self):
        result = await self.service.configure({"deviceId": DEVICE, "button": 0, "action": {"type": "key", "value": 30}})
        self.assertTrue(result["applied"])
        self.assertEqual(self.daemon.writes[0][2], "(uv)")
        self.assertEqual(plain(self.daemon.writes[0][3]), [3, 30])

    async def test_existing_macro_not_returned(self):
        self.daemon.values[(BUTTON, "Button")]["Mapping"] = [4, [[1, 30], [0, 30]]]
        device = await self.service.read_device(DEVICE)
        self.assertEqual(device["profiles"][0]["buttons"][0]["mapping"], [4, {"redacted": True}])

    async def test_onboard_macro_uses_balanced_wire_events_and_verifies_readback(self):
        result = await self.service.configure({"deviceId": DEVICE, "button": 0,
            "action": {"type": "macro", "events": [[1, 29], [1, 46], [2, 46], [2, 29]]}})
        self.assertTrue(result["readbackVerified"])
        mapping = self.daemon.writes[0][3]
        self.assertEqual(mapping[0], 4)
        self.assertEqual(mapping[1].signature, "a(uu)")
        self.assertEqual(result["device"]["profiles"][0]["buttons"][0]["mapping"], [4, {"redacted": True}])

    async def test_unbalanced_or_repeating_onboard_macro_is_rejected_before_writes(self):
        await self.assert_code("INVALID_PARAMS", {"button": 0, "action": {"type": "macro", "events": [[1, 29]]}})
        await self.assert_code("UNSUPPORTED_SETTING", {"button": 0, "action": {"type": "macro", "mode": "toggle", "events": [[1, 29], [2, 29]]}})
        self.assertEqual(self.daemon.writes, [])

    async def test_unavailable_daemon_is_structured_in_discovery(self):
        self.daemon.connect = AsyncMock(side_effect=HardwareError("BACKEND_UNAVAILABLE", "Missing daemon"))
        result = await self.service.devices()
        self.assertEqual(result["devices"], [])
        self.assertEqual(result["errors"][0]["code"], "BACKEND_UNAVAILABLE")


class ParsingTests(unittest.TestCase):
    def test_usb_and_bluetooth_vendor_filter(self):
        for value in ("usb:046d:c539:0", "bluetooth:046d:b034:12"):
            self.assertTrue(logitech_model(value))
        for value in ("unknown", "usb:046d:c539", "usb:1532:c539:0", "046d", "usb:046d:c539:0:123"):
            self.assertFalse(logitech_model(value))

    def test_sysfs_ignores_other_vendors_and_serials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, vendor in enumerate(("0000046D", "00001532")):
                device = root / f"hidraw{index}" / "device"
                device.mkdir(parents=True)
                (device / "uevent").write_text(f"HID_ID=0003:{vendor}:0000C539\nHID_NAME=Device {index}\nHID_UNIQ=private serial\n")
            devices = sysfs_devices(root)
            self.assertEqual(len(devices), 1)
            self.assertFalse(devices[0]["supported"])
            self.assertNotIn("private serial", repr(devices))

    def test_solaar_parser_extracts_only_device_fields(self):
        output = "solaar version 1.1.19\nLightspeed Receiver\n  Device path  : /dev/hidraw0\n  Serial       : private-serial\n  1: G915 Keyboard\n     Device path  : /dev/hidraw1\n     Kind         : keyboard\n     Serial number: private-keyboard-serial\n     Battery: 85%, discharging.\n"
        devices = SolaarBackend.parse_show(output)
        self.assertEqual(devices, [{"name": "G915 Keyboard", "connected": True, "node": "/dev/hidraw1", "kind": "keyboard", "battery": 85}])
        self.assertNotIn("private", repr(devices))

    def test_solaar_choices_are_queried_not_guessed(self):
        parsed = SolaarBackend.parse_setting("# Report Rate\n# possible values: one of [ 1ms, 2ms, 8ms ], or higher/lower\nreport_rate = 1ms\n", "report_rate")
        self.assertEqual(parsed["choices"], ["1ms", "2ms", "8ms"])
        with self.assertRaises(HardwareError):
            SolaarBackend.parse_setting("backlight = ? (failed to read from device)\n", "backlight")


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_rpc_and_invalid_params(self):
        worker = Worker.__new__(Worker)
        worker.hardware = HardwareService(platform="win32")
        worker.automation = None
        self.assertEqual((await worker.request({"id": 1, "method": "shell.run", "params": {}}))["error"]["code"], "METHOD_NOT_FOUND")
        self.assertEqual((await worker.request({"id": 2, "method": "hardware.status", "params": []}))["error"]["code"], "INVALID_PARAMS")
        self.assertEqual((await worker.request({"id": 3, "method": "hardware.status"}))["result"]["platform"], "win32")


class SolaarWriteTests(unittest.IsolatedAsyncioTestCase):
    SHOW = "  1: Test Keyboard\n     Device path  : /dev/hidraw5\n     Kind         : keyboard\n"

    def setUp(self):
        import hashlib
        self.backend = SolaarBackend()
        self.backend.executable = "/usr/bin/solaar"
        self.identifier = "solaar:" + hashlib.sha256(b"/dev/hidraw5\0Test Keyboard").hexdigest()[:16]

    async def test_failed_cli_write_never_reports_applied(self):
        self.backend.run = AsyncMock(side_effect=[self.SHOW, "fn-swap = False\n", HardwareError("SOLAAR_ERROR", "Rejected")])
        with self.assertRaises(HardwareError) as error:
            await self.backend.configure({"deviceId": self.identifier, "setting": "fn-swap", "value": True})
        self.assertEqual(error.exception.code, "SOLAAR_ERROR")
        self.assertEqual(self.backend.run.await_count, 3)

    async def test_write_readback_mismatch_is_error(self):
        self.backend.run = AsyncMock(side_effect=[self.SHOW, "fn-swap = False\n", "Setting fn-swap\n", "fn-swap = False\n"])
        with self.assertRaises(HardwareError) as error:
            await self.backend.configure({"deviceId": self.identifier, "setting": "fn-swap", "value": True})
        self.assertEqual(error.exception.code, "READBACK_MISMATCH")

    async def test_success_requires_fresh_matching_readback(self):
        self.backend.run = AsyncMock(side_effect=[self.SHOW, "fn-swap = False\n", "Setting fn-swap\n", "fn-swap = True\n"])
        result = await self.backend.configure({"deviceId": self.identifier, "setting": "fn-swap", "value": True})
        self.assertTrue(result["readbackVerified"])
        self.backend.run.assert_any_await("config", "Test Keyboard", "fn-swap", "true")

    async def test_ambiguous_substring_device_name_cannot_write(self):
        self.backend.run = AsyncMock(return_value=self.SHOW + "  2: Test Keyboard Pro\n     Device path  : /dev/hidraw6\n     Kind         : keyboard\n")
        with self.assertRaises(HardwareError) as error:
            await self.backend.configure({"deviceId": self.identifier, "setting": "fn-swap", "value": True})
        self.assertEqual(error.exception.code, "DEVICE_NOT_FOUND")
        self.assertEqual(self.backend.run.await_count, 1)

    async def test_extended_dpi_cli_uses_key_and_choice(self):
        import hashlib
        show = "  1: Test Mouse\n     Device path  : /dev/hidraw7\n     Kind         : mouse\n"
        identifier = "solaar:" + hashlib.sha256(b"/dev/hidraw7\0Test Mouse").hexdigest()[:16]
        self.backend.run = AsyncMock(side_effect=[show, "# possible values: one of [ 400, 800, 1600 ]\ndpi_extended {X:800}\n", "Setting DPI\n", "# possible values: one of [ 400, 800, 1600 ]\ndpi_extended {X:1600}\n"])
        result = await self.backend.configure({"deviceId": identifier, "setting": "dpi_extended", "key": "X", "value": "1600"})
        self.assertTrue(result["applied"])
        self.backend.run.assert_any_await("config", "Test Mouse", "dpi_extended", "X", "1600")


if __name__ == "__main__":
    unittest.main()
