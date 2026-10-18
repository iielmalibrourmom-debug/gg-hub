"""Persistent profiles, bounded uinput macros and X11 foreground switching.

Configuration is desired state. Saving/activating a profile alone does not prove
that its hardware settings were applied. No imported value is ever a command.
"""
from __future__ import annotations

import asyncio
import copy
import inspect
import json
import os
import re
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

MAX_DOCUMENT = 1_048_576
MAX_ITEMS = 256
MAX_STEPS = 512
MAX_SECONDS = 300
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
KEY_RE = re.compile(r"(?:KEY|BTN)_[A-Z0-9_]{1,40}\Z")
DEFAULT_SETTINGS = {"autoSwitch": False, "pollIntervalMs": 1000, "macroTimeoutSeconds": 60}


class AutomationError(ValueError):
    """An actionable RPC/configuration error."""


def _object(value: Any, allowed: set[str], required: set[str] = frozenset()) -> dict:
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        raise AutomationError("Expected an object")
    unknown = set(value) - allowed
    if unknown or required - set(value):
        raise AutomationError(f"Invalid fields: unknown={sorted(unknown)}, missing={sorted(required - set(value))}")
    return value


def _identifier(value: Any) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise AutomationError("ID must be 1–64 ASCII letters/digits, underscore or hyphen")
    return value


def _name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 120 or any(ord(c) < 32 for c in value):
        raise AutomationError("Name must contain 1–120 printable characters")
    return value.strip()


def _json_clone(value: Any) -> Any:
    try:
        encoded = json.dumps(value, allow_nan=False, ensure_ascii=False)
        if len(encoded.encode("utf-8")) > MAX_DOCUMENT:
            raise AutomationError("Configuration exceeds 1 MiB")
        return json.loads(encoded)
    except (TypeError, ValueError, RecursionError) as error:
        raise AutomationError(f"Invalid JSON: {error}") from error


def _profile(value: Any) -> dict:
    p = _object(value, {"id", "name", "game", "executable", "deviceSettings"}, {"id", "name"})
    result = {"id": _identifier(p["id"]), "name": _name(p["name"]), "deviceSettings": {}}
    if "game" in p:
        result["game"] = _name(p["game"])
    if "executable" in p:
        executable = p["executable"]
        if not isinstance(executable, str) or len(executable) > 4096 or not executable.strip() or any(ord(c) < 32 for c in executable):
            raise AutomationError("Executable must be a printable Linux executable name or absolute path")
        if not executable.startswith("/") and ("/" in executable or "\\" in executable):
            raise AutomationError("Executable must be a basename or absolute Linux path")
        result["executable"] = executable
    if "deviceSettings" in p:
        if not isinstance(p["deviceSettings"], dict):
            raise AutomationError("deviceSettings must be an object")
        result["deviceSettings"] = _json_clone(p["deviceSettings"])
    return result


def _key(value: Any) -> str:
    if not isinstance(value, str):
        raise AutomationError("Key must be a Linux KEY_* or BTN_* name")
    value = value.upper()
    if not value.startswith(("KEY_", "BTN_")):
        value = "KEY_" + value
    if not KEY_RE.fullmatch(value):
        raise AutomationError("Key must be a Linux KEY_* or BTN_* name")
    return value


def _macro(value: Any) -> dict:
    m = _object(value, {"id", "name", "mode", "steps"}, {"id", "name", "steps"})
    mode = m.get("mode", "noRepeat")
    if not isinstance(mode, str) or mode not in {"noRepeat", "repeat", "toggle", "sequence"}:
        raise AutomationError("Unknown macro mode; Lua scripting is unsupported")
    steps = m["steps"]
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        raise AutomationError("Macro must have 1–512 steps")
    normalized = []
    duration = 0
    for step in steps:
        s = _object(step, {"type", "key", "action", "ms", "text"}, {"type"})
        kind = s["type"]
        if kind == "key":
            _object(s, {"type", "key", "action"}, {"type", "key", "action"})
            if not isinstance(s["action"], str) or s["action"] not in {"down", "up", "tap"}:
                raise AutomationError("Key action must be down, up or tap")
            normalized.append({"type": kind, "key": _key(s["key"]), "action": s["action"]})
        elif kind == "delay":
            _object(s, {"type", "ms"}, {"type", "ms"})
            ms = s["ms"]
            if type(ms) is not int or not 0 <= ms <= 60_000:
                raise AutomationError("Delay must be an integer from 0 to 60000 ms")
            duration += ms
            normalized.append({"type": kind, "ms": ms})
        elif kind == "text":
            _object(s, {"type", "text"}, {"type", "text"})
            text = s["text"]
            if not isinstance(text, str) or not 1 <= len(text) <= 1024 or any(ord(c) < 32 or ord(c) > 126 for c in text):
                raise AutomationError("Text supports 1–1024 printable ASCII characters on a US keyboard layout only")
            normalized.append({"type": kind, "text": text})
        else:
            raise AutomationError("Unsupported macro step; Lua and command execution are unsupported")
    if duration > MAX_SECONDS * 1000:
        raise AutomationError("One macro pass may not exceed 300 seconds")
    return {"id": _identifier(m["id"]), "name": _name(m["name"]), "mode": mode, "steps": normalized}


def _settings(value: Any, partial: bool = False) -> dict:
    s = _object(value, set(DEFAULT_SETTINGS), set() if partial else set(DEFAULT_SETTINGS))
    if "autoSwitch" in s and type(s["autoSwitch"]) is not bool:
        raise AutomationError("autoSwitch must be a boolean")
    for key, low, high in (("pollIntervalMs", 250, 10000), ("macroTimeoutSeconds", 1, MAX_SECONDS)):
        if key in s and (type(s[key]) is not int or not low <= s[key] <= high):
            raise AutomationError(f"{key} must be an integer from {low} to {high}")
    return dict(s)


def _document(value: Any) -> dict:
    d = _object(value, {"schemaVersion", "profiles", "macros", "activeProfileId", "settings"},
                {"schemaVersion", "profiles", "macros", "activeProfileId", "settings"})
    if type(d["schemaVersion"]) is not int or d["schemaVersion"] != 1:
        raise AutomationError("Unsupported configuration schema; expected version 1")
    result = {"schemaVersion": 1, "settings": _settings(d["settings"])}
    for key, validator in (("profiles", _profile), ("macros", _macro)):
        if not isinstance(d[key], list) or len(d[key]) > MAX_ITEMS:
            raise AutomationError(f"{key} must be a list with at most 256 entries")
        result[key] = [validator(item) for item in d[key]]
        identifiers = [item["id"] for item in result[key]]
        if len(set(identifiers)) != len(identifiers):
            raise AutomationError(f"Duplicate {key} IDs")
    active = d["activeProfileId"]
    if active is not None and _identifier(active) not in {p["id"] for p in result["profiles"]}:
        raise AutomationError("Active profile does not exist")
    result["activeProfileId"] = active
    return _json_clone(result)


class EvdevSink:
    """A dedicated virtual input device; never launches a user-supplied process."""

    def __init__(self):
        if sys.platform != "linux":
            raise AutomationError("Macro playback requires Linux /dev/uinput; this host is unsupported")
        try:
            from evdev import UInput, ecodes
        except ImportError as error:
            raise AutomationError("Install python-evdev to enable real macro playback") from error
        self.ecodes = ecodes
        keys = sorted({code for name, code in ecodes.ecodes.items()
                       if name.startswith(("KEY_", "BTN_")) and isinstance(code, int) and 0 < code < ecodes.KEY_MAX})
        try:
            self.device = UInput({ecodes.EV_KEY: keys}, name="GG HUB macro keyboard")
        except (PermissionError, OSError) as error:
            raise AutomationError(f"Cannot open /dev/uinput: {error}. Configure the GG HUB udev rule and re-login") from error

    def validate(self, key: str):
        if key not in self.ecodes.ecodes or not 0 < self.ecodes.ecodes[key] < self.ecodes.KEY_MAX:
            raise AutomationError(f"Unknown Linux input key: {key}")

    def emit(self, key: str, pressed: bool):
        self.device.write(self.ecodes.EV_KEY, self.ecodes.ecodes[key], int(pressed))
        self.device.syn()

    def close(self):
        self.device.close()


# Text uses the US physical keyboard layout, explicitly not Unicode injection.
_PLAIN = "`1234567890-=\\[];',./"
_SHIFT = '~!@#$%^&*()_+|{}:"<>?'
_CODES = ["GRAVE", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "MINUS", "EQUAL", "BACKSLASH", "LEFTBRACE", "RIGHTBRACE", "SEMICOLON", "APOSTROPHE", "COMMA", "DOT", "SLASH"]


def _text_keys(char: str) -> tuple[str, bool]:
    if char == " ":
        return "KEY_SPACE", False
    if char.isalpha():
        return "KEY_" + char.upper(), char.isupper()
    if char in _PLAIN:
        return "KEY_" + _CODES[_PLAIN.index(char)], False
    return "KEY_" + _CODES[_SHIFT.index(char)], True


class AutomationService:
    """JSON RPC dispatcher. sink_factory/apply_callback are injection seams.

    apply_callback(deviceSettings) may return JSON or an awaitable. It should
    report per-device successes/failures; this module does not infer success.
    """

    def __init__(self, config_dir, *, sink_factory=None, apply_callback=None, foreground_provider=None):
        self.config_dir = Path(config_dir).expanduser().resolve()
        self.config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.config_dir / "automation.json"
        self.sink_factory = sink_factory or EvdevSink
        self.apply_callback = apply_callback
        self.foreground_provider = foreground_provider
        self._lock = asyncio.Lock()
        self._runs: dict[str, dict] = {}
        self._apply_tasks = set()
        self._closing = False
        self._auto_task = None
        self._auto_error = None
        self._foreground = None
        self._last_auto_profile = None
        self._data = {"schemaVersion": 1, "profiles": [{"id": "desktop", "name": "DESKTOP", "deviceSettings": {}}],
                      "macros": [], "activeProfileId": "desktop", "settings": dict(DEFAULT_SETTINGS)}
        if self.path.exists() or self.path.is_symlink():
            if self.path.is_symlink() or not self.path.is_file() or self.path.stat().st_size > MAX_DOCUMENT:
                raise AutomationError("Unsafe or oversized configuration file")
            try:
                self._data = _document(json.loads(self.path.read_text(encoding="utf-8")))
            except (OSError, ValueError, RecursionError) as error:
                raise AutomationError(f"Cannot load configuration; existing file was preserved: {error}") from error

    def _commit(self, value: dict):
        value = _document(value)
        if self.path.is_symlink():
            raise AutomationError("Refusing to replace a configuration symlink")
        payload = json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(payload) > MAX_DOCUMENT:
            raise AutomationError("Configuration exceeds 1 MiB")
        fd, temporary = tempfile.mkstemp(prefix=".automation-", suffix=".tmp", dir=self.config_dir)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            if sys.platform == "linux":
                directory_fd = os.open(self.config_dir, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        self._data = value

    def _find(self, collection: str, identifier: Any) -> dict:
        identifier = _identifier(identifier)
        for item in self._data[collection]:
            if item["id"] == identifier:
                return item
        raise AutomationError(f"Unknown {collection} ID: {identifier}")

    async def dispatch(self, method: str, params=None):
        params = {} if params is None else params
        if not isinstance(params, dict):
            raise AutomationError("RPC params must be an object")
        if method == "profiles.activate":
            _object(params, {"id"}, {"id"})
            # Hardware I/O may take seconds. Keep the configuration lock only
            # while validating and committing the desired-state snapshot so
            # macros.stop, status and local edits remain responsive.
            async with self._lock:
                if self._closing:
                    raise AutomationError("Automation service is shutting down")
                profile = self._prepare_activation(params["id"])
            return _json_clone(await self._apply_profile(profile))
        async with self._lock:
            if self._closing:
                raise AutomationError("Automation service is shutting down")
            return _json_clone(await self._dispatch(method, params))

    async def _dispatch(self, method: str, p: dict):
        if method == "profiles.list":
            _object(p, set())
            return {"profiles": self._data["profiles"], "activeProfileId": self._data["activeProfileId"]}
        if method in {"profiles.save", "macros.save"}:
            collection, validator = ("profiles", _profile) if method.startswith("profiles") else ("macros", _macro)
            value = dict(p)
            if "id" not in value:
                value["id"] = str(uuid.uuid4())
            item = validator(value)
            data = copy.deepcopy(self._data)
            existing = next((i for i, old in enumerate(data[collection]) if old["id"] == item["id"]), None)
            if existing is None:
                data[collection].append(item)
            else:
                data[collection][existing] = item
            self._commit(data)
            return {"saved": True, "profile" if collection == "profiles" else "macro": item, "hardwareApplied": False}
        if method in {"profiles.delete", "macros.delete"}:
            _object(p, {"id"}, {"id"})
            collection = method.split(".")[0]
            self._find(collection, p["id"])
            if collection == "macros":
                await self._stop_macro(p["id"])
            data = copy.deepcopy(self._data)
            data[collection] = [item for item in data[collection] if item["id"] != p["id"]]
            if collection == "profiles" and data["activeProfileId"] == p["id"]:
                data["activeProfileId"] = None
                self._last_auto_profile = None
            self._commit(data)
            if collection == "macros":
                self._runs.pop(p["id"], None)
            return {"deleted": True, "id": p["id"], "activeProfileId": data["activeProfileId"], "hardwareApplied": False}
        if method == "profiles.export":
            _object(p, set())
            return {"document": self._data}
        if method == "profiles.import":
            _object(p, {"document"}, {"document"})
            source = p["document"]
            if isinstance(source, str):
                if len(source.encode("utf-8")) > MAX_DOCUMENT:
                    raise AutomationError("Import exceeds 1 MiB")
                try:
                    source = json.loads(source)
                except (ValueError, RecursionError) as error:
                    raise AutomationError("Import is not valid JSON") from error
            data = _document(_json_clone(source))
            await self._stop_auto()
            for identifier in list(self._runs):
                await self._stop_macro(identifier)
            self._commit(data)
            self._runs.clear()
            self._last_auto_profile = None
            return {"imported": True, "profileCount": len(data["profiles"]), "macroCount": len(data["macros"]),
                    "hardwareApplied": False, "automationRunning": False}
        if method == "settings.get":
            _object(p, set())
            return {"settings": self._data["settings"]}
        if method == "settings.update":
            settings = _settings(p, partial=True)
            data = copy.deepcopy(self._data)
            data["settings"].update(settings)
            self._commit(data)
            if settings.get("autoSwitch") is False:
                await self._stop_auto()
            # Explicit automation.start is required to acquire desktop access.
            return {"saved": True, "settings": data["settings"], "automationRunning": bool(self._auto_task and not self._auto_task.done())}
        if method == "macros.list":
            _object(p, set())
            return {"macros": self._data["macros"], "runs": [self._run_status(run) for run in self._runs.values()]}
        if method == "macros.run":
            _object(p, {"id"}, {"id"})
            macro = copy.deepcopy(self._find("macros", p["id"]))
            prior = self._runs.get(macro["id"])
            if prior and prior["task"] and not prior["task"].done():
                if macro["mode"] == "toggle":
                    await self._stop_macro(macro["id"])
                    return {"started": False, "stopped": True, "id": macro["id"]}
                raise AutomationError("Macro is already running; stop it before restarting")
            if sum(not r["task"].done() for r in self._runs.values()) >= 8:
                raise AutomationError("At most eight macros may run concurrently")
            sink = self.sink_factory()
            try:
                for step in macro["steps"]:
                    if step["type"] == "key":
                        sink.validate(step["key"])
                    elif step["type"] == "text":
                        sink.validate("KEY_LEFTSHIFT")
                        for char in step["text"]:
                            sink.validate(_text_keys(char)[0])
            except BaseException:
                sink.close()
                raise
            run = {"id": macro["id"], "state": "running", "error": None, "iterations": 0,
                   "startedAt": time.time(), "task": None}
            run["task"] = asyncio.create_task(self._play(macro, sink, run), name="gg-hub-macro-" + macro["id"])
            self._runs[macro["id"]] = run
            return {"started": True, "id": macro["id"], "timeoutSeconds": self._data["settings"]["macroTimeoutSeconds"],
                    "textLayout": "US ASCII", "sequenceBehavior": "execute steps once in order"}
        if method == "macros.stop":
            _object(p, {"id"}, {"id"})
            return {"id": _identifier(p["id"]), "stopped": await self._stop_macro(p["id"])}
        if method == "automation.status":
            _object(p, set())
            return self._auto_status()
        if method == "automation.start":
            _object(p, set())
            if not self.foreground_provider:
                if sys.platform != "linux":
                    raise AutomationError("Automatic application switching requires Linux")
                if os.environ.get("WAYLAND_DISPLAY"):
                    raise AutomationError("Wayland foreground application tracking is not implemented; select profiles manually")
                if not os.environ.get("DISPLAY"):
                    raise AutomationError("X11 DISPLAY is unavailable; select profiles manually")
                await self._x11_foreground()  # fail before reporting a running watcher
            data = copy.deepcopy(self._data)
            data["settings"]["autoSwitch"] = True
            self._commit(data)
            if not self._auto_task or self._auto_task.done():
                self._auto_error = None
                self._auto_task = asyncio.create_task(self._watch(), name="gg-hub-profile-watcher")
            return self._auto_status()
        if method == "automation.stop":
            _object(p, set())
            await self._stop_auto()
            data = copy.deepcopy(self._data)
            data["settings"]["autoSwitch"] = False
            self._commit(data)
            return self._auto_status()
        raise AutomationError(f"Unsupported automation method: {method}")

    def _prepare_activation(self, identifier: str):
        profile = copy.deepcopy(self._find("profiles", identifier))
        data = copy.deepcopy(self._data)
        data["activeProfileId"] = identifier
        self._commit(data)
        return profile

    async def _apply_profile(self, profile: dict):
        # Stopping the watcher must not interrupt a ratbagd staged write between
        # Set and Commit. Track shielded applications so shutdown can drain them
        # after releasing macro keys. The hardware service bounds its own I/O.
        task = asyncio.create_task(self._run_apply(profile), name="gg-hub-apply-" + profile["id"])
        self._apply_tasks.add(task)
        task.add_done_callback(self._apply_tasks.discard)
        return await asyncio.shield(task)

    async def _run_apply(self, profile: dict):
        application = {"applied": False, "reason": "No hardware application callback is connected"}
        if not profile["deviceSettings"]:
            application = {"applied": False, "reason": "Profile has no device settings"}
        elif self.apply_callback:
            try:
                result = self.apply_callback(copy.deepcopy(profile["deviceSettings"]))
                if inspect.isawaitable(result):
                    result = await result
                application = {"result": _json_clone(result), "attempted": True}
            except Exception as error:
                application = {"applied": False, "error": str(error), "attempted": True}
        return {"activeProfileId": profile["id"], "saved": True, "hardware": application}

    @staticmethod
    def _application_error(hardware: dict):
        if hardware.get("error"):
            return str(hardware["error"])
        result = hardware.get("result")
        if not isinstance(result, dict):
            return None
        failures = []
        for identifier, value in result.items():
            if isinstance(value, dict) and value.get("applied") is False:
                error = value.get("error", "Hardware settings were not applied")
                if isinstance(error, dict):
                    error = error.get("message", error.get("code", "Hardware settings were not applied"))
                failures.append(f"{identifier}: {error}")
        return "; ".join(failures) or None

    @staticmethod
    def _run_status(run: dict):
        return {key: value for key, value in run.items() if key != "task"}

    async def _play(self, macro: dict, sink, run: dict):
        held = set()
        deadline = asyncio.get_running_loop().time() + self._data["settings"]["macroTimeoutSeconds"]

        def emit(key, down):
            # Track before writing: a partially failed write must still be released.
            if down:
                held.add(key)
            sink.emit(key, down)
            if not down:
                held.discard(key)

        async def pause(seconds):
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0 or seconds > remaining:
                raise TimeoutError("Macro reached its configured time limit")
            await asyncio.sleep(seconds)

        try:
            while True:
                for step in macro["steps"]:
                    await pause(0)
                    if step["type"] == "delay":
                        await pause(step["ms"] / 1000)
                    elif step["type"] == "key":
                        if step["action"] in {"down", "tap"}:
                            emit(step["key"], True)
                        if step["action"] == "tap":
                            await pause(0)
                        if step["action"] in {"up", "tap"}:
                            emit(step["key"], False)
                    else:
                        for char in step["text"]:
                            key, shifted = _text_keys(char)
                            if shifted:
                                emit("KEY_LEFTSHIFT", True)
                            emit(key, True)
                            await pause(0)
                            emit(key, False)
                            if shifted:
                                emit("KEY_LEFTSHIFT", False)
                run["iterations"] += 1
                if macro["mode"] not in {"repeat", "toggle"}:
                    run["state"] = "completed"
                    break
                for key in list(held):
                    emit(key, False)
                if run["iterations"] >= 1000:
                    raise TimeoutError("Macro reached the 1000-pass safety limit")
                await pause(0.01)
        except asyncio.CancelledError:
            run["state"] = "stopped"
        except Exception as error:
            run["state"] = "failed"
            run["error"] = str(error)
        finally:
            release_errors = []
            for key in list(held):
                try:
                    sink.emit(key, False)
                except Exception as error:
                    release_errors.append(str(error))
            try:
                sink.close()
            except Exception as error:
                release_errors.append(str(error))
            if release_errors:
                run["state"] = "failed"
                run["error"] = "; ".join([run["error"] or "", "Input cleanup: " + "; ".join(release_errors)]).strip("; ")
            run["endedAt"] = time.time()

    async def _stop_macro(self, identifier: str):
        run = self._runs.get(_identifier(identifier))
        if not run or run["task"].done():
            return False
        # Let a newly created task enter its try/finally before cancelling.
        await asyncio.sleep(0)
        run["task"].cancel()
        await run["task"]
        return True

    def _auto_status(self):
        protocol = "injected" if self.foreground_provider else (
            "unsupported" if sys.platform != "linux" else "Wayland (unsupported)" if os.environ.get("WAYLAND_DISPLAY") else "X11")
        return {"running": bool(self._auto_task and not self._auto_task.done()),
                "enabled": self._data["settings"]["autoSwitch"], "protocol": protocol,
                "foregroundExecutable": self._foreground, "lastError": self._auto_error,
                "waylandSupported": False, "luaSupported": False,
                "activeProfileId": self._data["activeProfileId"]}

    @staticmethod
    async def _xprop(*arguments):
        try:
            process = await asyncio.create_subprocess_exec("xprop", *arguments, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        except FileNotFoundError as error:
            raise AutomationError("Install xorg-xprop for X11 automatic switching") from error
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=2)
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        if process.returncode or len(stdout) > 8192:
            raise AutomationError("xprop failed: " + stderr.decode(errors="replace")[:300])
        return stdout.decode(errors="replace")

    async def _x11_foreground(self):
        root = await self._xprop("-root", "_NET_ACTIVE_WINDOW")
        window = re.search(r"window id # (0x[0-9a-fA-F]+)", root)
        if not window or int(window[1], 16) == 0:
            return None
        metadata = await self._xprop("-id", window[1], "_NET_WM_PID")
        pid = re.search(r"=\s*(\d+)\s*$", metadata)
        if not pid:
            return None
        try:
            return os.readlink(f"/proc/{int(pid[1])}/exe")
        except (OSError, ValueError):
            return None

    async def _watch(self):
        try:
            while True:
                provider = self.foreground_provider or self._x11_foreground
                executable = provider()
                if inspect.isawaitable(executable):
                    executable = await executable
                if executable is not None and not isinstance(executable, str):
                    raise AutomationError("Foreground provider must return a path or None")
                self._foreground = executable
                pending_profile = None
                async with self._lock:
                    target = next((profile for profile in self._data["profiles"]
                                   if executable and profile.get("executable") and
                                   (profile["executable"] == executable if profile["executable"].startswith("/")
                                    else profile["executable"] == executable.rsplit("/", 1)[-1])), None)
                    if target is None:
                        # Return to the desktop profile after leaving a matched game.
                        target = next((profile for profile in self._data["profiles"]
                                       if profile["id"] == "desktop" and not profile.get("executable")), None)
                    if target and target["id"] != self._last_auto_profile:
                        pending_profile = self._prepare_activation(target["id"])
                        self._last_auto_profile = target["id"]
                    elif not target:
                        self._last_auto_profile = None
                if pending_profile is not None:
                    result = await self._apply_profile(pending_profile)
                    self._auto_error = self._application_error(result["hardware"])
                await asyncio.sleep(self._data["settings"]["pollIntervalMs"] / 1000)
        except asyncio.CancelledError:
            pass
        except Exception as error:
            self._auto_error = str(error)

    async def _stop_auto(self):
        if self._auto_task and not self._auto_task.done():
            self._auto_task.cancel()
            await self._auto_task
        self._auto_task = None
        self._last_auto_profile = None

    async def close(self):
        """Release virtual keys and stop background tasks on backend shutdown."""
        async with self._lock:
            self._closing = True
            await self._stop_auto()
            for identifier in list(self._runs):
                await self._stop_macro(identifier)
        if self._apply_tasks:
            await asyncio.gather(*list(self._apply_tasks), return_exceptions=True)
