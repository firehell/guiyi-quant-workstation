"""Process-local routing for the pinned TqKq WebSocket endpoints.

macOS urllib falls back to system proxies even in an empty launchd environment.
Materialize that existing configuration before adding bypasses, so introducing
NO_PROXY doesn't accidentally remove the proxy for every other SDK request.
The market helper must receive the environment captured before this scope.
"""

import os
from urllib.parse import urlsplit
from urllib.request import getproxies

VERSION = "tqkq_direct_websocket_transport_v1"
DIRECT_HOSTS = ("free-api.shinnytech.com", "otg-sim.shinnytech.com")


def sdk_environment(environment, proxies):
    result = {k: v for k, v in environment.items() if not k.lower().endswith("_proxy")}
    for scheme, value in proxies.items():
        if not isinstance(scheme, str) or not scheme.isalpha() or not isinstance(value, str):
            raise ValueError("TQ_TRANSPORT_PROXY_UNPROVEN")
        result[scheme.lower() + "_proxy"] = value
    bypass = [v.strip() for v in proxies.get("no", "").split(",") if v.strip()]
    for host in DIRECT_HOSTS:
        if host not in bypass:
            bypass.append(host)
    result["no_proxy"] = ",".join(bypass)
    return result


class SdkTransport:
    def __init__(self):
        self.original = {k: v for k, v in os.environ.items() if k.lower().endswith("_proxy")}
        configured = sdk_environment(dict(os.environ), getproxies())
        for key in self.original:
            del os.environ[key]
        os.environ.update({k: v for k, v in configured.items() if k.lower().endswith("_proxy")})

    def verify(self, api, account):
        try:
            urls = (api._md_url, account._td_url)
            parsed = tuple(urlsplit(value) for value in urls)
            valid = all(
                value.scheme == "wss" and value.hostname == host
                and value.port in (None, 443) and value.username is None
                and value.password is None
                for value, host in zip(parsed, DIRECT_HOSTS, strict=True)
            )
        except (AttributeError, TypeError, ValueError):
            valid = False
        if not valid:
            raise ValueError("TQ_TRANSPORT_ENDPOINT_UNPROVEN")

    def close(self):
        for key in tuple(os.environ):
            if key.lower().endswith("_proxy"):
                del os.environ[key]
        os.environ.update(self.original)
