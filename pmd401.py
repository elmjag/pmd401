#!/usr/bin/env python
from typing import Iterable
import socket
import time
import tango
from tango import DevLong, AttrWriteType
from tango.server import Device, device_property, command


class Client:
    def __init__(self):
        self.sock = None

    def reconnect(self, host, port):
        if self.sock is not None:
            assert False, "disconecting not implemented"
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        # TODO handle ConnectionRefusedError exception
        print(f"connecting to {host}:{port}")
        self.sock.connect((host, port))

    def _read_line(self):
        assert self.sock is not None

    def _send(self, cmd: bytes):
        assert self.sock is not None
        self.sock.sendall(cmd)

    def _recv(self) -> bytes:
        assert self.sock is not None
        return self.sock.recv(4096)

    def get_channel_nums(self) -> Iterable[int]:
        self._send(b"X127\n")
        time.sleep(0.5)
        self._send(b"X?\n")

        data = b""
        while True:
            data += self._recv()
            if data.endswith(b"\r"):
                break

        print(f"channel query replies {data=}")
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

    def arbitrary_ask(self, message: str) -> str:
        message += "\n"
        self._send(message.encode())
        time.sleep(0.5)
        reply = self._recv()
        return reply.decode()


class PMD401(Device):
    host = device_property(dtype=str)
    port = device_property(dtype=int)

    def __init__(self, *args, **kwargs):
        # self._client is used in init_device(), thus needs to be
        # created before calling super constructor
        self._client = Client()
        super().__init__(*args, **kwargs)
        print(f"__init {args=} {kwargs=}")

    def init_device(self):
        print("INIT COMMAND!")

        # This is necessary before use the properties.
        self.get_device_properties()

        self._client.reconnect(self.host, self.port)

        for channel_num in self._client.get_channel_nums():
            print(f"channel {channel_num=}")
            self._create_channel_attributes(channel_num)

    @command(dtype_in=str, dtype_out=str)
    def ArbitraryAsk(self, message):
        return self._client.arbitrary_ask(message)

    def _create_channel_attributes(self, cn):
        """
        Create dynamic attributes for controller channel.
        """
        print(f"creating dynamic channel{cn:02}")

        attr = tango.Attr(f"channel{cn:02}_encoder", DevLong, AttrWriteType.READ,)
        self.add_attribute(attr, self._get_channel_encoder)

    def _get_channel_encoder(self, attr):
        print(f"_get_channel_encoder {attr=}")
        attr.set_value(2)


PMD401.run_server()
