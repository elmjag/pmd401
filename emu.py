#!/usr/bin/env python
import time
from typing import Optional, List
import re
import socket
from threading import Thread, Lock
from dataclasses import dataclass

HOST = "127.0.0.1"
PORT = 4001

CHANNELS = 3


class Channel:
    def __init__(self, encoder_position: int, target_position: int):
        self.encoder_position = encoder_position
        self.target_position = target_position
        self._lock = Lock()

    def __enter__(self):
        self._lock.acquire()
        return self

    def __exit__(self, type, value, traceback):
        self._lock.release()


@dataclass
class Controller:
    channels: List[Channel]


@dataclass
class Command:
    channel: str
    name: str
    argument: Optional[str]
    suppress_response: bool


COMMAND_RE = re.compile(r"^X(\?|\d*)([ETY].*)?([;\n\r])$")


def motor_ticker(controller: Controller):
    def move_motor(channel):
        if channel.target_position == channel.encoder_position:
            # at target position, no need to move anything
            return
        delta = 1 if channel.target_position > channel.encoder_position else -1
        channel.encoder_position += delta

    while True:
        for channel in controller.channels:
            move_motor(channel)
        time.sleep(1)


def _parse_command(command) -> Optional[Command]:
    print(f"parse {command=}")
    res = COMMAND_RE.match(command)
    if res is None:
        print(f"no match for {command=}")
        return None

    channel, command, delimiter = res.groups()

    argument = None
    if command is not None and "," in command:
        command, argument = command.split(",")

    suppress_response = delimiter == ";"

    return Command(channel, command, argument, suppress_response)


def _read_command_str(sock) -> str:
    def endswith_delimiter():
        if line.endswith(b"\n"):
            return True

        if line.endswith(b"\r"):
            return True

        if line.endswith(b";"):
            return True

        return False

    line = b""
    while not endswith_delimiter():
        res = sock.recv(4096)
        if res == b"":
            break

        line += res

    return line.decode()


def _list_channels_cmd():
    def gen_channels():
        for n in range(CHANNELS):
            yield f"X{n}\n"

    reply = "".join(gen_channels())
    return reply.encode()


def _target_cmd(command: Command, controller: Controller) -> bytes:
    if len(command.name) == 1:
        # this is 'read target position' version of the command
        with controller.channels[int(command.channel)] as channel:
            position = channel.target_position

        return f"X{command.channel}T:{position}\r".encode()

    new_target_pos = int(command.name[1:])
    with controller.channels[int(command.channel)] as channel:
        old_position = channel.target_position
        channel.target_position = new_target_pos

    return f"X{command.channel}T:{old_position}\r".encode()


def _encode_position_cmd(command: Command, controller: Controller):
    with controller.channels[int(command.channel)] as channel:
        position = channel.encoder_position

    return f"X{command.channel}E:{position}\r".encode()


def _config_encoder_cmd(command: Command):
    reply = f"X{command.channel}Y13"

    if command.argument is None:
        reply += ":1, Quad_32\r"
    else:
        reply += f",{command.argument}\n"

    return reply.encode()


def _handle_command(connection, line, controller: Controller):
    command = _parse_command(line)
    print(f"{command=}")

    if command is None:
        reply = b"parse error\n"
    elif command.channel == "?":
        reply = b"X?:PMD401 V18-emu\r"
    elif command.channel == "127" and command.name is None:
        reply = _list_channels_cmd()
    elif command.name[0] == "T":
        reply = _target_cmd(command, controller)
    elif command.name == "E":
        reply = _encode_position_cmd(command, controller)
    elif command.name == "Y13":
        reply = _config_encoder_cmd(command)
    else:
        reply = b"wat?\n"

    if command is None or (not command.suppress_response):
        connection.sendall(reply)


def serve_client(connection, client, controller: Controller):
    try:
        while (line := _read_command_str(connection)) != "":
            _handle_command(connection, line, controller)
    except BrokenPipeError:
        print("connection closed, I guess")

    connection.shutdown(socket.SHUT_WR)
    connection.close()

    print(f"bye {client}")


def get_controller():
    def get_channels():
        for n in range(CHANNELS):
            yield Channel(0, 0)

    return Controller(list(get_channels()))


def main():
    controller = get_controller()

    Thread(target=motor_ticker, args=[controller]).start()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((HOST, PORT))
    sock.listen()

    while True:
        print(f"Waiting for connection on {HOST}:{PORT}")
        connection, client = sock.accept()
        Thread(target=serve_client, args=[connection, client, controller]).start()


main()
