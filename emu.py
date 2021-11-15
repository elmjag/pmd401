#!/usr/bin/env python
import re
import socket
from threading import Thread

CHANNELS = 4
HOST = "127.0.0.1"
PORT = 4001


COMMAND_RE = re.compile(r"^X(\?|\d*)(.*)")


def _parse_command(command):
    print(f"parse {command=}")
    res = COMMAND_RE.match(command)
    if res is None:
        print(f"no match for {command=}")
        return

    channel, command = res.groups()
    print(f"{channel=} {command=}")

    return channel, command


def _read_line(sock) -> str:
    line = b""
    while not line.endswith(b"\n"):
        res = sock.recv(4096)
        if res == b"":
            break

        line += res

    return line.decode()


def _list_channels_cmd():
    def gen_channels():
        for n in range(CHANNELS):
            yield f"X{n}\n"

    #        yield f"Yhaha\n"

    reply = "".join(gen_channels())
    return reply.encode()


def _encode_position_cmd(channel):
    return f"X{channel}E:0\r".encode()


def _handle_command(line):
    res = _parse_command(line)
    if res is None:
        return b"parse error\n"

    channel, command = res

    if channel == "?":
        return b"X?:PMD401 V18-emu\r"

    if channel == "127" and command == "":
        return _list_channels_cmd()

    if command == "E":
        return _encode_position_cmd(channel)

    return b"wat?\n"

    # command = command.decode()
    #
    # if command == b"X?":
    #     return b"X?:PMD401 V18-emu\r"
    #
    # if command == b"X127":
    #     return _list_channels_cmd()
    #
    # return b"wat?"


def serve_client(connection, client):
    try:
        while (line := _read_line(connection)) != "":
            print(f"{line=}")
            reply = _handle_command(line[:-1])
            connection.sendall(reply)
    except BrokenPipeError:
        print("connection closed, I guess")

    print(f"bye {client}")


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((HOST, PORT))
    sock.listen()

    while True:
        print(f"Waiting for connection on {HOST}:{PORT}")
        connection, client = sock.accept()
        Thread(target=serve_client, args=[connection, client]).start()


main()
