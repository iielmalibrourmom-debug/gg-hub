"""Real Linux device access; no catalogue entries or simulated write successes.

Wire contract checked against libratbag master ratbagd/*.c (API 2), doc/dbus.rst,
and pwr-Solaar/Solaar lib/solaar/cli/{show,config}.py on 2026-10-18.
ratbagd Commit is asynchronous: a reply alone NEVER confirms a hardware write.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Any

SERVICE = "org.freedesktop.ratbag1"
ROOT = "/org/freedesktop/ratbag1"
PROPERTIES = "org.freedesktop.DBus.Properties"
API_VERSION = 2
TIMEOUT = 12.0
DEVICE_BUDGET = 20.0
STATUS_BUDGET = 8.0
CONFIGURE_BUDGET = 55.0


class HardwareError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def plain(value):
    if hasattr(value, "signature") and hasattr(value, "value"):
        return plain(value.value)
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    return value


def integer(value, name, low=0, high=0xFFFFFFFF):
    if type(value) is not int or not low <= value <= high:
        raise HardwareError("INVALID_PARAMS", f"{name} must be an integer in {low}..{high}.")
    return value


def logitech_model(model):
    return bool(isinstance(model, str) and re.fullmatch(r"(?:usb|bluetooth):046d:[0-9a-f]{4}:\d+", model))


def macro_events(action):
    """Compile a bounded, balanced, single-pass onboard key macro.

    libratbag-enums.h: KEY_PRESSED=1, KEY_RELEASED=2, WAIT=3. These are
    ratbag event types, not Linux EV_KEY values (release=0 there).
    """
    mode = action.get("mode", "noRepeat")
    if not isinstance(mode, str) or mode not in ("noRepeat", "sequence"):
        raise HardwareError("UNSUPPORTED_SETTING", "Onboard binding supports a single macro pass; repeat and toggle are software playback modes.")
    if ("events" in action) == ("steps" in action) or "value" in action:
        raise HardwareError("INVALID_PARAMS", "A macro action requires exactly one of events or steps.")
    events = action.get("events")
    if "steps" in action:
        steps = action["steps"]
        if not isinstance(steps, list) or not 1 <= len(steps) <= 512:
            raise HardwareError("INVALID_PARAMS", "Macro steps must contain 1..512 entries.")
        try:
            from evdev import ecodes
        except ImportError:
            raise HardwareError("DEPENDENCY_MISSING", "Install python-evdev to resolve Linux key names for onboard macros.") from None
        events = []
        def keycode(name):
            if not isinstance(name, str) or not re.fullmatch(r"(?:KEY|BTN)_[A-Z0-9_]{1,40}", name):
                raise HardwareError("INVALID_PARAMS", "Macro keys must use Linux KEY_* or BTN_* names.")
            return integer(ecodes.ecodes.get(name), "macro keycode", 1, 0x2FF)
        def tap(name):
            code = keycode(name)
            events.extend([[1, code], [2, code]])
        for step in steps:
            if not isinstance(step, dict):
                raise HardwareError("INVALID_PARAMS", "Every macro step must be an object.")
            kind = step.get("type")
            if kind == "key" and set(step) == {"type", "key", "action"}:
                code = keycode(step["key"])
                if step["action"] == "tap":
                    tap(step["key"])
                elif step["action"] in ("down", "up"):
                    events.append([1 if step["action"] == "down" else 2, code])
                else:
                    raise HardwareError("INVALID_PARAMS", "Macro key action must be down, up or tap.")
            elif kind == "delay" and set(step) == {"type", "ms"}:
                events.append([3, integer(step["ms"], "macro delay", 0, 60000)])
            elif kind == "text" and set(step) == {"type", "text"}:
                text = step["text"]
                if not isinstance(text, str) or not 1 <= len(text) <= 1024 or any(ord(char) < 32 or ord(char) > 126 for char in text):
                    raise HardwareError("INVALID_PARAMS", "Onboard text supports printable US ASCII only.")
                from .automation import _text_keys
                for char in text:
                    name, shift = _text_keys(char)
                    if shift:
                        events.append([1, keycode("KEY_LEFTSHIFT")])
                    tap(name)
                    if shift:
                        events.append([2, keycode("KEY_LEFTSHIFT")])
            else:
                raise HardwareError("INVALID_PARAMS", "Unknown macro step or fields.")
            if len(events) > 512:
                raise HardwareError("INVALID_PARAMS", "An onboard macro may expand to at most 512 events.")
    if not isinstance(events, list) or not 1 <= len(events) <= 512:
        raise HardwareError("INVALID_PARAMS", "Macro events must contain 1..512 entries.")
    pressed, duration, normalized = set(), 0, []
    for event in events:
        if not isinstance(event, list) or len(event) != 2:
            raise HardwareError("INVALID_PARAMS", "A macro event is [ratbagType, value].")
        kind = integer(event[0], "macro event type", 1, 3)
        value = integer(event[1], "macro event value", 0 if kind == 3 else 1, 60000 if kind == 3 else 0x2FF)
        if kind == 1:
            if value in pressed:
                raise HardwareError("INVALID_PARAMS", "Macro key presses and releases must be balanced.")
            pressed.add(value)
        elif kind == 2:
            if value not in pressed:
                raise HardwareError("INVALID_PARAMS", "Macro key presses and releases must be balanced.")
            pressed.remove(value)
        else:
            duration += value
        normalized.append([kind, value])
    if pressed or duration > 300000:
        raise HardwareError("INVALID_PARAMS", "An onboard macro must release every key and last at most 300 seconds.")
    return normalized


class RatbagTransport:
    """Small dbus-next transport. API is injectable for protocol/error tests."""
    def __init__(self):
        self.bus = None
        self.resync = set()

    async def connect(self):
        if self.bus:
            return
        try:
            from dbus_next.aio import MessageBus
            from dbus_next import BusType, Message, MessageType
        except ImportError:
            raise HardwareError("DEPENDENCY_MISSING", "Install python-dbus-next and libratbag/ratbagd.") from None
        try:
            self.bus = await asyncio.wait_for(MessageBus(bus_type=BusType.SYSTEM).connect(), TIMEOUT)
            def receive(message):
                if message.message_type == MessageType.SIGNAL and message.interface == SERVICE + ".Device" and message.member == "Resync":
                    self.resync.add(message.path)
            self.bus.add_message_handler(receive)
            reply = await asyncio.wait_for(self.bus.call(Message(destination="org.freedesktop.DBus", path="/org/freedesktop/DBus", interface="org.freedesktop.DBus", member="AddMatch", signature="s", body=[f"type='signal',sender='{SERVICE}',interface='{SERVICE}.Device',member='Resync'"])), TIMEOUT)
            if reply.message_type == MessageType.ERROR:
                raise HardwareError("DBUS_ERROR", "Cannot subscribe to ratbagd write errors.")
        except HardwareError:
            self.close()
            raise
        except asyncio.CancelledError:
            self.close()
            raise
        except Exception:
            self.close()
            raise HardwareError("BACKEND_UNAVAILABLE", "Cannot connect to the Linux system D-Bus.") from None

    def close(self):
        if self.bus:
            self.bus.disconnect()
            self.bus = None

    async def call(self, path, interface, member, signature="", body=None):
        from dbus_next import Message, MessageType
        await self.connect()
        try:
            reply = await asyncio.wait_for(self.bus.call(Message(destination=SERVICE, path=path, interface=interface, member=member, signature=signature, body=body or [])), TIMEOUT)
        except asyncio.TimeoutError:
            raise HardwareError("TIMEOUT", "ratbagd did not respond; write state may be unknown.") from None
        except Exception:
            raise HardwareError("DBUS_ERROR", "Communication with ratbagd failed.") from None
        if reply.message_type == MessageType.ERROR:
            # Error text may contain device identifiers. Return only a known code.
            name = reply.error_name or ""
            if name.endswith(("ServiceUnknown", "NameHasNoOwner")):
                raise HardwareError("BACKEND_UNAVAILABLE", "ratbagd is unavailable; install/start libratbag.")
            if name.endswith(("AccessDenied", "NotAuthorized")):
                raise HardwareError("PERMISSION_DENIED", "D-Bus denied access to ratbagd.")
            raise HardwareError("DEVICE_ERROR", "ratbagd rejected the operation; no success is assumed.")
        return reply.body

    async def properties(self, path, kind):
        return (await self.call(path, PROPERTIES, "GetAll", "s", [SERVICE + "." + kind]))[0]

    async def set(self, path, kind, prop, signature, value):
        from dbus_next import Variant
        await self.call(path, PROPERTIES, "Set", "ssv", [SERVICE + "." + kind, prop, Variant(signature, value)])

    async def method(self, path, kind, member):
        result = await self.call(path, SERVICE + "." + kind, member)
        if result and result[0] != 0:
            raise HardwareError("DEVICE_ERROR", f"ratbagd {member} rejected the operation.")


def sysfs_devices(root=Path("/sys/class/hidraw")):
    """Read only Logitech HID metadata; never open hidraw or read HID_UNIQ."""
    devices = []
    if not root.exists():
        return devices
    for entry in sorted(root.glob("hidraw*")):
        try:
            # Do not collect serial / HID_UNIQ, even for diagnostics.
            fields = {}
            for line in (entry / "device" / "uevent").read_text(errors="replace").splitlines():
                key, _, value = line.partition("=")
                if key in ("HID_ID", "HID_NAME"):
                    fields[key] = value
            parts = fields.get("HID_ID", "").split(":")
            if len(parts) != 3 or int(parts[1], 16) != 0x046D:
                continue
            node = Path("/dev") / entry.name
            devices.append({"id": "hidraw:" + entry.name, "name": fields.get("HID_NAME", "Logitech HID device"), "vendorId": "046d", "productId": f"{int(parts[2], 16):04x}", "node": str(node), "readable": os.access(node, os.R_OK), "writable": os.access(node, os.W_OK), "supported": False, "backend": "sysfs", "connected": True, "reason": "Detected by Linux; configuration support has not been established."})
        except (OSError, ValueError):
            continue
    return devices


class SolaarBackend:
    """Bounded CLI adapter. Only extracted setting metadata leaves this class.

    No serials, host names, raw show output or device macro contents are returned.
    Solaar has no stable JSON CLI: unfamiliar/ambiguous output fails closed.
    """
    SETTINGS = ("dpi", "dpi_extended", "report_rate", "report_rate_extended", "onboard_profiles", "fn-swap", "backlight", "backlight-qualitative", "backlight_level", "brightness_control", "divert-gkeys") + tuple(f"analog-button-tuning_{feature}-{button}" for feature in ("actuation", "rapid-trigger", "haptics") for button in (0, 1))

    def __init__(self):
        self.executable = shutil.which("solaar")
        self.selectors = {}

    async def run(self, *arguments, _timeout=TIMEOUT):
        if not self.executable:
            raise HardwareError("DEPENDENCY_MISSING", "Install Solaar for supported HID++ keyboard settings.")
        if not arguments or arguments[0] not in ("show", "config"):
            raise HardwareError("INVALID_PARAMS", "Solaar command is not allowed.")
        env = dict(os.environ, LC_ALL="C", LANG="C", LANGUAGE="C")
        try:
            process = await asyncio.create_subprocess_exec(self.executable, *arguments, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, env=env, limit=1024 * 1024)
            async def read_bounded():
                chunks, size = [], 0
                while True:
                    chunk = await process.stdout.read(65536)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > 1024 * 1024:
                        raise HardwareError("SOLAAR_ERROR", "Solaar output exceeded the supported limit.")
                    chunks.append(chunk)
                await process.wait()
                return b"".join(chunks)
            try:
                output = await asyncio.wait_for(read_bounded(), _timeout)
            except asyncio.TimeoutError:
                if process.returncode is None:
                    process.kill()
                await process.communicate()
                raise HardwareError("TIMEOUT", "Solaar did not respond in time; device state may be unknown.") from None
            except BaseException:
                if process.returncode is None:
                    process.kill()
                await process.communicate()
                raise
            if process.returncode != 0:
                raise HardwareError("SOLAAR_ERROR", "Solaar could not read or apply this setting.")
            if len(output) > 1024 * 1024:
                raise HardwareError("SOLAAR_ERROR", "Solaar output exceeded the supported limit.")
            return output.decode("utf-8", errors="replace")
        except OSError:
            raise HardwareError("BACKEND_UNAVAILABLE", "Unable to start Solaar.") from None

    @staticmethod
    def parse_show(output):
        results, current = [], None
        for line in output.splitlines():
            # Headings are unindented direct devices or '  n: device name'.
            heading = re.fullmatch(r"  \d+: (.+)", line)
            if heading or (line and not line.startswith(" ")):
                if current and current.get("kind") in ("keyboard", "mouse") and current.get("node"):
                    results.append(current)
                name = heading[1] if heading else line
                current = {"name": name, "connected": True}
                continue
            if current is None:
                continue
            if line.strip() == "Device is offline.":
                current["connected"] = False
            match = re.fullmatch(r"\s+Kind\s+:\s*(keyboard|mouse)\s*", line)
            if match:
                current["kind"] = match[1]
            match = re.fullmatch(r"\s+Device path\s+:\s*(/dev/hidraw\d+)\s*", line)
            if match:
                current["node"] = match[1]
            match = re.fullmatch(r"\s+Battery:\s+(\d{1,3})%(?:\s.*|,.*)", line)
            if match and 0 <= int(match[1]) <= 100:
                current["battery"] = int(match[1])
        if current and current.get("kind") in ("keyboard", "mouse") and current.get("node"):
            results.append(current)
        return results

    @staticmethod
    def parse_setting(output, name, key=None):
        value = None
        choices = None
        for line in output.splitlines():
            if line.startswith(name + " = "):
                value = line[len(name) + 3:].strip()
            if key is not None:
                match = re.fullmatch(re.escape(name) + r" \{" + re.escape(key) + r":([^{}]+)\}", line)
                if match:
                    value = match[1].strip()
            match = re.search(r"possible values: one of \[\s*(.*?)\s*\]", line)
            if match:
                choices = [s.strip() for s in match[1].split(",")]
        if value is None or value.startswith("?") or len(value) > 200:
            raise HardwareError("SETTING_UNAVAILABLE", "This setting is unavailable or unreadable on the device.")
        result = {"name": name, "value": value, "writable": True}
        if key is not None:
            result["key"] = key
        if choices:
            result["choices"] = choices
        if name in ("fn-swap", "divert-gkeys"):
            result["type"] = "boolean"
        else:
            result["type"] = "choice" if choices else "integer"
        return result

    async def devices(self, budget=17.0):
        if not self.executable:
            return []
        if budget <= 0.2:
            return []
        deadline = asyncio.get_running_loop().time() + min(17.0, budget)
        parsed = self.parse_show(await self.run("show", _timeout=min(4.0, budget - 0.1)))
        self.selectors.clear()
        devices = []
        for item in parsed:
            # Device-name selectors are accepted by Solaar, but must be unique.
            if sum(item["name"].casefold() in x["name"].casefold() for x in parsed) != 1:
                continue
            if not item["connected"] or item["name"].startswith("-") or len(item["name"]) > 150:
                continue
            identifier = "solaar:" + hashlib.sha256((item["node"] + "\0" + item["name"]).encode()).hexdigest()[:16]
            self.selectors[identifier] = item["name"]
            settings = []
            for name in self.SETTINGS:
                if asyncio.get_running_loop().time() >= deadline:
                    break
                if item["kind"] == "mouse" and name in ("fn-swap", "backlight", "backlight-qualitative", "backlight_level", "brightness_control", "divert-gkeys"):
                    continue
                if item["kind"] == "keyboard" and name.startswith("analog-button-tuning_"):
                    continue
                try:
                    if name == "dpi_extended":
                        for key in ("X", "Y", "LOD"):
                            try:
                                output = await self.run("config", item["name"], name, key, _timeout=min(2.5, max(0.1, deadline - asyncio.get_running_loop().time())))
                                settings.append(self.parse_setting(output, name, key))
                            except HardwareError:
                                continue
                    else:
                        settings.append(self.parse_setting(await self.run("config", item["name"], name, _timeout=min(2.5, max(0.1, deadline - asyncio.get_running_loop().time()))), name))
                except HardwareError as error:
                    if error.code == "TIMEOUT":
                        break
            devices.append({**item, "id": identifier, "backend": "solaar", "supported": bool(settings), "capabilities": {"settings": [x["name"] for x in settings]}, "settings": settings, "profiles": [], "limitations": "Only successfully queried allowlisted HID++ settings are exposed; G HUB feature parity is not established."})
        return devices

    async def configure(self, params):
        if set(params) - {"deviceId", "setting", "value", "key"}:
            raise HardwareError("INVALID_PARAMS", "Solaar accepts deviceId, setting, optional key and value only.")
        name = params.get("setting")
        if name not in self.SETTINGS:
            raise HardwareError("UNSUPPORTED_SETTING", "This Solaar setting is not supported by GG HUB.")
        key = params.get("key")
        if name == "dpi_extended":
            if key not in ("X", "Y", "LOD"):
                raise HardwareError("INVALID_PARAMS", "Extended DPI requires key X, Y or LOD.")
        elif key is not None:
            raise HardwareError("INVALID_PARAMS", "This setting does not accept a key.")
        # Refresh identity without querying unrelated settings on every write.
        parsed = self.parse_show(await self.run("show"))
        selected = next((item for item in parsed if "solaar:" + hashlib.sha256((item["node"] + "\0" + item["name"]).encode()).hexdigest()[:16] == params["deviceId"]), None)
        if selected is None or not selected["connected"] or selected["name"].startswith("-") or sum(selected["name"].casefold() in item["name"].casefold() for item in parsed) != 1:
            raise HardwareError("DEVICE_NOT_FOUND", "The device is disconnected or its selector is ambiguous.")
        selector = selected["name"]
        arguments = ("config", selector, name) + ((key,) if key is not None else ())
        before = self.parse_setting(await self.run(*arguments), name, key)
        value = params.get("value")
        if before["type"] == "boolean":
            if type(value) is not bool:
                raise HardwareError("INVALID_PARAMS", "This setting requires true or false.")
            argument = "true" if value else "false"
        elif before.get("choices"):
            if not isinstance(value, (str, int)) or isinstance(value, bool) or str(value) not in before["choices"]:
                raise HardwareError("INVALID_PARAMS", "Value must be one of the queried setting choices.")
            argument = str(value)
        else:
            argument = str(integer(value, "value", 0, 65535))
        await self.run(*arguments, argument)
        after = self.parse_setting(await self.run(*arguments), name, key)
        observed = after["value"].lower()
        expected = argument.lower()
        matches = observed == expected or (expected == "true" and observed in ("on", "1", "yes")) or (expected == "false" and observed in ("off", "0", "no"))
        if not matches:
            raise HardwareError("READBACK_MISMATCH", "Solaar returned a different value after the write.")
        return {"backend": "solaar", "deviceId": params["deviceId"], "applied": True, "readbackVerified": True, "setting": after}


class HardwareService:
    def __init__(self, transport=None, platform=None, sysfs_root=None, commit_timeout=15.0):
        self.transport = transport or RatbagTransport()
        self.platform = platform or sys.platform
        self.sysfs_root = sysfs_root or Path("/sys/class/hidraw")
        self.commit_timeout = commit_timeout
        self.solaar = SolaarBackend()
        self.lock = asyncio.Lock()

    def linux(self):
        if self.platform != "linux":
            raise HardwareError("UNSUPPORTED_PLATFORM", "Hardware configuration requires Linux. No Windows hardware is modified.")

    async def _locked(self, callback, *arguments):
        # Discovery and profile application share one lock: a read must not
        # inspect partially staged settings while a different request writes.
        async with self.lock:
            return await callback(*arguments)

    async def manager(self):
        await self.transport.connect()
        manager = plain(await self.transport.properties(ROOT, "Manager"))
        if manager.get("APIVersion") != API_VERSION:
            raise HardwareError("UNSUPPORTED_API_VERSION", f"GG HUB supports ratbagd D-Bus API {API_VERSION} only.")
        return manager

    async def status(self):
        if self.platform != "linux":
            return {"platform": self.platform, "supported": False, "backend": "unavailable", "connected": False, "error": {"code": "UNSUPPORTED_PLATFORM", "message": "Hardware access requires Linux."}, "devices": []}
        error = None
        try:
            await asyncio.wait_for(self._locked(self.manager), STATUS_BUDGET)
            available = True
        except asyncio.TimeoutError:
            available = False
            error = {"code": "TIMEOUT", "message": "Hardware status exceeded its time budget; another device operation may still be running."}
        except HardwareError as exc:
            available = False
            error = {"code": exc.code, "message": exc.message}
        return {"platform": "linux", "supported": True, "backend": "ratbagd", "available": available, "apiVersion": API_VERSION if available else None, "error": error, "solaar": {"available": bool(self.solaar.executable), "scope": "Successfully queried allowlisted HID++ settings only"}, "hidraw": sysfs_devices(self.sysfs_root)}

    async def read_device(self, path):
        device = plain(await self.transport.properties(path, "Device"))
        if not logitech_model(device.get("Model")):
            return None
        profiles = []
        for profile_path in device.get("Profiles", []):
            p = plain(await self.transport.properties(profile_path, "Profile"))
            resolutions, buttons, leds = [], [], []
            for resolution_path in p.get("Resolutions", []):
                r = plain(await self.transport.properties(resolution_path, "Resolution"))
                resolutions.append({"id": resolution_path, "index": r.get("Index"), "dpi": r.get("Resolution"), "values": r.get("Resolutions", []), "active": r.get("IsActive", False), "default": r.get("IsDefault", False), "disabled": r.get("IsDisabled", False), "capabilities": r.get("Capabilities", [])})
            for button_path in p.get("Buttons", []):
                b = plain(await self.transport.properties(button_path, "Button"))
                mapping = b.get("Mapping", [1000, 0])
                # Do not expose existing user macros as part of discovery.
                if mapping and mapping[0] == 4:
                    mapping = [4, {"redacted": True}]
                buttons.append({"id": button_path, "index": b.get("Index"), "actionTypes": b.get("ActionTypes", []), "mapping": mapping})
            for led_path in p.get("Leds", []):
                led = plain(await self.transport.properties(led_path, "Led"))
                leds.append({"id": led_path, "index": led.get("Index"), "mode": led.get("Mode"), "modes": led.get("Modes", []), "color": led.get("Color"), "colorDepth": led.get("ColorDepth"), "brightness": led.get("Brightness"), "effectDuration": led.get("EffectDuration")})
            profiles.append({"id": profile_path, "index": p.get("Index"), "name": p.get("Name", ""), "active": p.get("IsActive", False), "disabled": p.get("Disabled", False), "dirty": p.get("IsDirty", False), "reportRate": p.get("ReportRate"), "reportRates": p.get("ReportRates", []), "capabilities": p.get("Capabilities", []), "resolutions": resolutions, "buttons": buttons, "leds": leds})
        return {"id": path, "name": device.get("Name", "Logitech device"), "model": device["Model"], "vendorId": "046d", "productId": device["Model"].split(":")[2], "deviceType": device.get("DeviceType"), "firmware": device.get("FirmwareVersion", ""), "backend": "ratbagd", "connected": True, "supported": True, "profiles": profiles, "capabilities": {"dpi": any(p["resolutions"] for p in profiles), "reportRate": any(p["reportRates"] for p in profiles), "buttons": any(p["buttons"] for p in profiles), "lighting": any(p["leds"] for p in profiles), "onboardProfiles": len(profiles)}}

    async def devices(self):
        self.linux()
        devices, errors = [], []
        deadline = asyncio.get_running_loop().time() + DEVICE_BUDGET
        try:
            await asyncio.wait_for(self._locked(self._collect_devices, devices, errors, deadline), DEVICE_BUDGET)
        except asyncio.TimeoutError:
            errors.append({"backend": "discovery", "code": "TIMEOUT", "message": "Discovery exceeded its 20 second budget. Completed device results are retained; refresh to retry."})
        diagnostics = sysfs_devices(self.sysfs_root)
        return {"devices": devices, "diagnostics": diagnostics, "errors": errors, "connected": bool(devices or diagnostics), "coverage": "Connected backend devices only; sysfs diagnostics do not establish configuration support."}

    async def _collect_devices(self, devices, errors, deadline):
        try:
            manager = await self.manager()
            for path in manager.get("Devices", []):
                try:
                    item = await self.read_device(path)
                    if item:
                        devices.append(item)
                except HardwareError as error:
                    errors.append({"backend": "ratbagd", "code": error.code, "message": error.message})
        except HardwareError as error:
            errors.append({"backend": "ratbagd", "code": error.code, "message": error.message})
        try:
            remaining = deadline - asyncio.get_running_loop().time() - 0.3
            devices.extend(await self.solaar.devices(budget=remaining))
        except HardwareError as error:
            errors.append({"backend": "solaar", "code": error.code, "message": error.message})

    @staticmethod
    def choose(items, index, name):
        if index is None:
            result = next((item for item in items if item.get("active")), None)
            if result:
                return result
            if len(items) == 1:
                return items[0]
            raise HardwareError("INVALID_PARAMS", f"Select an explicit {name} index.")
        integer(index, name)
        result = next((item for item in items if item["index"] == index), None)
        if result is None:
            raise HardwareError("UNSUPPORTED_SETTING", f"The selected {name} does not exist on this device.")
        return result

    async def configure(self, params):
        self.linux()
        if not isinstance(params, dict) or not isinstance(params.get("deviceId"), str):
            raise HardwareError("INVALID_PARAMS", "deviceId is required.")
        callback = self.solaar.configure if params["deviceId"].startswith("solaar:") else self.configure_ratbag
        try:
            return await asyncio.wait_for(self._locked(callback, params), CONFIGURE_BUDGET)
        except asyncio.TimeoutError:
            # Cancellation may follow an already delivered Set/Commit. Never
            # reinterpret this as a rollback or an applied configuration.
            raise HardwareError("WRITE_STATE_UNKNOWN", "Configuration exceeded its 55 second budget. Device or staged state is unknown; refresh and resolve pending changes before retrying.") from None

    async def configure_ratbag(self, params):
        allowed = {"deviceId", "profile", "dpi", "resolutionIndex", "reportRate", "button", "action", "led", "color", "mode", "brightness", "effectDuration", "activateProfile", "activateResolution", "defaultResolution", "resolutionDisabled"}
        if set(params) - allowed:
            raise HardwareError("INVALID_PARAMS", "Unsupported configuration fields.")
        manager = await self.manager()
        path = params["deviceId"]
        if path not in manager.get("Devices", []):
            raise HardwareError("DEVICE_NOT_FOUND", "Select a device currently exposed by ratbagd.")
        device = await self.read_device(path)
        if device is None:
            raise HardwareError("UNSUPPORTED_DEVICE", "GG HUB is limited to Logitech USB/Bluetooth devices.")
        if any(p["dirty"] for p in device["profiles"]):
            raise HardwareError("PENDING_CHANGES", "ratbagd has pending changes; finish or discard them in the client that made them.")
        profile = self.choose(device["profiles"], params.get("profile"), "profile")
        if profile["disabled"]:
            raise HardwareError("UNSUPPORTED_SETTING", "Configuring a disabled profile is not supported.")
        operations = []
        # Each tuple is a fully validated operation + expected readback value.
        def setting(target, kind, prop, signature, value):
            operations.append((target["id"], kind, prop, signature, value))
        def activate(target, kind, member):
            operations.append((target["id"], kind, member, None, None))
        if "reportRate" in params:
            value = integer(params["reportRate"], "reportRate", 1)
            if value not in profile["reportRates"]:
                raise HardwareError("UNSUPPORTED_SETTING", "The selected report rate is not advertised by this profile.")
            setting(profile, "Profile", "ReportRate", "u", value)
        resolution_fields = {"dpi", "activateResolution", "defaultResolution", "resolutionDisabled"}
        if resolution_fields & params.keys():
            resolution = self.choose(profile["resolutions"], params.get("resolutionIndex"), "resolution")
            if "dpi" in params:
                dpi = params["dpi"]
                pair = dpi if isinstance(dpi, list) else [dpi, dpi]
                if len(pair) != 2:
                    raise HardwareError("INVALID_PARAMS", "dpi must be an integer or an [x, y] pair.")
                for value in pair:
                    integer(value, "dpi", 1)
                    if value not in resolution["values"]:
                        raise HardwareError("UNSUPPORTED_SETTING", "DPI must be one of this resolution's advertised values.")
                raw = await self.transport.properties(resolution["id"], "Resolution")
                variant = raw["Resolution"]
                nested = getattr(variant, "value", None)
                signature = getattr(nested, "signature", None)
                if signature not in ("u", "(uu)"):
                    raise HardwareError("UNSUPPORTED_SETTING", "Unsupported ratbagd resolution variant type.")
                if signature == "u" and pair[0] != pair[1]:
                    raise HardwareError("UNSUPPORTED_SETTING", "This device cannot set DPI axes separately.")
                from dbus_next import Variant
                setting(resolution, "Resolution", "Resolution", "v", Variant(signature, pair if signature == "(uu)" else pair[0]))
            if "resolutionDisabled" in params:
                value = params["resolutionDisabled"]
                if type(value) is not bool:
                    raise HardwareError("INVALID_PARAMS", "resolutionDisabled must be boolean.")
                if 2 not in resolution["capabilities"]:
                    raise HardwareError("UNSUPPORTED_SETTING", "This resolution cannot be enabled/disabled.")
                setting(resolution, "Resolution", "IsDisabled", "b", value)
            for key, member in (("activateResolution", "SetActive"), ("defaultResolution", "SetDefault")):
                if key in params:
                    if params[key] is not True:
                        raise HardwareError("INVALID_PARAMS", f"{key} must be true when supplied.")
                    activate(resolution, "Resolution", member)
        if "button" in params or "action" in params:
            button = self.choose(profile["buttons"], params.get("button"), "button")
            action = params.get("action")
            if not isinstance(action, dict) or set(action) - {"type", "value", "events", "steps", "mode"} or not isinstance(action.get("type"), str):
                raise HardwareError("INVALID_PARAMS", "Invalid button action fields.")
            action_type = {"none": 0, "button": 1, "special": 2, "key": 3, "macro": 4}.get(action.get("type"))
            if action_type is None or action_type not in button["actionTypes"]:
                raise HardwareError("UNSUPPORTED_SETTING", "The requested action type is not advertised by this device button.")
            if action_type != 4 and set(action) - {"type", "value"}:
                raise HardwareError("INVALID_PARAMS", "Only macro actions accept events, steps or mode.")
            value = macro_events(action) if action_type == 4 else integer(action.get("value", 0), "action.value")
            if action_type == 0 and value != 0:
                raise HardwareError("INVALID_PARAMS", "A disabled action must have value 0.")
            if action_type == 1 and not 1 <= value <= 32:
                raise HardwareError("INVALID_PARAMS", "Logical mouse button must be in 1..32.")
            if action_type == 2 and not 0x40000001 <= value <= 0x40000012:
                raise HardwareError("INVALID_PARAMS", "Unknown ratbagd special action.")
            if action_type == 3 and not 1 <= value <= 0x2FF:
                raise HardwareError("INVALID_PARAMS", "Key action requires a Linux input keycode in 1..767.")
            from dbus_next import Variant
            setting(button, "Button", "Mapping", "(uv)", [action_type, Variant("a(uu)" if action_type == 4 else "u", value)])
        if {"color", "mode", "brightness", "effectDuration"} & params.keys():
            led = self.choose(profile["leds"], params.get("led"), "LED")
            if "mode" in params:
                value = integer(params["mode"], "mode", 0, 3)
                if value not in led["modes"]:
                    raise HardwareError("UNSUPPORTED_SETTING", "The LED does not advertise this lighting mode.")
                setting(led, "Led", "Mode", "u", value)
            if "color" in params:
                color = params["color"]
                if isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color):
                    color = [int(color[i:i+2], 16) for i in (1, 3, 5)]
                if not isinstance(color, list) or len(color) != 3:
                    raise HardwareError("INVALID_PARAMS", "color requires #RRGGBB or [r,g,b].")
                maximum = {1: 255, 2: 1}.get(led["colorDepth"])
                if maximum is None:
                    raise HardwareError("UNSUPPORTED_SETTING", "This LED has no supported RGB color depth.")
                for value in color:
                    integer(value, "color channel", 0, maximum)
                setting(led, "Led", "Color", "(uuu)", color)
            for key, prop, maximum in (("brightness", "Brightness", 255), ("effectDuration", "EffectDuration", 10000)):
                if key in params:
                    setting(led, "Led", prop, "u", integer(params[key], key, 0, maximum))
        if "activateProfile" in params:
            if params["activateProfile"] is not True:
                raise HardwareError("INVALID_PARAMS", "activateProfile must be true when supplied.")
            activate(profile, "Profile", "SetActive")
        if not operations:
            raise HardwareError("INVALID_PARAMS", "No configuration change was requested.")
        # Validation is complete before the first mutation. D-Bus stages changes;
        # a property failure must NEVER be followed by Commit.
        changed = False
        self.transport.resync.discard(path)
        try:
            for target, kind, prop, signature, value in operations:
                if signature is None:
                    await self.transport.method(target, kind, prop)
                else:
                    await self.transport.set(target, kind, prop, signature, value)
                changed = True
                if path in self.transport.resync:
                    raise HardwareError("WRITE_FAILED", "ratbagd reported a configuration failure before Commit.")
            await self.transport.method(path, "Device", "Commit")
        except HardwareError as error:
            if changed:
                raise HardwareError("WRITE_FAILED_PENDING_CHANGES", "A write failed. Earlier values may remain staged in ratbagd; GG HUB did not issue another commit. Reconnect the device or resolve staged settings before retrying.") from error
            raise
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.commit_timeout
        while True:
            if path in self.transport.resync:
                raise HardwareError("WRITE_FAILED", "ratbagd reported a write failure (Resync); device state must be refreshed.")
            snapshot = await self.read_device(path)
            if snapshot is None:
                raise HardwareError("DEVICE_NOT_FOUND", "Device disconnected while committing settings.")
            if not any(p["dirty"] for p in snapshot["profiles"]):
                break
            if loop.time() >= deadline:
                raise HardwareError("COMMIT_TIMEOUT", "ratbagd has not completed its asynchronous commit; hardware state is unknown.")
            await asyncio.sleep(0.1)
        for target, kind, prop, signature, expected in operations:
            properties = plain(await self.transport.properties(target, kind))
            if signature is None:
                key = "IsDefault" if prop == "SetDefault" else "IsActive"
                matches = properties.get(key) is True
            else:
                matches = properties.get(prop) == plain(expected)
            if not matches:
                raise HardwareError("READBACK_MISMATCH", "The device readback differs from the requested value.")
        if path in self.transport.resync:
            raise HardwareError("WRITE_FAILED", "ratbagd reported a write failure during readback.")
        return {"deviceId": path, "backend": "ratbagd", "applied": True, "readbackVerified": True, "verification": "ratbagd completed commit without Resync and its properties match; physical device behavior still requires testing.", "device": snapshot}

    async def dispatch(self, method, params):
        if method == "hardware.status":
            return await self.status()
        if method == "hardware.devices":
            return await self.devices()
        if method == "hardware.configure":
            return await self.configure(params)
        raise HardwareError("METHOD_NOT_FOUND", "Unknown hardware method.")
