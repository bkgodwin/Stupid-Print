"""Exercise the BlueZ contract, including a real D-Bus Unix descriptor handoff."""

import asyncio
import os
import shutil
import socket
import subprocess
import threading
import unittest
from concurrent.futures import Future
from contextlib import contextmanager
from unittest.mock import patch

try:
    from stupid_print import linux_bluetooth as bluez
except ImportError:
    bluez = None  # dbus-fast is a Linux-only runtime dependency.


ADDRESS = "00:11:22:33:44:55"
P21_ADDRESS = "AA:BB:CC:DD:EE:FF"
ADAPTER_PATH = "/org/bluez/hci0"
DEVICE_PATH = ADAPTER_PATH + "/dev_00_11_22_33_44_55"
NEARBY_PATH = ADAPTER_PATH + "/dev_AA_BB_CC_DD_EE_FF"


def objects(powered=True, nearby=False, p21_paired=False):
    variant = bluez.Variant
    result = {
        ADAPTER_PATH: {bluez.ADAPTER: {"Powered": variant("b", powered)}},
        DEVICE_PATH: {bluez.DEVICE: {
            "Address": variant("s", ADDRESS), "Adapter": variant("o", ADAPTER_PATH),
            "Name": variant("s", "D30N"), "Alias": variant("s", "Office printer"),
            "Paired": variant("b", True), "UUIDs": variant("as", [bluez.SPP.upper()]),
        }},
    }
    if nearby:
        result[NEARBY_PATH] = {bluez.DEVICE: {
            "Address": variant("s", P21_ADDRESS), "Adapter": variant("o", ADAPTER_PATH),
            "Name": variant("s", "P21"), "Paired": variant("b", p21_paired),
        }}
    return result


@unittest.skipUnless(bluez, "requires dbus-fast")
class InventoryTests(unittest.TestCase):
    def test_inventory_keeps_alias_pairing_and_adapter_state(self):
        adapters, devices = bluez._inventory(objects(powered=False, nearby=True))
        self.assertEqual(adapters, {ADAPTER_PATH: False})
        paired, nearby = devices
        self.assertEqual((paired.name, paired.alias, paired.address), ("D30N", "Office printer", ADDRESS))
        self.assertTrue(paired.paired)
        self.assertTrue(paired.serial_port)
        self.assertFalse(paired.powered)
        self.assertFalse(nearby.paired)

    def test_only_p21_falls_back_to_its_known_channel_when_spp_is_missing(self):
        error = bluez.SerialProfileUnavailable("No serial service")
        with (patch.object(bluez, "_bluez_rfcomm", side_effect=error),
              patch.object(socket, "AF_BLUETOOTH", 31, create=True),
              patch.object(socket, "BTPROTO_RFCOMM", 3, create=True),
              patch.object(socket, "socket") as make_socket):
            with self.assertRaises(bluez.SerialProfileUnavailable), bluez.open_rfcomm(ADDRESS):
                self.fail("A generic printer should not try a guessed channel")
            make_socket.assert_not_called()
            with bluez.open_rfcomm(P21_ADDRESS, p21=True) as stream:
                stream.socket.connect.assert_called_once_with((P21_ADDRESS, 1))


@contextmanager
def simulated_bluez(address, *, powered=True, fail_connect=False):
    from dbus_fast.aio import MessageBus

    ready = Future()
    calls = []

    async def serve():
        bus = await MessageBus(bus_address=address, negotiate_unix_fd=True).connect()
        await bus.request_name(bluez.BLUEZ)
        loop = asyncio.get_running_loop()
        stop = asyncio.Event()
        tasks = []
        found_p21 = False
        p21_paired = False
        profile = ""

        async def connect(request):
            client, peer = socket.socketpair()
            with client, peer:
                response = await bus.call(bluez.Message(
                    destination=request.sender, path=profile, interface=bluez.PROFILE, member="NewConnection",
                    signature="oha{sv}", body=[DEVICE_PATH, 0, {}], unix_fds=[client.fileno()],
                ))
                if response.message_type != bluez.MessageType.METHOD_RETURN:
                    await bus.send(bluez.Message.new_error(request, bluez.BLUEZ + ".Error.Failed",
                                                           "Client rejected the socket"))
                    return
                await bus.send(bluez.Message.new_method_return(request))
                peer.setblocking(False)
                data = await loop.sock_recv(peer, 64)
                if data == b"status":
                    await loop.sock_sendall(peer, b"ready")

        def handle(request):
            nonlocal found_p21, p21_paired, profile
            if request.message_type != bluez.MessageType.METHOD_CALL:
                return None
            calls.append(request.member)
            if request.member == "GetManagedObjects":
                return bluez.Message.new_method_return(request, "a{oa{sa{sv}}}",
                                                       [objects(powered, found_p21, p21_paired)])
            if request.member == "StartDiscovery":
                found_p21 = True
            elif request.member == "Pair" and request.path == NEARBY_PATH:
                p21_paired = True
            elif request.member == "RegisterProfile":
                profile, uuid, options = request.body
                if uuid != bluez.SPP or options["Role"].value != "client":
                    return bluez.Message.new_error(request, bluez.BLUEZ + ".Error.InvalidArguments", "Expected SPP")
            elif request.member == "ConnectProfile":
                if fail_connect:
                    return bluez.Message.new_error(request, bluez.BLUEZ + ".Error.Failed", "Connection refused")
                tasks.append(asyncio.create_task(connect(request)))
                return True
            return bluez.Message.new_method_return(request)

        bus.add_message_handler(handle)
        ready.set_result((loop, stop))
        try:
            await stop.wait()
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            bus.disconnect()
            await bus.wait_for_disconnect()

    def run():
        try:
            asyncio.run(serve())
        except Exception as exc:
            if not ready.done():
                ready.set_exception(exc)
            else:
                raise

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    loop, stop = ready.result(timeout=5)
    try:
        yield calls
    finally:
        loop.call_soon_threadsafe(stop.set)
        worker.join(timeout=5)


@unittest.skipUnless(bluez and shutil.which("dbus-daemon") and hasattr(socket, "SCM_RIGHTS"),
                     "requires Linux D-Bus and Unix descriptor passing")
class BluezIntegrationTests(unittest.TestCase):
    def setUp(self):
        daemon = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=1"],
                                  stdout=subprocess.PIPE, text=True)
        self.addCleanup(daemon.stdout.close)
        self.addCleanup(daemon.wait, 5)
        self.addCleanup(daemon.terminate)
        self.address = daemon.stdout.readline().strip()
        self.assertTrue(self.address, "The test D-Bus daemon did not start")
        env = patch.dict(os.environ, DBUS_SYSTEM_BUS_ADDRESS=self.address)
        env.start()
        self.addCleanup(env.stop)

    def test_discovery_and_real_socket_handoff(self):
        with simulated_bluez(self.address) as calls, patch.object(bluez, "SCAN_SECONDS", .02):
            devices, note = bluez.discover()
            self.assertEqual(note, "")
            self.assertEqual([device.name for device in devices], ["D30N"])
            nearby, note = bluez.discover(scan=True)
            self.assertEqual(note, "")
            self.assertEqual([device.name for device in nearby], ["D30N", "P21"])
            self.assertIn("StopDiscovery", calls)
            bluez.pair(P21_ADDRESS)
            self.assertTrue(bluez.discover()[0][1].paired)
            self.assertIn("Pair", calls)
            with bluez.open_rfcomm(ADDRESS) as stream:
                self.assertEqual(stream.write(b"status"), 6)
                self.assertEqual(stream.read(8), b"ready")
            self.assertEqual(calls[-3:], ["RegisterProfile", "ConnectProfile", "UnregisterProfile"])

    def test_adapter_off_and_connection_failure_have_actionable_messages(self):
        with simulated_bluez(self.address, powered=False) as calls:
            _, note = bluez.discover(scan=True)
            self.assertIn("Bluetooth is off", note)
            self.assertNotIn("StartDiscovery", calls)
        with simulated_bluez(self.address, fail_connect=True) as calls:
            with self.assertRaisesRegex(OSError, "Connection refused.*Wake the printer"):
                with bluez.open_rfcomm(ADDRESS):
                    self.fail("An unavailable printer should not return a stream")
            self.assertEqual(calls[-1], "UnregisterProfile")
