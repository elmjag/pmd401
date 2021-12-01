#!/usr/bin/env python3
from typing import Iterable
import atexit
import time
import tango
from tango import DevLong, AttrWriteType
from tango.server import Device, device_property, command
from lazy_sock import LazyTCPSocket


TCP_DISCONNECT_TIMEOUT = 60


class Client:
    # Y13 command's value for configuring 'BiSS 32-bit' encoder mode
    Y13_BiSS_32bit = "6"

    def __init__(self, host, port):
        self.sock = LazyTCPSocket(host, port, TCP_DISCONNECT_TIMEOUT)

    def teardown(self):
        self.sock.teardown()

    def _send(self, cmd: bytes):
        assert self.sock is not None
        self.sock.sendall(cmd)

    def _recv(self) -> bytes:
        assert self.sock is not None
        reply = self.sock.recv(4096)
        return reply

    def _recv_until(self, end: bytes) -> bytes:
        assert self.sock is not None
        data = b""
        while True:
            data += self._recv()
            if data.endswith(end):
                break

        return data

    @staticmethod
    def _get_command_prefix(channel_num: int) -> str:
        return f"X{channel_num}"

    def get_channel_nums(self) -> Iterable[int]:
        self._send(b"X127\n")
        time.sleep(0.5)
        self._send(b"X?\n")

        data = self._recv_until(b"\r")

        for line in data.split(b"\n"):
            if line.startswith(b"X?:"):
                # this is the 'status command' reply part,
                # we are done parsing available channels
                break

            if not line.startswith(b"X"):
                # TODO: handle properly
                assert False, f"unexpected reply line {line}"

            channel_num = int(line[1:].decode())
            yield channel_num

    def configure_encoder(self, channel_num: int):
        #
        # hard-code 'BiSS 32-bit' encoder mode for now,
        # this is what is used at NanoMAX currently
        #
        cmd = f"X{channel_num}Y13,{self.Y13_BiSS_32bit};"
        self._send(cmd.encode())

    def get_target_position(self, channel_num: int) -> int:
        cmd_prefix = self._get_command_prefix(channel_num)
        cmd = f"{cmd_prefix}T\n"
        self._send(cmd.encode())

        reply = self._recv_until(b"\r")
        reply = reply[len(cmd_prefix) + 2 : -1]

        return int(reply.decode())

    def set_target_position(self, channel_num: int, position: int):
        cmd_prefix = self._get_command_prefix(channel_num)
        cmd = f"{cmd_prefix}T{position};"
        self._send(cmd.encode())

    def get_encoder_position(self, channel_num: int) -> int:
        cmd_prefix = self._get_command_prefix(channel_num)
        cmd = f"{cmd_prefix}E\n"
        self._send(cmd.encode())

        reply = self._recv_until(b"\r")
        reply = reply[len(cmd_prefix) + 2 : -1]

        return int(reply.decode())

    def stop_movement(self, channel_num: int):
        cmd = f"{self._get_command_prefix(channel_num)}S;"
        self._send(cmd.encode())

    def arbitrary_ask(self, message: str) -> str:
        message += "\n"
        self._send(message.encode())
        time.sleep(0.5)
        reply = self._recv()
        return reply.decode()

    def arbitrary_send(self, message: str):
        data = f"{message.strip()};"
        self._send(data.encode())


class PMD401(Device):
    host = device_property(dtype=str)
    port = device_property(dtype=int)

    def __init__(self, *args, **kwargs):
        # create fields before calling super constructor,
        # as they are accessed in init_device()
        # which will be invoked by the super constructor
        self._client = None
        self._channels = []
        super().__init__(*args, **kwargs)
        atexit.register(self._reset)

    def _reset(self):
        if self._client:
            self._client.teardown()

    def init_device(self):
        print("init_device()")
        self._reset()
        self._check_properties()

        self._client = Client(self.host, self.port)
        self._channels = list(self._client.get_channel_nums())

        for channel_num in self._channels:
            self._client.configure_encoder(channel_num)
            self._create_channel_attributes(channel_num)

    def _check_properties(self):
        # This is necessary before use the properties.
        self.get_device_properties()

        if self.host is None:
            assert False, "no 'host' property specified"

        if self.port is None:
            assert False, "no 'port' property specified"

    def _create_channel_attributes(self, channel_num: int):
        """
        Create dynamic attributes for controller channel.
        """
        print(f"creating dynamic channel{channel_num:02}")

        attr = tango.Attr(
            f"channel{channel_num:02}_position", DevLong, AttrWriteType.READ_WRITE,
        )
        self.add_attribute(attr, self._get_channel_position, self._set_channel_position)

        attr = tango.Attr(
            f"channel{channel_num:02}_encoder", DevLong, AttrWriteType.READ,
        )
        self.add_attribute(attr, self._get_channel_encoder)

    @staticmethod
    def _get_attr_channel_num(attr) -> int:
        """
        parse channel number from Attribute's name

        e.g. 'channel02_encoder' will return 2
        """
        attr_name = attr.get_name()
        attr_prefix_len = len("channel")

        num = attr_name[attr_prefix_len : attr_prefix_len + 2]
        return int(num)

    #
    # Attributes
    #

    def _get_channel_position(self, attr):
        channel_num = self._get_attr_channel_num(attr)
        attr.set_value(self._client.get_target_position(channel_num))

    def _set_channel_position(self, attr):
        channel_num = self._get_attr_channel_num(attr)
        target_pos = attr.get_write_value()
        self._client.set_target_position(channel_num, target_pos)

    def _get_channel_encoder(self, attr):
        channel_num = self._get_attr_channel_num(attr)
        attr.set_value(self._client.get_encoder_position(channel_num))

    #
    # Commands
    #

    @command(dtype_in=str, dtype_out=str)
    def ArbitraryAsk(self, message):
        return self._client.arbitrary_ask(message)

    @command(dtype_in=str)
    def ArbitrarySend(self, message):
        self._client.arbitrary_send(message)

    @command
    def StopAll(self):
        for channel_num in self._channels:
            self._client.stop_movement(channel_num)


if __name__ == "__main__":
    PMD401.run_server()
