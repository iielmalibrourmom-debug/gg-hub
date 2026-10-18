"""Behavior tests use an injected input sink; no physical input is generated."""
import asyncio
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gg_hub.automation import AutomationError, AutomationService, EvdevSink, _text_keys


class RecordingSink:
    def __init__(self):
        self.events = []
        self.closed = False
        self.pressed = set()

    def validate(self, key):
        if key == "KEY_UNKNOWN":
            raise AutomationError("Unknown key")

    def emit(self, key, down):
        self.events.append((key, down))
        if down:
            self.pressed.add(key)
        else:
            self.pressed.discard(key)

    def close(self):
        self.closed = True


class AutomationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.sinks = []

        def factory():
            sink = RecordingSink()
            self.sinks.append(sink)
            return sink

        self.service = AutomationService(self.directory.name, sink_factory=factory)

    async def asyncTearDown(self):
        await self.service.close()
        self.directory.cleanup()

    async def save_macro(self, steps, mode="noRepeat", identifier="test"):
        return await self.service.dispatch("macros.save", {"id": identifier, "name": "Test macro", "mode": mode, "steps": steps})

    async def test_profile_roundtrip_delete_active_and_isolation(self):
        response = await self.service.dispatch("profiles.save", {"name": "Game", "executable": "game", "deviceSettings": {"mouse": {"dpi": 800}}})
        identifier = response["profile"]["id"]
        self.assertFalse(response["hardwareApplied"])
        response["profile"]["name"] = "Changed outside service"
        activated = await self.service.dispatch("profiles.activate", {"id": identifier})
        self.assertFalse(activated["hardware"]["applied"])
        reopened = AutomationService(self.directory.name)
        listing = await reopened.dispatch("profiles.list")
        self.assertEqual(listing["profiles"][-1]["name"], "Game")
        self.assertEqual(listing["activeProfileId"], identifier)
        await self.service.dispatch("profiles.delete", {"id": identifier})
        self.assertIsNone((await self.service.dispatch("profiles.list"))["activeProfileId"])
        await reopened.close()

    async def test_apply_callback_is_honest_about_failure(self):
        calls = []

        async def apply(settings):
            calls.append(settings)
            raise PermissionError("hidraw permission denied")

        self.service.apply_callback = apply
        await self.service.dispatch("profiles.save", {"id": "game", "name": "Game", "deviceSettings": {"usb": {"dpi": 800}}})
        response = await self.service.dispatch("profiles.activate", {"id": "game"})
        self.assertEqual(calls, [{"usb": {"dpi": 800}}])
        self.assertFalse(response["hardware"]["applied"])
        self.assertIn("permission denied", response["hardware"]["error"])
        self.assertEqual(response["activeProfileId"], "game")

    async def test_failed_atomic_write_preserves_original(self):
        await self.service.dispatch("settings.update", {"pollIntervalMs": 800})
        before = self.service.path.read_bytes()
        with patch("gg_hub.automation.os.replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                await self.service.dispatch("settings.update", {"pollIntervalMs": 900})
        self.assertEqual(self.service.path.read_bytes(), before)
        self.assertEqual((await self.service.dispatch("settings.get"))["settings"]["pollIntervalMs"], 800)
        self.assertEqual([p.name for p in Path(self.directory.name).iterdir()], ["automation.json"])

    async def test_import_is_strict_bounded_and_transactional(self):
        original = (await self.service.dispatch("profiles.export"))["document"]
        for modification in (
            lambda d: d.update(schemaVersion=2),
            lambda d: d.update(schemaVersion=True),
            lambda d: d.update(extra="not allowed"),
            lambda d: d["profiles"][0].update(id="../../escape"),
            lambda d: d["profiles"][0].update(name="x" * 121),
            lambda d: d.update(activeProfileId="missing"),
            lambda d: d["profiles"].append(copy.deepcopy(d["profiles"][0])),
            lambda d: d["settings"].update(pollIntervalMs=0),
            lambda d: d["profiles"][0].update(deviceSettings={"dpi": float("nan")}),
        ):
            candidate = copy.deepcopy(original)
            modification(candidate)
            with self.assertRaises(AutomationError):
                await self.service.dispatch("profiles.import", {"document": candidate})
            self.assertEqual((await self.service.dispatch("profiles.export"))["document"], original)
        with self.assertRaises(AutomationError):
            await self.service.dispatch("profiles.import", {"document": " " * 1_048_577})
        with self.assertRaises(AutomationError):
            await self.service.dispatch("profiles.import", {"document": "{}", "path": "../../escape"})
        imported = await self.service.dispatch("profiles.import", {"document": json.dumps(original)})
        self.assertTrue(imported["imported"])
        self.assertFalse(imported["hardwareApplied"])

    async def test_ids_cannot_select_files_or_paths(self):
        for identifier in ("../escape", "/tmp/evil", "a\\b", "", "a" * 65, "..", None):
            with self.assertRaises(AutomationError):
                await self.service.dispatch("profiles.save", {"id": identifier, "name": "Bad"})
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])

    async def test_macro_cancellation_releases_all_pressed_keys(self):
        await self.save_macro([{"type": "key", "key": "LEFTCTRL", "action": "down"},
                               {"type": "key", "key": "A", "action": "down"},
                               {"type": "delay", "ms": 10000}])
        await self.service.dispatch("macros.run", {"id": "test"})
        for _ in range(10):
            await asyncio.sleep(0)
        self.assertEqual(self.sinks[0].pressed, {"KEY_LEFTCTRL", "KEY_A"})
        await self.service.dispatch("macros.stop", {"id": "test"})
        self.assertEqual(self.sinks[0].pressed, set())
        self.assertTrue(self.sinks[0].closed)
        self.assertEqual((await self.service.dispatch("macros.list"))["runs"][0]["state"], "stopped")

    async def test_immediate_stop_also_closes_sink(self):
        await self.save_macro([{"type": "delay", "ms": 10000}])
        await self.service.dispatch("macros.run", {"id": "test"})
        await self.service.dispatch("macros.stop", {"id": "test"})
        self.assertTrue(self.sinks[0].closed)

    async def test_playback_failure_releases_key_and_surfaces_error(self):
        sink = RecordingSink()
        emit = sink.emit

        def failing_emit(key, down):
            emit(key, down)
            if down:
                raise OSError("injected write error after key down")

        sink.emit = failing_emit
        self.service.sink_factory = lambda: sink
        await self.save_macro([{"type": "key", "key": "A", "action": "down"}])
        await self.service.dispatch("macros.run", {"id": "test"})
        for _ in range(10):
            await asyncio.sleep(0)
        run = (await self.service.dispatch("macros.list"))["runs"][0]
        self.assertEqual(run["state"], "failed")
        self.assertIn("write error", run["error"])
        self.assertFalse(sink.pressed)
        self.assertTrue(sink.closed)

    async def test_validation_closes_sink_without_playing(self):
        await self.save_macro([{"type": "key", "key": "UNKNOWN", "action": "tap"}])
        with self.assertRaises(AutomationError):
            await self.service.dispatch("macros.run", {"id": "test"})
        self.assertTrue(self.sinks[0].closed)
        self.assertFalse(self.sinks[0].events)

    async def test_text_mapping_and_sequence_execute_real_events(self):
        for char in (chr(i) for i in range(32, 127)):
            key, shift = _text_keys(char)
            self.assertTrue(key.startswith("KEY_"))
            self.assertIsInstance(shift, bool)
        await self.save_macro([{"type": "text", "text": "Az!"}], mode="sequence")
        await self.service.dispatch("macros.run", {"id": "test"})
        for _ in range(20):
            await asyncio.sleep(0)
        self.assertIn(("KEY_A", True), self.sinks[0].events)
        self.assertIn(("KEY_1", True), self.sinks[0].events)
        self.assertFalse(self.sinks[0].pressed)
        self.assertEqual((await self.service.dispatch("macros.list"))["runs"][0]["state"], "completed")

    async def test_toggle_and_repeat_are_cancellable(self):
        await self.save_macro([{"type": "key", "key": "A", "action": "tap"}], mode="toggle")
        await self.service.dispatch("macros.run", {"id": "test"})
        response = await self.service.dispatch("macros.run", {"id": "test"})
        self.assertTrue(response["stopped"])
        self.assertTrue(self.sinks[0].closed)
        await self.save_macro([{"type": "delay", "ms": 2000}], mode="repeat")
        await self.service.dispatch("settings.update", {"macroTimeoutSeconds": 1})
        await self.service.dispatch("macros.run", {"id": "test"})
        for _ in range(10):
            await asyncio.sleep(0)
        self.assertEqual((await self.service.dispatch("macros.list"))["runs"][0]["state"], "failed")

    async def test_macro_rejects_scripts_unicode_and_excessive_delay(self):
        for steps in ([{"type": "command", "text": "touch /tmp/pwn"}],
                      [{"type": "text", "text": "中文"}],
                      [{"type": "delay", "ms": True}],
                      [{"type": "delay", "ms": 60001}],
                      [{"type": "key", "key": "A", "action": []}]):
            with self.assertRaises(AutomationError):
                await self.save_macro(steps)
        with self.assertRaises(AutomationError):
            await self.save_macro([{"type": "delay", "ms": 1}], mode=[])

    async def test_linux_input_is_not_simulated_on_windows(self):
        with patch("gg_hub.automation.sys.platform", "win32"):
            with self.assertRaisesRegex(AutomationError, "requires Linux"):
                EvdevSink()

    async def test_auto_switch_matches_executable_without_running_it(self):
        self.service.foreground_provider = lambda: "/games/game;echo-pwn"
        calls = []

        async def apply(settings):
            calls.append(settings)
            return {"applied": True}

        self.service.apply_callback = apply
        await self.service.dispatch("profiles.save", {"id": "game", "name": "Game", "executable": "game;echo-pwn", "deviceSettings": {"mouse": {"dpi": 800}}})
        status = await self.service.dispatch("automation.start")
        self.assertTrue(status["running"])
        for _ in range(10):
            await asyncio.sleep(0)
        self.assertEqual((await self.service.dispatch("profiles.list"))["activeProfileId"], "game")
        self.assertEqual(calls, [{"mouse": {"dpi": 800}}])
        await self.service.dispatch("automation.stop")
        self.assertFalse((await self.service.dispatch("automation.status"))["running"])

    async def test_wayland_declares_unsupported(self):
        with patch("gg_hub.automation.sys.platform", "linux"), patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-0"}):
            with self.assertRaisesRegex(AutomationError, "Wayland"):
                await self.service.dispatch("automation.start")

    async def test_automatic_switch_returns_to_desktop_after_game(self):
        foreground = ["/games/game"]
        self.service.foreground_provider = lambda: foreground[0]
        await self.service.dispatch("settings.update", {"pollIntervalMs": 250})
        await self.service.dispatch("profiles.save", {"id": "game", "name": "Game", "executable": "game"})
        await self.service.dispatch("automation.start")
        for _ in range(10):
            await asyncio.sleep(0)
        self.assertEqual((await self.service.dispatch("profiles.list"))["activeProfileId"], "game")
        foreground[0] = "/usr/bin/editor"
        await asyncio.sleep(0.3)
        self.assertEqual((await self.service.dispatch("profiles.list"))["activeProfileId"], "desktop")

    async def test_slow_hardware_apply_does_not_block_macro_stop_or_local_state(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def slow_apply(settings):
            entered.set()
            await release.wait()
            return {"mouse": {"applied": True}}

        self.service.apply_callback = slow_apply
        await self.service.dispatch("profiles.save", {"id": "game", "name": "Game", "deviceSettings": {"mouse": {"dpi": 800}}})
        await self.save_macro([{"type": "key", "key": "A", "action": "down"}, {"type": "delay", "ms": 10000}])
        await self.service.dispatch("macros.run", {"id": "test"})
        activation = asyncio.create_task(self.service.dispatch("profiles.activate", {"id": "game"}))
        try:
            await asyncio.wait_for(entered.wait(), timeout=1)
            stopped = await asyncio.wait_for(self.service.dispatch("macros.stop", {"id": "test"}), timeout=1)
            self.assertTrue(stopped["stopped"])
            self.assertFalse(self.sinks[0].pressed)
            listed = await asyncio.wait_for(self.service.dispatch("profiles.list"), timeout=1)
            self.assertEqual(listed["activeProfileId"], "game")
            self.assertFalse(activation.done())
        finally:
            release.set()
            await activation

    async def test_stopping_watcher_does_not_interrupt_inflight_hardware_write(self):
        entered, release, completed = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def slow_apply(settings):
            entered.set()
            await release.wait()
            completed.set()
            return {"mouse": {"applied": True}}

        self.service.apply_callback = slow_apply
        self.service.foreground_provider = lambda: "/games/game"
        await self.service.dispatch("profiles.save", {"id": "game", "name": "Game", "executable": "game", "deviceSettings": {"mouse": {"dpi": 800}}})
        await self.service.dispatch("automation.start")
        try:
            await asyncio.wait_for(entered.wait(), timeout=1)
            stopped = await asyncio.wait_for(self.service.dispatch("automation.stop"), timeout=1)
            self.assertFalse(stopped["running"])
            self.assertFalse(completed.is_set())
        finally:
            release.set()
            await self.service.close()
        self.assertTrue(completed.is_set())

    async def test_automatic_hardware_failure_is_exposed_in_status(self):
        async def fail_apply(settings):
            return {"mouse": {"applied": False, "error": {"code": "NO_DEVICE", "message": "Mouse disconnected"}}}

        self.service.apply_callback = fail_apply
        self.service.foreground_provider = lambda: "/games/game"
        await self.service.dispatch("profiles.save", {"id": "game", "name": "Game", "executable": "game", "deviceSettings": {"mouse": {"dpi": 800}}})
        await self.service.dispatch("automation.start")
        for _ in range(20):
            await asyncio.sleep(0)
        status = await self.service.dispatch("automation.status")
        self.assertIn("Mouse disconnected", status["lastError"])

    async def test_shutdown_releases_macro_keys_before_waiting_for_hardware(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def slow_apply(settings):
            entered.set()
            await release.wait()
            return {"mouse": {"applied": True}}

        self.service.apply_callback = slow_apply
        await self.service.dispatch("profiles.save", {"id": "game", "name": "Game", "deviceSettings": {"mouse": {"dpi": 800}}})
        await self.save_macro([{"type": "key", "key": "A", "action": "down"}, {"type": "delay", "ms": 10000}])
        await self.service.dispatch("macros.run", {"id": "test"})
        activation = asyncio.create_task(self.service.dispatch("profiles.activate", {"id": "game"}))
        closing = None
        try:
            await asyncio.wait_for(entered.wait(), timeout=1)
            closing = asyncio.create_task(self.service.close())
            for _ in range(20):
                await asyncio.sleep(0)
            self.assertFalse(self.sinks[0].pressed)
            self.assertTrue(self.sinks[0].closed)
            self.assertFalse(closing.done())
            with self.assertRaisesRegex(AutomationError, "shutting down"):
                await self.service.dispatch("profiles.list")
        finally:
            release.set()
            await activation
            if closing:
                await closing


if __name__ == "__main__":
    unittest.main()
