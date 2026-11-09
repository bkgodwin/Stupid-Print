"""Discover BlueZ devices and open a Serial Port Profile stream without a tty."""

import asyncio
import os
import select
import socket
import threading
import time
from contextlib import asynccontextmanager, contextmanager, suppress
from dataclasses import dataclass

from dbus_fast import BusType, Message, MessageType, Variant


BLUEZ = "org.bluez"
ADAPTER = BLUEZ + ".Adapter1"
DEVICE = BLUEZ + ".Device1"
MANAGER = BLUEZ + ".ProfileManager1"
PROFILE = BLUEZ + ".Profile1"
PROFILE_PATH = "/org/stupidprint/SerialPort"
SPP = "00001101-0000-1000-8000-00805f9b34fb"
SCAN_SECONDS = 4


class BluetoothError(OSError):
    pass


@dataclass(frozen=True)
class BluetoothDevice:
    path: str
    address: str
    name: str
    alias: str
    paired: bool
    powered: bool
    serial_port: bool
    classic: bool


def _value(properties, key, default=None):
    return properties[key].value if key in properties else default


def _inventory(objects):
    adapters = {path: _value(interfaces[ADAPTER], "Powered", False)
                for path, interfaces in objects.items() if ADAPTER in interfaces}
    devices = []
    for path, interfaces in objects.items():
        if DEVICE not in interfaces:
            continue
        props = interfaces[DEVICE]
        address = _value(props, "Address")
        if not address:
            continue
        devices.append(BluetoothDevice(
            path, address.upper(), _value(props, "Name", ""), _value(props, "Alias", ""),
            _value(props, "Paired", False) or _value(props, "Bonded", False),
            adapters.get(_value(props, "Adapter"), False),
            any(uuid.lower() == SPP for uuid in _value(props, "UUIDs", [])),
            _value(props, "AddressType") != "random",
        ))
    return adapters, devices


@asynccontextmanager
async def _system_bus(*, receive_fds=False):
    from dbus_fast.aio import MessageBus

    bus = None
    try:
        try:
            bus = MessageBus(bus_type=BusType.SYSTEM, negotiate_unix_fd=receive_fds)
            await asyncio.wait_for(bus.connect(), 3)
        except (OSError, ValueError, EOFError, asyncio.TimeoutError) as exc:
            raise BluetoothError("Linux Bluetooth is unavailable. Check Bluetooth in system settings.") from exc
        yield bus
    finally:
        if bus is not None:
            bus.disconnect()
            with suppress(OSError, EOFError, asyncio.TimeoutError):
                await asyncio.wait_for(bus.wait_for_disconnect(), 1)


async def _call(bus, path, interface, member, signature="", body=None, *, timeout=3):
    request = Message(
        destination=BLUEZ, path=path, interface=interface, member=member,
        signature=signature, body=body or [],
    )
    try:
        reply = await asyncio.wait_for(bus.call(request), timeout)
    except asyncio.TimeoutError as exc:
        raise TimeoutError(f"{member} timed out") from exc
    except (ConnectionError, EOFError) as exc:
        raise BluetoothError("Lost the connection to Linux Bluetooth. Click Find printers to try again.") from exc
    if reply.message_type == MessageType.ERROR:
        if reply.error_name in ("org.freedesktop.DBus.Error.ServiceUnknown",
                                "org.freedesktop.DBus.Error.NameHasNoOwner"):
            raise BluetoothError("Linux Bluetooth service (BlueZ) is unavailable. Check Bluetooth in system settings.")
        detail = str(reply.body[0]) if reply.body else reply.error_name
        raise BluetoothError(detail)
    return reply


async def _managed_objects(bus):
    return await _call(bus, "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects")


async def _discover(scan):
    async with _system_bus() as bus:
        reply = await _managed_objects(bus)
        adapters, devices = _inventory(reply.body[0])
        powered = [path for path, enabled in adapters.items() if enabled]
        if not adapters:
            return devices, "Linux found no Bluetooth adapter. Check that your adapter is connected."
        if not powered:
            return devices, "Bluetooth is off. Turn it on in Linux Bluetooth settings, then click Find printers."
        if not scan:
            return devices, ""

        scanning = []
        try:
            for path in powered:
                try:
                    await _call(bus, path, ADAPTER, "SetDiscoveryFilter", "a{sv}", [{"Transport": Variant("s", "bredr")}])
                    await _call(bus, path, ADAPTER, "StartDiscovery")
                    scanning.append(path)
                except OSError:
                    # Paired printers remain usable if an adapter cannot scan.
                    continue
            if not scanning:
                return devices, "Could not scan nearby. Pair the printer in Linux Bluetooth settings, then refresh."
            await asyncio.sleep(SCAN_SECONDS)
            try:
                reply = await _managed_objects(bus)
            except OSError:
                return devices, "The nearby scan could not finish. Previously found printers are still listed."
            return _inventory(reply.body[0])[1], ""
        finally:
            for path in scanning:
                with suppress(OSError):
                    await _call(bus, path, ADAPTER, "StopDiscovery")


def discover(scan=False):
    try:
        return asyncio.run(_discover(scan))
    except TimeoutError:
        return [], "Linux Bluetooth did not respond. Check Bluetooth in system settings and try again."
    except OSError as exc:
        return [], str(exc)


class _RfcommStream:
    """Give the printer drivers bounded, serial-like reads and writes."""

    def __init__(self, connection):
        self.socket = connection
        self.socket.settimeout(.15)

    def read(self, size):
        try:
            data = self.socket.recv(size)
        except TimeoutError:
            return b""
        if not data:
            raise BluetoothError("The printer closed its Bluetooth connection.")
        return data

    def write(self, data):
        self.socket.settimeout(3)
        try:
            self.socket.sendall(data)
        finally:
            self.socket.settimeout(.15)
        return len(data)

    def reset_input_buffer(self):
        deadline = time.monotonic() + .15
        while time.monotonic() < deadline and select.select([self.socket], [], [], 0)[0]:
            self.read(4096)


@asynccontextmanager
async def _rfcomm_session(address):
    async with _system_bus(receive_fds=True) as bus:
        reply = await _managed_objects(bus)
        _, devices = _inventory(reply.body[0])
        candidates = [device for device in devices if device.address == address]
        if not candidates or not any(device.paired for device in candidates):
            raise BluetoothError("Pair this printer in Linux Bluetooth settings, then click Find printers.")
        usable = [device for device in candidates if device.paired and device.powered]
        if not usable:
            raise BluetoothError("Turn on Bluetooth in Linux Bluetooth settings.")
        usable = [device for device in usable if device.classic]
        if not usable:
            raise BluetoothError("Pair the printer’s Bluetooth Classic entry in Linux Bluetooth settings.")
        device = max(usable, key=lambda candidate: candidate.serial_port)
        owner = reply.sender
        connection = None
        received = asyncio.Event()

        def handle(message):
            nonlocal connection
            if (message.message_type != MessageType.METHOD_CALL or message.path != PROFILE_PATH
                    or message.interface != PROFILE):
                return None
            fds = list(message.unix_fds)
            try:
                if message.sender != owner:
                    return Message.new_error(message, "org.freedesktop.DBus.Error.AccessDenied", "Expected BlueZ")
                if (message.member == "NewConnection" and message.signature == "oha{sv}"
                        and message.body[0] == device.path and message.body[1] == 0
                        and len(fds) == 1 and not received.is_set()):
                    connection = socket.socket(fileno=fds[0])
                    fds.clear()  # The socket owns the descriptor.
                    received.set()
                elif message.member == "Release" or (message.member == "RequestDisconnection"
                                                      and message.body == [device.path]):
                    if connection is not None:
                        connection.close()
                        connection = None
                else:
                    return Message.new_error(message, BLUEZ + ".Error.Rejected", "Unexpected printer connection")
                return Message.new_method_return(message)
            finally:
                for fd in fds:
                    os.close(fd)

        bus.add_message_handler(handle)
        registered = False
        try:
            options = {"Name": Variant("s", "Stupid Print"), "Role": Variant("s", "client"),
                       "RequireAuthentication": Variant("b", True),
                       "AutoConnect": Variant("b", False)}
            try:
                await _call(bus, "/org/bluez", MANAGER, "RegisterProfile", "osa{sv}", [PROFILE_PATH, SPP, options])
            except BluetoothError as exc:
                if "uuid already registered" in str(exc).lower():
                    raise BluetoothError("Another app is using the Bluetooth serial profile. Close it and try again, "
                                         "or select an existing serial port.") from exc
                raise
            registered = True
            try:
                await _call(bus, device.path, DEVICE, "ConnectProfile", "s", [SPP], timeout=15)
                await asyncio.wait_for(received.wait(), 3)
            except (OSError, asyncio.TimeoutError) as exc:
                detail = str(exc) or "connection timed out"
                if "profile-unavailable" in detail:
                    raise BluetoothError("BlueZ could not find the printer’s serial service. "
                                         "Pair the Bluetooth Classic entry in Linux Bluetooth settings.") from exc
                raise BluetoothError(f"Could not open Bluetooth serial ({detail}). "
                                     "Wake the printer, close its phone app, and check again.") from exc
            if connection is None:
                raise BluetoothError("The printer disconnected before the Bluetooth serial connection was ready.")
            yield _RfcommStream(connection)
        finally:
            if connection is not None:
                connection.close()
            if registered:
                with suppress(OSError, EOFError):
                    await _call(bus, "/org/bluez", MANAGER, "UnregisterProfile", "o", [PROFILE_PATH])
            bus.remove_message_handler(handle)


@contextmanager
def open_rfcomm(address):
    # BlueZ can request disconnection while the printer worker is doing synchronous I/O.
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    session = _rfcomm_session(address)
    thread.start()
    try:
        stream = asyncio.run_coroutine_threadsafe(session.__aenter__(), loop).result()
        try:
            yield stream
        finally:
            asyncio.run_coroutine_threadsafe(session.__aexit__(None, None, None), loop).result()
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join()
        loop.close()
