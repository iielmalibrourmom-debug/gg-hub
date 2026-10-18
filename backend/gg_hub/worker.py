"""Bounded JSON-lines RPC worker used by Electron over stdin/stdout."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys

from .hardware import HardwareError, HardwareService

MAX_LINE = 1024 * 1024
MAX_CONCURRENT_REQUESTS = 8
AUTOMATION_METHODS = {"profiles.list", "profiles.save", "profiles.delete", "profiles.activate", "profiles.export", "profiles.import", "settings.get", "settings.update", "macros.list", "macros.save", "macros.delete", "macros.run", "macros.stop", "automation.status", "automation.start", "automation.stop"}


def config_directory():
    explicit = os.environ.get("GG_HUB_CONFIG_DIR")
    if explicit:
        return Path(explicit).expanduser()
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "gg-hub"


class Worker:
    def __init__(self):
        self.hardware = HardwareService()
        self.automation = None
        try:
            from .automation import AutomationService
            self.automation = AutomationService(config_directory())
            self.automation.apply_callback = self.apply_device_settings
        except ImportError:
            pass

    async def apply_device_settings(self, settings):
        if not isinstance(settings, dict) or len(settings) > 32:
            raise HardwareError("INVALID_PARAMS", "deviceSettings must map up to 32 connected device IDs to settings.")
        results = {}
        deadline = asyncio.get_running_loop().time() + 55
        for identifier, values in settings.items():
            if not isinstance(values, dict):
                raise HardwareError("INVALID_PARAMS", "Each device's settings must be an object.")
            try:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    results[identifier] = {"applied": False, "error": {"code": "TIMEOUT", "message": "Profile hardware application exceeded its total 55 second budget; this device was not attempted."}}
                    continue
                results[identifier] = await asyncio.wait_for(self.hardware.configure({**values, "deviceId": identifier}), remaining)
            except asyncio.TimeoutError:
                results[identifier] = {"applied": False, "error": {"code": "WRITE_STATE_UNKNOWN", "message": "Profile hardware application exceeded its total 55 second budget; the last device state is unknown."}}
            except HardwareError as error:
                results[identifier] = {"applied": False, "error": {"code": error.code, "message": error.message}}
        return results

    async def request(self, request):
        identifier = request.get("id") if isinstance(request, dict) else None
        try:
            if not isinstance(request, dict) or not isinstance(request.get("method"), str):
                raise HardwareError("INVALID_REQUEST", "A request requires id, method and object params.")
            if isinstance(identifier, (dict, list, bool)) or (identifier is not None and not isinstance(identifier, (str, int))):
                raise HardwareError("INVALID_REQUEST", "id must be a string, integer or null.")
            params = request.get("params", {})
            if not isinstance(params, dict):
                raise HardwareError("INVALID_PARAMS", "params must be an object.")
            method = request["method"]
            if method in ("hardware.status", "hardware.devices", "hardware.configure"):
                result = await self.hardware.dispatch(method, params)
            elif method in AUTOMATION_METHODS and self.automation:
                result = await self.automation.dispatch(method, params)
            else:
                raise HardwareError("METHOD_NOT_FOUND", "Unknown RPC method.")
            return {"id": identifier, "result": result}
        except HardwareError as error:
            return {"id": identifier, "error": {"code": error.code, "message": error.message}}
        except Exception as error:
            # AutomationService uses its own structured error type. Never expose
            # arbitrary tracebacks, device identifiers or macro contents.
            code = getattr(error, "code", None)
            message = getattr(error, "message", None)
            if error.__class__.__name__ == "AutomationError":
                return {"id": identifier, "error": {"code": "INVALID_PARAMS", "message": str(error)}}
            if isinstance(code, (str, int)) and isinstance(message, str):
                return {"id": identifier, "error": {"code": code, "message": message}}
            return {"id": identifier, "error": {"code": "INTERNAL_ERROR", "message": "The backend could not complete this request."}}


async def main():
    worker = Worker()
    pending = set()

    def output(response):
        print(json.dumps(response, ensure_ascii=True, allow_nan=False), flush=True)

    async def respond(request):
        output(await worker.request(request))

    try:
        while True:
            # Requests are correlated by id, so fast operations (especially
            # macros.stop) may reply while discovery waits for device I/O.
            line = await asyncio.to_thread(sys.stdin.buffer.readline, MAX_LINE + 1)
            if not line:
                break
            if len(line) > MAX_LINE:
                while line and not line.endswith(b"\n"):
                    line = await asyncio.to_thread(sys.stdin.buffer.readline, MAX_LINE + 1)
                response = {"id": None, "error": {"code": "REQUEST_TOO_LARGE", "message": "RPC requests are limited to 1 MiB."}}
            else:
                try:
                    request = json.loads(line, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON")))
                    done = {task for task in pending if task.done()}
                    for task in done:
                        task.result()
                    pending.difference_update(done)
                    priority = isinstance(request, dict) and request.get("method") == "macros.stop"
                    if len(pending) >= MAX_CONCURRENT_REQUESTS + (2 if priority else 0):
                        identifier = request.get("id") if isinstance(request, dict) else None
                        output({"id": identifier, "error": {"code": "BACKEND_BUSY", "message": "The backend is busy; wait for the current operation, then retry."}})
                        continue
                    pending.add(asyncio.create_task(respond(request)))
                    # Reap finished tasks without keeping results indefinitely.
                    done = {task for task in pending if task.done()}
                    for task in done:
                        task.result()
                    pending.difference_update(done)
                    continue
                except (ValueError, UnicodeError, RecursionError):
                    response = {"id": None, "error": {"code": "PARSE_ERROR", "message": "Invalid JSON request."}}
            output(response)
        # Release software macro keys before waiting for slow hardware requests.
        if worker.automation:
            await worker.automation.close()
        if pending:
            await asyncio.gather(*pending)
    finally:
        for task in pending:
            if not task.done():
                task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        if worker.automation:
            await worker.automation.close()
        close = getattr(worker.hardware.transport, "close", None)
        if close:
            close()


if __name__ == "__main__":
    asyncio.run(main())
