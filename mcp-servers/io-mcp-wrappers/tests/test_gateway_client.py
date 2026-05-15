import pytest

from io_mcp_base.client import GatewayClient


def test_missing_jwt_raises(monkeypatch):
    monkeypatch.setenv("IO_GATEWAY_URL", "http://172.22.0.1:8080")
    monkeypatch.delenv("IO_USER_JWT", raising=False)
    with pytest.raises(RuntimeError, match="IO_USER_JWT"):
        GatewayClient()


def test_empty_jwt_raises(monkeypatch):
    monkeypatch.setenv("IO_GATEWAY_URL", "http://172.22.0.1:8080")
    monkeypatch.setenv("IO_USER_JWT", "")
    with pytest.raises(RuntimeError, match="IO_USER_JWT"):
        GatewayClient()


def test_missing_gateway_url_raises(monkeypatch):
    monkeypatch.setenv("IO_USER_JWT", "abc.def.ghi")
    monkeypatch.delenv("IO_GATEWAY_URL", raising=False)
    with pytest.raises(RuntimeError, match="IO_GATEWAY_URL"):
        GatewayClient()


def test_valid_env_constructs(monkeypatch):
    monkeypatch.setenv("IO_GATEWAY_URL", "http://172.22.0.1:8080")
    monkeypatch.setenv("IO_USER_JWT", "abc.def.ghi")
    client = GatewayClient()
    assert client.base_url == "http://172.22.0.1:8080"
