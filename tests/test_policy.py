"""Política de comandos de la consola: denegar por defecto y bloqueados primero."""
import pytest
from app.command_policy import ALLOWED, evaluate, policy_summary
from app.console_sim import apply_filter


@pytest.mark.parametrize("vendor,cmd", [
    ("cisco", "show version"),
    ("cisco", "SHOW   VERSION"),
    ("cisco", "show interfaces GigabitEthernet1/0/1"),
    ("cisco", "show running-config | include hostname"),
    ("fortinet", "get system status"),
    ("huawei", "display version"),
    ("huawei", "display interface GigabitEthernet0/0/1"),
])
def test_allowed_commands(vendor, cmd):
    assert evaluate(vendor, cmd).allowed


@pytest.mark.parametrize("vendor,cmd", [
    ("cisco", "configure terminal"),
    ("cisco", "write erase"),
    ("cisco", "reload"),
    ("cisco", "enable"),
    ("cisco", "ping 192.0.2.1"),
    ("cisco", "show version; reload"),
    ("cisco", "show version && reload"),
    ("cisco", "$(reboot)"),
    ("cisco", "show version | redirect flash:x"),
    ("cisco", "sh ver"),
    ("fortinet", "show version"),          # comando de otro fabricante
    ("fortinet", "execute reboot"),
    ("fortinet", "config system global"),
    ("huawei", "system-view"),
    ("huawei", "undo info-center enable"),
    ("huawei", "save"),
    ("other", "show version"),
])
def test_blocked_commands(vendor, cmd):
    d = evaluate(vendor, cmd)
    assert not d.allowed and d.reason


def test_blocked_categories_report_a_specific_reason():
    assert evaluate("cisco", "write erase").category == "bloqueado-persistencia"
    assert evaluate("cisco", "configure terminal").category == "bloqueado-configuracion"
    assert evaluate("cisco", "show version; reload").category == "caracteres"
    assert evaluate("cisco", "sh ver").category == "no-listado"
    assert evaluate("cisco", "").category == "vacio"
    assert evaluate("cisco", "show " + "a" * 300).category == "longitud"


def test_every_allowed_command_passes_the_policy_itself():
    """La lista de permitidos no puede contradecir a la de bloqueados."""
    for vendor, items in ALLOWED.items():
        for cmd, _, _ in items:
            sample = cmd.replace("<if>", "GigabitEthernet1/0/1")
            assert evaluate(vendor, sample).allowed, (vendor, cmd)


def test_policy_summary_exposes_rules():
    s = policy_summary("cisco")
    assert len(s["blocked"]) == 6 and s["allowed"] and s["rules"]


def test_output_filters():
    text = "a up\nb down\nc up"
    assert apply_filter(text, "include up") == "a up\nc up"
    assert apply_filter(text, "exclude up") == "b down"
    assert apply_filter(text, "begin down") == "b down\nc up"
    assert apply_filter(text, "count up").endswith("2")