"""Test pyscript @webhook_trigger decorator."""

import pytest

from homeassistant.components import webhook
from homeassistant.util.aiohttp import MockRequest


@pytest.mark.asyncio
async def test_webhook_request_kwarg(pyscript):
    """The aiohttp request is passed to the user function as the `request` kwarg."""
    await pyscript.start("""
@webhook_trigger("test_req_hook")
def webhook_test(payload, request):
    pyscript.done = [request.headers["X-My-Sig"], request.method, payload]
""")

    request = MockRequest(
        content=b'{"hello": "world"}',
        mock_source="test",
        method="POST",
        headers={"Content-Type": "application/json", "X-My-Sig": "abc123"},
        remote="127.0.0.1",
    )
    await webhook.async_handle_webhook(pyscript.hass, "test_req_hook", request)

    await pyscript.wait_done(["abc123", "POST", {"hello": "world"}])


@pytest.mark.asyncio
async def test_webhook_methods_order(pyscript):
    """Same webhook_id with methods listed in a different order is not a conflict."""
    await pyscript.start("""
@webhook_trigger("order_hook", methods=["GET", "POST"])
def func_order_a():
    pass

@webhook_trigger("order_hook", methods=["POST", "GET"])
def func_order_b():
    pass
""")
    assert pyscript.exceptions.empty()


@pytest.mark.asyncio
async def test_webhooks_method(pyscript):
    """Test invalid keyword arguments type generates an error."""
    await pyscript.start("""
@webhook_trigger("hook", methods=["bad"])
def func8():
    pass
""")
    await pyscript.wait_exception(TypeError, match="func8' defined in file.hello")


@pytest.mark.asyncio
async def test_webhook_local_only_conflict(pyscript):
    """Test @webhook_trigger with same webhook_id but conflicting local_only raises."""
    await pyscript.start("""
@webhook_trigger("conflict_local", local_only=True)
def func_local_a():
    pass

@webhook_trigger("conflict_local", local_only=False)
def func_local_b():
    pass
""")
    await pyscript.wait_exception(ValueError, match="'conflict_local' conflicts with existing")


@pytest.mark.asyncio
async def test_webhook_methods_conflict(pyscript):
    """Test @webhook_trigger with same webhook_id but conflicting methods raises."""
    await pyscript.start("""
@webhook_trigger("conflict_methods", methods=["GET"])
def func_methods_a():
    pass

@webhook_trigger("conflict_methods", methods=["POST"])
def func_methods_b():
    pass
""")
    await pyscript.wait_exception(ValueError, match="'conflict_methods' conflicts with existing")


@pytest.mark.asyncio
async def test_webhook_methods_missing_vs_set_conflict(pyscript):
    """Test @webhook_trigger with same webhook_id but only one specifying methods raises."""
    await pyscript.start("""
@webhook_trigger("conflict_unset")
def func_unset_a():
    pass

@webhook_trigger("conflict_unset", methods=["POST"])
def func_unset_b():
    pass
""")
    await pyscript.wait_exception(ValueError, match="'conflict_unset' conflicts with existing")
