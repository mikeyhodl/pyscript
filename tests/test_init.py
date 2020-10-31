"""Test the pyscript component."""
from ast import literal_eval
import asyncio
from datetime import datetime as dt
import pathlib

from custom_components.pyscript.const import DOMAIN
from custom_components.pyscript.event import Event
from custom_components.pyscript.function import Function
from custom_components.pyscript.global_ctx import GlobalContextMgr
from custom_components.pyscript.state import State
import custom_components.pyscript.trigger as trigger
from pytest_homeassistant_custom_component.async_mock import mock_open, patch

from homeassistant import loader
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, EVENT_STATE_CHANGED
from homeassistant.core import Context
from homeassistant.helpers.service import async_get_all_descriptions
from homeassistant.setup import async_setup_component


async def setup_script(hass, notify_q, now, source):
    """Initialize and load the given pyscript."""

    scripts = [
        "/some/config/dir/pyscript/hello.py",
    ]

    with patch("custom_components.pyscript.os.path.isdir", return_value=True), patch(
        "custom_components.pyscript.glob.iglob", return_value=scripts
    ), patch("custom_components.pyscript.global_ctx.open", mock_open(read_data=source), create=True,), patch(
        "custom_components.pyscript.trigger.dt_now", return_value=now
    ), patch(
        "homeassistant.config.load_yaml_config_file", return_value={}
    ):
        assert await async_setup_component(hass, "pyscript", {DOMAIN: {}})

    #
    # I'm not sure how to run the mock all the time, so just force the dt_now()
    # trigger function to return the fixed time, now.
    #
    trigger.__dict__["dt_now"] = lambda: now

    if notify_q:

        async def state_changed(event):
            var_name = event.data["entity_id"]
            if var_name != "pyscript.done":
                return
            value = event.data["new_state"].state
            await notify_q.put(value)

        hass.bus.async_listen(EVENT_STATE_CHANGED, state_changed)


async def wait_until_done(notify_q):
    """Wait for the done handshake."""
    return await asyncio.wait_for(notify_q.get(), timeout=4)


async def test_setup_makedirs_on_no_dir(hass, caplog):
    """Test setup calls os.makedirs when no dir found."""
    with patch("custom_components.pyscript.os.path.isdir", return_value=False), patch(
        "custom_components.pyscript.os.makedirs"
    ) as makedirs_call, patch("homeassistant.config.load_yaml_config_file", return_value={}):
        res = await async_setup_component(hass, "pyscript", {DOMAIN: {}})

    assert res
    assert makedirs_call.called


async def test_service_exists(hass, caplog):
    """Test discover, compile script and install a service."""

    await setup_script(
        hass,
        None,
        dt(2020, 7, 1, 11, 59, 59, 999999),
        """
@service
def func1():
    pass

def func2():
    pass

@service
def reload():
    pass

@state_active("arg1", "too many args")
def func4():
    pass

@service("too many args")
def func5():
    pass

@time_trigger("wrong arg type", 50)
def func6():
    pass

@time_trigger("invalid kwargs", arg=10)
@task_unique("invalid kwargs", arg=10)
def func7():
    pass
""",
    )
    assert hass.services.has_service("pyscript", "func1")
    assert hass.services.has_service("pyscript", "reload")
    assert not hass.services.has_service("pyscript", "func2")
    assert (
        "function 'reload' in file.hello with @service conflicts with builtin service; ignoring (please rename function)"
        in caplog.text
    )
    assert (
        "func4 defined in file.hello: decorator @state_active got 2 arguments, expected 1; ignoring decorator"
        in caplog.text
    )
    assert (
        "func5 defined in file.hello: decorator @service takes no arguments; ignoring decorator"
        in caplog.text
    )
    assert (
        "func6 defined in file.hello: decorator @time_trigger argument 2 should be a string; ignoring decorator"
        in caplog.text
    )
    assert (
        "func7 defined in file.hello: decorator @time_trigger doesn't take keyword arguments; ignored"
        in caplog.text
    )
    assert (
        "func7 defined in file.hello: decorator @task_unique valid keyword arguments are: kill_me; others ignored"
        in caplog.text
    )


async def test_syntax_error(hass, caplog):
    """Test syntax error in pyscript file."""

    await setup_script(
        hass,
        None,
        dt(2020, 7, 1, 11, 59, 59, 999999),
        """
@service
def func1()
    pass
""",
    )
    assert "SyntaxError: invalid syntax (hello.py, line 3)" in caplog.text


async def test_syntax_error2(hass, caplog):
    """Test syntax error in pyscript file."""

    await setup_script(
        hass,
        None,
        dt(2020, 7, 1, 11, 59, 59, 999999),
        """
xyz def 123
""",
    )
    assert "SyntaxError: invalid syntax (hello.py, line 2)" in caplog.text


async def test_runtime_error(hass, caplog):
    """Test run-time error in pyscript file."""

    await setup_script(
        hass,
        None,
        dt(2020, 7, 1, 11, 59, 59, 999999),
        """
@service
def func_runtime_error():
    pass

xyz
""",
    )
    assert "NameError: name 'xyz' is not defined" in caplog.text


async def test_service_description(hass):
    """Test service description defined in doc_string."""

    await setup_script(
        hass,
        None,
        dt(2020, 7, 1, 11, 59, 59, 999999),
        """
@service
def func_no_doc_string(param1=None):
    pass

@service
def func_simple_doc_string(param2=None, param3=None):
    \"\"\"This is func2_simple_doc_string.\"\"\"
    pass

@service
def func_yaml_doc_string(param2=None, param3=None):
    \"\"\"yaml
description: This is func_yaml_doc_string.
fields:
  param1:
    description: first argument
    example: 12
  param2:
    description: second argument
    example: 34
\"\"\"
    pass
""",
    )

    integration = loader.Integration(
        hass,
        "custom_components.pyscript",
        pathlib.Path("custom_components/pyscript"),
        {"name": "pyscript", "dependencies": [], "requirements": [], "domain": "automation"},
    )

    with patch(
        "homeassistant.loader.async_get_custom_components", return_value={"pyscript": integration},
    ):
        descriptions = await async_get_all_descriptions(hass)

    assert descriptions[DOMAIN]["func_no_doc_string"] == {
        "description": "pyscript function func_no_doc_string()",
        "fields": {"param1": {"description": "argument param1"}},
    }

    assert descriptions[DOMAIN]["func_simple_doc_string"] == {
        "description": "This is func2_simple_doc_string.",
        "fields": {
            "param2": {"description": "argument param2"},
            "param3": {"description": "argument param3"},
        },
    }

    assert descriptions[DOMAIN]["func_yaml_doc_string"] == {
        "description": "This is func_yaml_doc_string.",
        "fields": {
            "param1": {"description": "first argument", "example": "12"},
            "param2": {"description": "second argument", "example": "34"},
        },
    }


async def test_service_run(hass, caplog):
    """Test running a service with keyword arguments."""
    notify_q = asyncio.Queue(0)
    await setup_script(
        hass,
        notify_q,
        dt(2020, 7, 1, 11, 59, 59, 999999),
        """

@service
def func1(arg1=1, arg2=2, context=None):
    x = 1
    x = 2 * x + 3
    log.info(f"this is func1 x = {x}, arg1 = {arg1}, arg2 = {arg2}")
    pyscript.done = [x, arg1, arg2, str(context)]

@service
def func2(**kwargs):
    x = 1
    x = 2 * x + 3
    log.info(f"this is func1 x = {x}, kwargs = {kwargs}")
    has2 = service.has_service("pyscript", "func2")
    has3 = service.has_service("pyscript", "func3")
    del kwargs["context"]
    pyscript.done = [x, kwargs, has2, has3]

@service
def call_service(domain=None, name=None, **kwargs):
    if domain == "pyscript" and name == "func1":
        task.sleep(0)
        pyscript.func1(**kwargs)
    else:
        service.call(domain, name, **kwargs)

""",
    )
    context = Context(user_id="1234", parent_id="5678", id="8901")
    await hass.services.async_call("pyscript", "func1", {}, context=context)
    ret = await wait_until_done(notify_q)
    assert literal_eval(ret) == [5, 1, 2, str(context)]
    assert "this is func1 x = 5" in caplog.text

    await hass.services.async_call("pyscript", "func1", {"arg1": 10}, context=context)
    ret = await wait_until_done(notify_q)
    assert literal_eval(ret) == [5, 10, 2, str(context)]

    await hass.services.async_call(
        "pyscript",
        "call_service",
        {"domain": "pyscript", "name": "func1", "arg1": "string1"},
        context=context,
    )
    ret = await wait_until_done(notify_q)
    assert literal_eval(ret) == [5, "string1", 2, str(context)]

    await hass.services.async_call("pyscript", "func1", {"arg1": "string1", "arg2": 123}, context=context)
    ret = await wait_until_done(notify_q)
    assert literal_eval(ret) == [5, "string1", 123, str(context)]

    await hass.services.async_call("pyscript", "call_service", {"domain": "pyscript", "name": "func2"})
    ret = await wait_until_done(notify_q)
    assert literal_eval(ret) == [5, {"trigger_type": "service"}, 1, 0]

    await hass.services.async_call(
        "pyscript", "call_service", {"domain": "pyscript", "name": "func2", "arg1": "string1"},
    )
    ret = await wait_until_done(notify_q)
    assert literal_eval(ret) == [5, {"trigger_type": "service", "arg1": "string1"}, 1, 0]

    await hass.services.async_call("pyscript", "func2", {"arg1": "string1", "arg2": 123})
    ret = await wait_until_done(notify_q)
    assert literal_eval(ret) == [5, {"trigger_type": "service", "arg1": "string1", "arg2": 123}, 1, 0]


async def test_reload(hass, caplog):
    """Test reload."""
    notify_q = asyncio.Queue(0)
    now = dt(2020, 7, 1, 11, 59, 59, 999999)
    source0 = """
seq_num = 0

@time_trigger
def func_startup_sync():
    global seq_num

    seq_num += 1
    log.info(f"func_startup_sync setting pyscript.done = {seq_num}")
    pyscript.done = seq_num

@service
@state_trigger("pyscript.f1var1 == '1'")
def func1(var_name=None, value=None):
    global seq_num

    seq_num += 1
    log.info(f"func1 var = {var_name}, value = {value}")
    pyscript.done = [seq_num, var_name, int(value)]

"""
    source1 = """
seq_num = 10

@time_trigger("startup")
def func_startup_sync():
    global seq_num

    seq_num += 1
    log.info(f"func_startup_sync setting pyscript.done = {seq_num}")
    pyscript.done = seq_num

@service
@state_trigger("pyscript.f5var1 == '1'")
def func5(var_name=None, value=None):
    global seq_num

    seq_num += 1
    log.info(f"func5 var = {var_name}, value = {value}")
    pyscript.done = [seq_num, var_name, int(value)]

"""

    await setup_script(hass, notify_q, now, source0)

    #
    # run and reload 6 times with different sournce files to make sure seqNum
    # gets reset, autostart of func_startup_sync happens and triggers work each time
    #
    # first time: fire event to startup triggers and run func_startup_sync
    #
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    for i in range(6):
        if i & 1:
            seq_num = 10

            assert not hass.services.has_service("pyscript", "func1")
            assert hass.services.has_service("pyscript", "reload")
            assert hass.services.has_service("pyscript", "func5")

            seq_num += 1
            assert literal_eval(await wait_until_done(notify_q)) == seq_num

            seq_num += 1
            # initialize the trigger and active variables
            hass.states.async_set("pyscript.f5var1", 0)

            # try some values that shouldn't work, then one that does
            hass.states.async_set("pyscript.f5var1", "string")
            hass.states.async_set("pyscript.f5var1", 1)
            assert literal_eval(await wait_until_done(notify_q)) == [
                seq_num,
                "pyscript.f5var1",
                1,
            ]
            assert "func5 var = pyscript.f5var1, value = 1" in caplog.text
            next_source = source0

        else:
            seq_num = 0

            assert hass.services.has_service("pyscript", "func1")
            assert hass.services.has_service("pyscript", "reload")
            assert not hass.services.has_service("pyscript", "func5")

            seq_num += 1
            assert literal_eval(await wait_until_done(notify_q)) == seq_num

            seq_num += 1
            # initialize the trigger and active variables
            hass.states.async_set("pyscript.f1var1", 0)

            # try some values that shouldn't work, then one that does
            hass.states.async_set("pyscript.f1var1", "string")
            hass.states.async_set("pyscript.f1var1", 1)
            assert literal_eval(await wait_until_done(notify_q)) == [
                seq_num,
                "pyscript.f1var1",
                1,
            ]
            assert "func1 var = pyscript.f1var1, value = 1" in caplog.text
            next_source = source1

        #
        # now reload the other source file
        #
        scripts = [
            "/some/config/dir/pyscript/hello.py",
        ]

        with patch("custom_components.pyscript.os.path.isdir", return_value=True), patch(
            "custom_components.pyscript.glob.iglob", return_value=scripts
        ), patch(
            "custom_components.pyscript.global_ctx.open", mock_open(read_data=next_source), create=True,
        ), patch(
            "custom_components.pyscript.trigger.dt_now", return_value=now
        ), patch(
            "homeassistant.config.load_yaml_config_file", return_value={}
        ):
            reload_param = {}
            if i % 2 == 1:
                #
                # on alternate times, just reload the specific file we are testing with
                #
                reload_param = {"global_ctx": "file.hello"}
            await hass.services.async_call("pyscript", "reload", reload_param, blocking=True)
            if i % 3 == 0:
                #
                # reload a file that doesn't exist; will log error and do nothing
                #
                await hass.services.async_call(
                    "pyscript", "reload", {"global_ctx": "file.nosuchfile"}, blocking=True
                )

    assert "pyscript.reload: no global context 'file.nosuchfile' to reload" in caplog.text


async def test_misc_errors(hass, caplog):
    """Test miscellaneous errors."""

    await setup_script(hass, None, dt(2020, 7, 1, 11, 59, 59, 999999), "")

    Function()
    GlobalContextMgr()
    State()
    Event()
    Event.notify_del("not_in_notify_list", None)
    trigger.TrigTime()

    assert "Function class is not meant to be instantiated" in caplog.text
    assert "GlobalContextMgr class is not meant to be instantiated" in caplog.text
    assert "State class is not meant to be instantiated" in caplog.text
    assert "Event class is not meant to be instantiated" in caplog.text
    assert "TrigTime class is not meant to be instantiated" in caplog.text


async def test_install_requirements(hass):
    """Test install_requirements function."""
    requirements = """
pytube==9.7.0
# another test comment
pykakasi==2.0.1 # test comment

"""

    with patch("custom_components.pyscript.async_hass_config_yaml", return_value={}), patch(
        "custom_components.pyscript.open", mock_open(read_data=requirements), create=True,
    ), patch("custom_components.pyscript.async_process_requirements") as install_requirements:
        await setup_script(hass, None, dt(2020, 7, 1, 11, 59, 59, 999999), "")
        assert install_requirements.call_args[0][2] == ["pytube==9.7.0", "pykakasi==2.0.1"]
        install_requirements.reset_mock()
        # Because in tests, packages are not installed, we fake that they are
        # installed so we can test that we don't attempt to install them
        with patch("custom_components.pyscript.installed_version", return_value="2.0.1"):
            await hass.services.async_call("pyscript", "reload", {}, blocking=True)
            assert not install_requirements.called
