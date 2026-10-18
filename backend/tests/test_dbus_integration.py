"""Exercise the actual dbus-next wire transport against a private test service.

Linux: unittest starts dbus-run-session and points the child's *system* client
at that disposable bus. It never claims a name on the host system bus and never
opens a physical HID device. This validates marshalling and error/signal handling,
not libratbag drivers or compatibility with a physical mouse.

Signatures mirror upstream ratbagd/ratbagd-{device,profile,resolution,button,led}.c
and ratbagd.c, API 2. In particular Resolution is v containing u/(uu), Mapping
is (uv), and Commit/SetActive return u (older prose docs show empty results).
"""
import asyncio
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from dbus_next import BusType, DBusError, Variant
from dbus_next.aio import MessageBus
from dbus_next.constants import PropertyAccess
from dbus_next.service import ServiceInterface, dbus_property, method, signal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gg_hub.hardware import HardwareError, HardwareService, ROOT, SERVICE

BUS_CHILD = "--bus-child" in sys.argv
DEVICE = ROOT + "/device/wire_test"
OTHER = ROOT + "/device/other_vendor"
PROFILE = ROOT + "/profile/wire_test/p0"
RESOLUTION = ROOT + "/resolution/wire_test/p0/r0"
BUTTON = ROOT + "/button/wire_test/p0/b0"
LED = ROOT + "/led/wire_test/p0/l0"
READ = PropertyAccess.READ
READWRITE = PropertyAccess.READWRITE


class ManagerInterface(ServiceInterface):
    def __init__(self):
        super().__init__(SERVICE + ".Manager")

    @dbus_property(access=READ)
    def APIVersion(self) -> 'i':
        return 2

    @dbus_property(access=READ)
    def Devices(self) -> 'ao':
        return [DEVICE, OTHER]


class DeviceInterface(ServiceInterface):
    def __init__(self, state, model="usb:046d:c539:0"):
        super().__init__(SERVICE + ".Device")
        self.state = state
        self.model = model

    @dbus_property(access=READ)
    def Model(self) -> 's':
        return self.model

    @dbus_property(access=READ)
    def DeviceType(self) -> 'u':
        return 1

    @dbus_property(access=READ)
    def Name(self) -> 's':
        return "Private D-Bus protocol fixture"

    @dbus_property(access=READ)
    def FirmwareVersion(self) -> 's':
        return "test-only"

    @dbus_property(access=READ)
    def Profiles(self) -> 'ao':
        return [PROFILE] if self.model.startswith("usb:046d:") else []

    @method()
    def Commit(self) -> 'u':
        self.state.commits += 1
        if self.state.commit_error:
            raise DBusError(SERVICE + ".Error.Device", "Test service rejected commit")
        def finish():
            self.state.profile.dirty = False
            self.state.profile.emit_properties_changed({"IsDirty": False})
            if self.state.resync_on_commit:
                self.Resync()
        # A real asynchronous signal/PropertiesChanged round trip is required.
        asyncio.get_running_loop().call_later(0.025, finish)
        return 0

    @signal()
    def Resync(self) -> '':
        return None


class ProfileInterface(ServiceInterface):
    def __init__(self, state):
        super().__init__(SERVICE + ".Profile")
        self.state, self.dirty, self.rate = state, False, 1000

    def changed(self):
        self.dirty = True
        self.emit_properties_changed({"IsDirty": True})

    @dbus_property(access=READ)
    def Index(self) -> 'u':
        return 0

    @dbus_property(access=READ)
    def Name(self) -> 's':
        return "Protocol fixture"

    @dbus_property(access=READ)
    def Disabled(self) -> 'b':
        return False

    @dbus_property(access=READ)
    def IsActive(self) -> 'b':
        return True

    @dbus_property(access=READ)
    def IsDirty(self) -> 'b':
        return self.dirty

    @dbus_property(access=READ)
    def Capabilities(self) -> 'au':
        return []

    @dbus_property(access=READ)
    def Resolutions(self) -> 'ao':
        return [RESOLUTION]

    @dbus_property(access=READ)
    def Buttons(self) -> 'ao':
        return [BUTTON]

    @dbus_property(access=READ)
    def Leds(self) -> 'ao':
        return [LED]

    @dbus_property(access=READ)
    def ReportRates(self) -> 'au':
        return [125, 500, 1000]

    @dbus_property(access=READWRITE)
    def ReportRate(self) -> 'u':
        return self.rate

    @ReportRate.setter
    def ReportRate(self, value: 'u'):
        if self.state.rate_error:
            raise DBusError(SERVICE + ".Error.Value", "Test service rejected property")
        self.rate = value
        self.changed()

    @method()
    def SetActive(self) -> 'u':
        self.changed()
        return 0


class ResolutionInterface(ServiceInterface):
    def __init__(self, state):
        super().__init__(SERVICE + ".Resolution")
        self.state, self.dpi = state, [800, 800]

    @dbus_property(access=READ)
    def Index(self) -> 'u':
        return 0

    @dbus_property(access=READ)
    def Capabilities(self) -> 'au':
        return [1, 2]

    @dbus_property(access=READ)
    def IsActive(self) -> 'b':
        return True

    @dbus_property(access=READ)
    def IsDefault(self) -> 'b':
        return True

    @dbus_property(access=READ)
    def IsDisabled(self) -> 'b':
        return False

    @dbus_property(access=READ)
    def Resolutions(self) -> 'au':
        return [400, 800, 1600]

    @dbus_property(access=READWRITE)
    def Resolution(self) -> 'v':
        return Variant("(uu)", self.dpi)

    @Resolution.setter
    def Resolution(self, value: 'v'):
        if value.signature != "(uu)":
            raise DBusError(SERVICE + ".Error.Value", "Resolution variant type must be preserved")
        self.dpi = list(value.value)
        self.state.profile.changed()

    @method()
    def SetActive(self) -> 'u':
        self.state.profile.changed()
        return 0

    @method()
    def SetDefault(self) -> 'u':
        self.state.profile.changed()
        return 0


class ButtonInterface(ServiceInterface):
    def __init__(self, state):
        super().__init__(SERVICE + ".Button")
        self.state = state
        self.mapping = [1, Variant("u", 1)]

    @dbus_property(access=READ)
    def Index(self) -> 'u':
        return 0

    @dbus_property(access=READ)
    def ActionTypes(self) -> 'au':
        return [0, 1, 2, 3]

    @dbus_property(access=READWRITE)
    def Mapping(self) -> '(uv)':
        return self.mapping

    @Mapping.setter
    def Mapping(self, value: '(uv)'):
        self.mapping = value
        self.state.profile.changed()


class LedInterface(ServiceInterface):
    def __init__(self, state):
        super().__init__(SERVICE + ".Led")
        self.state, self.mode, self.color, self.brightness, self.duration = state, 1, [1, 2, 3], 128, 1000

    @dbus_property(access=READ)
    def Index(self) -> 'u':
        return 0

    @dbus_property(access=READ)
    def Modes(self) -> 'au':
        return [0, 1, 2, 3]

    @dbus_property(access=READ)
    def ColorDepth(self) -> 'u':
        return 1

    @dbus_property(access=READWRITE)
    def Mode(self) -> 'u':
        return self.mode

    @Mode.setter
    def Mode(self, value: 'u'):
        self.mode = value
        self.state.profile.changed()

    @dbus_property(access=READWRITE)
    def Color(self) -> '(uuu)':
        return self.color

    @Color.setter
    def Color(self, value: '(uuu)'):
        self.color = list(value)
        self.state.profile.changed()

    @dbus_property(access=READWRITE)
    def Brightness(self) -> 'u':
        return self.brightness

    @Brightness.setter
    def Brightness(self, value: 'u'):
        self.brightness = value
        self.state.profile.changed()

    @dbus_property(access=READWRITE)
    def EffectDuration(self) -> 'u':
        return self.duration

    @EffectDuration.setter
    def EffectDuration(self, value: 'u'):
        self.duration = value
        self.state.profile.changed()


@unittest.skipUnless(sys.platform == "linux" and BUS_CHILD, "Runs only inside the disposable Linux D-Bus child")
class RatbagWireTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.commits = 0
        self.commit_error = self.resync_on_commit = self.rate_error = False
        self.profile = ProfileInterface(self)
        self.resolution = ResolutionInterface(self)
        self.device = DeviceInterface(self)
        self.led = LedInterface(self)
        self.button = ButtonInterface(self)
        self.server = await MessageBus(bus_type=BusType.SESSION).connect()
        for path, interface in ((ROOT, ManagerInterface()), (DEVICE, self.device), (OTHER, DeviceInterface(self, "usb:1532:0098:0")), (PROFILE, self.profile), (RESOLUTION, self.resolution), (BUTTON, self.button), (LED, self.led)):
            self.server.export(path, interface)
        await self.server.request_name(SERVICE)
        self.client = HardwareService(platform="linux", sysfs_root=Path(self.temporary.name), commit_timeout=2)
        self.client.solaar.executable = None

    async def asyncTearDown(self):
        bus = self.client.transport.bus
        self.client.transport.close()
        if bus:
            await bus.wait_for_disconnect()
        self.server.disconnect()
        await self.server.wait_for_disconnect()
        self.temporary.cleanup()

    async def test_discovery_and_configure_dpi_rate_led_and_button_over_wire(self):
        discovered = await self.client.devices()
        self.assertEqual(discovered["errors"], [])
        self.assertEqual([device["id"] for device in discovered["devices"]], [DEVICE])
        self.assertEqual(discovered["devices"][0]["profiles"][0]["resolutions"][0]["dpi"], [800, 800])
        result = await self.client.configure({"deviceId": DEVICE, "dpi": [400, 1600], "reportRate": 500, "led": 0, "color": "#123456", "mode": 3, "brightness": 77, "effectDuration": 1500, "button": 0, "action": {"type": "key", "value": 30}})
        self.assertTrue(result["applied"])
        self.assertTrue(result["readbackVerified"])
        self.assertEqual(self.commits, 1)
        self.assertFalse(self.profile.dirty)
        self.assertEqual(self.resolution.dpi, [400, 1600])
        self.assertEqual(self.profile.rate, 500)
        self.assertEqual(self.led.color, [0x12, 0x34, 0x56])
        self.assertEqual(self.led.mode, 3)
        self.assertEqual(self.led.brightness, 77)
        self.assertEqual(self.button.mapping[0], 3)
        self.assertEqual(self.button.mapping[1].signature, "u")
        self.assertEqual(self.button.mapping[1].value, 30)

    async def test_property_dbus_error_does_not_call_commit(self):
        self.rate_error = True
        with self.assertRaises(HardwareError) as caught:
            await self.client.configure({"deviceId": DEVICE, "reportRate": 500})
        self.assertEqual(caught.exception.code, "DEVICE_ERROR")
        self.assertEqual(self.commits, 0)

    async def test_commit_dbus_error_never_reports_applied(self):
        self.commit_error = True
        with self.assertRaises(HardwareError) as caught:
            await self.client.configure({"deviceId": DEVICE, "reportRate": 500})
        self.assertEqual(caught.exception.code, "WRITE_FAILED_PENDING_CHANGES")
        self.assertEqual(self.commits, 1)

    async def test_real_resync_signal_prevents_write_success(self):
        self.resync_on_commit = True
        with self.assertRaises(HardwareError) as caught:
            await self.client.configure({"deviceId": DEVICE, "dpi": 1600})
        self.assertEqual(caught.exception.code, "WRITE_FAILED")
        self.assertIn(DEVICE, self.client.transport.resync)


@unittest.skipUnless(sys.platform == "linux" and not BUS_CHILD, "Private D-Bus integration requires Linux")
class PrivateBusIntegrationTests(unittest.TestCase):
    def test_ratbag_protocol_on_disposable_bus(self):
        executable = shutil.which("dbus-run-session")
        if not executable:
            self.skipTest("Install dbus-daemon/dbus-run-session to run real wire integration tests")
        result = subprocess.run([executable, "--", sys.executable, str(Path(__file__).resolve()), "--bus-child"], capture_output=True, text=True, timeout=45, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Ran 4 tests", result.stdout + result.stderr)


if __name__ == "__main__":
    if BUS_CHILD:
        # Explicitly retarget only this child. Production still uses SYSTEM bus.
        os.environ["DBUS_SYSTEM_BUS_ADDRESS"] = os.environ["DBUS_SESSION_BUS_ADDRESS"]
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RatbagWireTests))
        raise SystemExit(0 if result.wasSuccessful() else 1)
    unittest.main()
