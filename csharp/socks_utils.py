import asyncio
from asyncio import AbstractEventLoop, Future
from socket import socket
from typing import Sequence, Callable, Coroutine
from functools import partial

from structures import Remote, PackageType
from util import unpack, pack

receiver_waiters: dict[Remote, Future] = {}
clients: set[Remote] = set()


def send_pack(
        sock: socket, addr: Remote,
        pack_type: PackageType, data: bytes | Sequence[bytes] = (0).to_bytes()
) -> int:
    return sock.sendto(pack(pack_type, data), addr)


async def send_pack_async(
        sock: socket, addr: Remote,
        pack_type: PackageType, data: bytes | Sequence[bytes] = (0).to_bytes(),
        loop: AbstractEventLoop = None
) -> int:
    loop = asyncio.get_running_loop() if loop is None else loop
    return await loop.sock_sendto(sock, pack(pack_type, data), addr)


async def recv_from(addr: Remote, loop: AbstractEventLoop = None) -> bytes:
    loop = asyncio.get_running_loop() if loop is None else loop
    fut = loop.create_future()
    receiver_waiters[addr] = fut
    return await fut


async def recv_pack_async(
        addr: Remote,
        loop: AbstractEventLoop = None
) -> tuple[PackageType, int | bytes]:
    return unpack(await recv_from(addr, loop=loop))


def abort(addr: Remote):
    clients.discard(addr)
    if addr in receiver_waiters:
        _ = receiver_waiters.pop(addr)


async def abort_bad_package(sock: socket, addr: Remote, loop: AbstractEventLoop = None):
    abort(addr)
    return await send_pack_async(sock, addr, pack_type=PackageType.bad_package, loop=loop)


def abort_timeout(sock: socket, addr: Remote):
    abort(addr)
    asyncio.get_event_loop().call_soon(partial(send_pack, sock, addr, PackageType.timeout))


async def receiver(
        sock: socket, new_handler: Callable[[socket, Remote, bytes], Coroutine],
        block_size=2048,
        loop: AbstractEventLoop = None
):
    loop = asyncio.get_running_loop() if loop is None else loop
    while True:
        buf, addr = await loop.sock_recvfrom(sock, block_size)
        fut = receiver_waiters.get(addr, None)
        if addr not in clients:
            clients.add(addr)
            await new_handler(sock, addr, buf)
        if fut is not None:
            fut.set_result(buf)
            del receiver_waiters[addr]
