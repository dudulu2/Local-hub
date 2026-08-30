from __future__ import annotations

import errno
import ipaddress
import os
import socket
import threading

_LOCK = threading.RLock()
_INSTALLED = False

_ORIGINAL_CREATE_CONNECTION = socket.create_connection
_ORIGINAL_CONNECT = socket.socket.connect
_ORIGINAL_CONNECT_EX = socket.socket.connect_ex
_ORIGINAL_SENDTO = socket.socket.sendto
_ORIGINAL_GETADDRINFO = socket.getaddrinfo
_ORIGINAL_GETHOSTBYNAME = socket.gethostbyname
_ORIGINAL_GETHOSTBYNAME_EX = socket.gethostbyname_ex

_LOCAL_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost"}


def _host_text(host) -> str:
    if isinstance(host, bytes):
        try:
            host = host.decode("ascii", "strict")
        except Exception:
            return ""
    return str(host or "").strip().strip("[]")


def is_loopback_host(host) -> bool:
    text = _host_text(host)
    if not text:
        return False
    lowered = text.casefold().rstrip(".")
    if lowered in _LOCAL_NAMES:
        return True
    # IPv6 link-local zone suffixes are not loopback and therefore remain blocked.
    if "%" in lowered:
        lowered = lowered.split("%", 1)[0]
    try:
        return ipaddress.ip_address(lowered).is_loopback
    except ValueError:
        return False


def _deny(host) -> None:
    raise PermissionError(
        errno.EACCES,
        "LocalHub privacy guard blocked a non-local network destination",
        _host_text(host),
    )


def _guard_destination(address) -> None:
    if not isinstance(address, tuple) or not address:
        return
    host = address[0]
    if not is_loopback_host(host):
        _deny(host)


def _guarded_create_connection(address, *args, **kwargs):
    _guard_destination(address)
    return _ORIGINAL_CREATE_CONNECTION(address, *args, **kwargs)


def _guarded_connect(sock, address):
    if sock.family in {socket.AF_INET, socket.AF_INET6}:
        _guard_destination(address)
    return _ORIGINAL_CONNECT(sock, address)


def _guarded_connect_ex(sock, address):
    if sock.family in {socket.AF_INET, socket.AF_INET6}:
        try:
            _guard_destination(address)
        except PermissionError:
            return errno.EACCES
    return _ORIGINAL_CONNECT_EX(sock, address)


def _guarded_sendto(sock, data, *args):
    # sendto(data, address) or sendto(data, flags, address)
    address = args[-1] if args else None
    if sock.family in {socket.AF_INET, socket.AF_INET6}:
        _guard_destination(address)
    return _ORIGINAL_SENDTO(sock, data, *args)


def _guarded_getaddrinfo(host, *args, **kwargs):
    if host is not None and not is_loopback_host(host):
        _deny(host)
    return _ORIGINAL_GETADDRINFO(host, *args, **kwargs)


def _guarded_gethostbyname(host):
    if not is_loopback_host(host):
        _deny(host)
    return _ORIGINAL_GETHOSTBYNAME(host)


def _guarded_gethostbyname_ex(host):
    if not is_loopback_host(host):
        _deny(host)
    return _ORIGINAL_GETHOSTBYNAME_EX(host)


def install() -> None:
    """Make the LocalHub Python process loopback-only.

    LocalHub's browser UI talks to its own 127.0.0.1 HTTP server. There is no
    runtime need for DNS or outbound TCP/UDP. Blocking those primitives here
    prevents a future feature or dependency from silently turning LocalHub into
    an internet-connected application.
    """
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return
        # Proxy variables are irrelevant to a loopback-only program and could
        # otherwise route an accidental HTTP request outside the machine.
        for key in (
            "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
            "http_proxy", "https_proxy", "all_proxy",
        ):
            os.environ.pop(key, None)
        os.environ["NO_PROXY"] = "localhost,127.0.0.1,::1"
        os.environ["no_proxy"] = "localhost,127.0.0.1,::1"

        socket.create_connection = _guarded_create_connection
        socket.socket.connect = _guarded_connect
        socket.socket.connect_ex = _guarded_connect_ex
        socket.socket.sendto = _guarded_sendto
        socket.getaddrinfo = _guarded_getaddrinfo
        socket.gethostbyname = _guarded_gethostbyname
        socket.gethostbyname_ex = _guarded_gethostbyname_ex
        _INSTALLED = True


def installed() -> bool:
    return _INSTALLED
