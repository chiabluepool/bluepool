import asyncio
import socket

from chia.server.server import ChiaServer
from chia.types.peer_info import PeerInfo


def start_reconnect_task(server: ChiaServer, peer_info_arg: PeerInfo, log, auth: bool):
    """
    Start a background task that checks connection and reconnects periodically to a peer.
    """

    async def connection_check():
        while True:
            try:
                peer_info = PeerInfo(socket.gethostbyname(peer_info_arg.host), peer_info_arg.port)
                peer_retry = True
                for _, connection in server.all_connections.items():
                    if connection.get_peer_info() == peer_info or connection.get_peer_info() == peer_info_arg:
                        peer_retry = False
                if peer_retry:
                    log.info(f"Reconnecting to peer {peer_info}")
                    try:
                        await server.start_client(peer_info, server.on_connect, auth=auth)
                    except Exception as e:
                        log.info(f"Failed to connect to {peer_info} {e}")
                await asyncio.sleep(3)
            except Exception as e:
                log.info(f"Failed to connect to {peer_info} {e}")

    return asyncio.create_task(connection_check())
