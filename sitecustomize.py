import asyncio
import socket
import sys

# Prefer IPv4 over IPv6 on networks where IPv6 is advertised but non-routable
_orig_getaddrinfo = socket.getaddrinfo


def _ipv4_first_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    try:
        res = _orig_getaddrinfo(host, port, family, type, proto, flags)
        return sorted(res, key=lambda x: 0 if x[0] == socket.AF_INET else 1)
    except OSError:
        return _orig_getaddrinfo(host, port, family, type, proto, flags)


socket.getaddrinfo = _ipv4_first_getaddrinfo

# Ensure WindowsSelectorEventLoopPolicy on Windows for SSL socket support
if sys.platform == "win32":
    policy_cls = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if isinstance(policy_cls, type):
        policy = policy_cls()
        if isinstance(policy, asyncio.AbstractEventLoopPolicy):
            asyncio.set_event_loop_policy(policy)

    try:
        import uvicorn.loops.asyncio

        uvicorn.loops.asyncio.asyncio_loop_factory = (
            lambda use_subprocess=False: asyncio.SelectorEventLoop
        )
    except (ImportError, AttributeError):
        pass
