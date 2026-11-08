import pytest

from app.services.network import TrustedProxies, parse_networks

PRIVATE = TrustedProxies(parse_networks("10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, fc00::/7"))


def test_no_trusted_proxies_uses_the_peer() -> None:
    proxies = TrustedProxies()
    assert proxies.client_address("203.0.113.9", ["198.51.100.1"]) == "203.0.113.9"
    assert proxies.client_address(None, []) == "unknown"
    assert proxies.client_address("testclient", []) == "testclient"


def test_an_untrusted_peer_cant_set_its_address() -> None:
    assert PRIVATE.client_address("203.0.113.9", ["10.0.0.5"]) == "203.0.113.9"


@pytest.mark.parametrize(
    ("headers", "client"),
    [
        (["198.51.100.7"], "198.51.100.7"),
        # A client can prepend anything; the first untrusted hop from the right wins.
        (["1.1.1.1, 198.51.100.7"], "198.51.100.7"),
        (["1.1.1.1, 198.51.100.7, 10.1.2.3"], "198.51.100.7"),
        # Several headers count as one list.
        (["1.1.1.1", "198.51.100.7, 172.20.0.4"], "198.51.100.7"),
        # Ports and IPv4-mapped IPv6 are read as the address.
        (["198.51.100.7:51234"], "198.51.100.7"),
        (["[2001:db8::1]:443"], "2001:db8::1"),
        (["::ffff:198.51.100.7"], "198.51.100.7"),
        # Every hop trusted: the furthest one known.
        (["192.168.1.10, 10.0.0.2"], "192.168.1.10"),
        ([], "10.0.0.1"),
        # Garbage from a client is kept as text, bounded.
        (["not-an-ip"], "not-an-ip"),
    ],
)
def test_forwarded_for_behind_trusted_proxies(headers: list[str], client: str) -> None:
    assert PRIVATE.client_address("10.0.0.1", headers) == client


def test_bad_networks_are_rejected() -> None:
    assert parse_networks(" , 10.0.0.1 ,") == parse_networks("10.0.0.1/32")
    with pytest.raises(ValueError, match="CIDR"):
        parse_networks("10.0.0.0/8, nonsense")
