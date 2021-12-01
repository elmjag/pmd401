from typing import Callable
import socket
from time import monotonic
from contextlib import contextmanager
from threading import Lock, Thread, Event


def _log_msg(msg: str):
    print(f"{monotonic():0.2f}: TCP {msg}")


class _DelayedCallback:
    """
    Will call 'callback' after the specified delay. The callback can
    specify if it should be called again, by returning a new delay.

    The call will be made from a different thread.
    """

    def __init__(self, callback: Callable, initial_delay: float):
        """
        callback: a callable should return either a float or None
          If float is returned, the callback will be called again, after waiting the
            specified amount of seconds.
          If None is returned, callback will not be called anymore, and this
            object dies.
        initial_delay: time to wait, in seconds, before calling first time
        """
        self._canceled = Event()
        self._thread = Thread(
            target=self._run,
            args=(callback, initial_delay),
            daemon=True,  # join not required
        )
        self._thread.start()

    def _run(self, callback, initial_delay):
        timeout = initial_delay

        while not self._canceled.wait(timeout):
            timeout = callback()
            if timeout is None:
                return

    def cancel(self):
        """
        Cancel pending callback. After call to this method, this object dies.
        """
        self._canceled.set()
        self._thread.join()


class LazyTCPSocket:
    """
    A wrapper around a TCP socket.

    Automatically opens a TCP socket when needed, and closes it after a time of
    inactivity.

    Use sendall() for writing to the socket, recv() to read from the socket.
    The connection will be (re)opended and closed automatically.

    Use teardown() when the socket is no longer needed, to allow for the object to
    cleanly shut down it's internal machinery.
    """

    def __init__(self, host: str, port: int, disconnect_timeout: int):
        self._host = host
        self._port = port
        self._disconnect_timeout = disconnect_timeout

        self._disconnect_at = None
        self._sock = None
        self._sock_lock = Lock()
        self._delayed_cb = None

    def _connect(self):
        _log_msg(f"connecting to {self._host}:{self._port}")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        # TODO handle ConnectionRefusedError exception
        sock.connect((self._host, self._port))

        # we have successfully connected, save the TCP socket object
        self._sock = sock

        self._delayed_cb = _DelayedCallback(
            self._maybe_disconnect, self._disconnect_timeout
        )

    def _disconnect(self):
        _log_msg(f"disconnecting from {self._host}:{self._port}")
        self._sock.close()
        self._sock = None
        self._delayed_cb = None

    def _maybe_disconnect(self):
        with self._sock_lock:
            now = monotonic()
            if now < self._disconnect_at:
                return self._disconnect_at - now

            # we have timed out due to inactivity,
            # time to disconnect the raw socket
            self._disconnect()
            return None

    @contextmanager
    def _get_tcp_socket(self):
        with self._sock_lock:
            # move forward the 'disconnect time'
            self._disconnect_at = monotonic() + self._disconnect_timeout

            if self._sock is None:
                self._connect()

            yield self._sock

    def sendall(self, data: bytes):
        """
        wraps socket.sendall() method
        """
        with self._get_tcp_socket() as sock:
            _log_msg(f"> {data}")
            sock.sendall(data)

    def recv(self, buffersize: int) -> bytes:
        """
        wraps socket.recv() methid
        """
        with self._get_tcp_socket() as sock:
            reply = sock.recv(buffersize)
            _log_msg(f"< {reply}")
            return reply

    def teardown(self):
        """
        show down all the internal machinery of this object
        """
        with self._sock_lock:
            if self._delayed_cb is None:
                return

            self._delayed_cb.cancel()
            self._disconnect()
