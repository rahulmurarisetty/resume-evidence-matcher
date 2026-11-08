"""The client address behind trusted proxies, for per-IP rate limits.

The address of the connecting machine is used unless it is a trusted proxy. Then
X-Forwarded-For is read from the right, skipping trusted proxies, and the first
address that isn't one is the client. Entries to the left of it can be set by the
client and are never used.
"""

import ipaddress
from collections.abc import Iterable
from dataclasses import dataclass

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

# Longest address string kept as a rate-limit key.
_MAX_ADDRESS = 64


def parse_networks(text: str) -> tuple[IPNetwork, ...]:
    """Read a comma-separated list of addresses and CIDR ranges."""
    networks: list[IPNetwork] = []
    for item in text.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError as exc:
            raise ValueError(
                f'"{item}" is not an IP address or CIDR range, such as 10.0.0.0/8.'
            ) from exc
    return tuple(networks)


def _address(text: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    text = text.strip()
    # "[2001:db8::1]:443" and "203.0.113.7:51234" carry a port.
    if text.startswith("[") and "]" in text:
        text = text[1 : text.index("]")]
    elif text.count(":") == 1:
        text = text.split(":", 1)[0]
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


@dataclass(frozen=True)
class TrustedProxies:
    networks: tuple[IPNetwork, ...] = ()

    def trusts(self, text: str) -> bool:
        address = _address(text)
        return address is not None and any(address in network for network in self.networks)

    def client_address(self, peer: str | None, forwarded_for: Iterable[str]) -> str:
        """The client address for a request from `peer` with these
        X-Forwarded-For headers (all of them, in order)."""
        peer = (peer or "unknown")[:_MAX_ADDRESS]
        if not self.trusts(peer):
            return _normalized(peer)
        hops = [hop.strip() for header in forwarded_for for hop in header.split(",")]
        hops = [hop for hop in hops if hop]
        for hop in reversed(hops):
            if not self.trusts(hop):
                return _normalized(hop[:_MAX_ADDRESS])
        # Every hop is a trusted proxy: the leftmost is the furthest one known.
        return _normalized(hops[0][:_MAX_ADDRESS]) if hops else _normalized(peer)


def _normalized(text: str) -> str:
    address = _address(text)
    return str(address) if address is not None else text
