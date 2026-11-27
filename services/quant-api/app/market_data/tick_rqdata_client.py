"""Use the pinned RQData LiveMarketDataClient with verified WebSocket transport."""
from __future__ import annotations

import json
from ssl import create_default_context
from urllib.parse import urlsplit

from websockets.sync.client import connect

from app.market_data.rqdata_adapter import RQDataClient

_LOCKED_VERSION = "3.5.6.1"


def create_tick_client(provider: RQDataClient):
    if provider.client_version != _LOCKED_VERSION:
        raise ValueError("TICK_RQDATA_VERSION_UNPROVED")
    client_class = provider.api.LiveMarketDataClient

    class VerifiedConnection(client_class):
        # The pinned SDK retries certificate errors without verification.
        # Keep its authentication, subscriptions, receive and reconnect logic
        # and enforce verified TLS at that smallest transport seam.
        def _connect_and_login(self, login_data) -> None:
            url = urlsplit(self._ws_server_uri)
            if url.scheme != "wss" or not url.hostname or url.username or url.password:
                raise ValueError("TICK_RQDATA_TRANSPORT_INVALID")
            connection = connect(
                self._ws_server_uri, proxy=self._proxy_url, ssl=create_default_context(),
                open_timeout=5, close_timeout=2,
            )
            try:
                connection.send(json.dumps(login_data).encode("utf-8"))
                response = json.loads(connection.recv(timeout=3, decode=False))
                if type(response) is not dict:
                    raise ValueError("TICK_RQDATA_AUTH_INVALID")
            except BaseException:
                connection.close()
                raise
            self._client = connection
            self._info = response

    return VerifiedConnection()
