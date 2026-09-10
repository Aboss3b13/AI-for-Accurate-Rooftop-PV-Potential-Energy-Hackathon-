"""Freeing port 8000 from a previous SolarFit, and refusing to touch anything else."""

import pytest

from scripts import port_guard

NETSTAT = """
Active Connections

  Proto  Local Address          Foreign Address        State           PID
  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       1044
  TCP    127.0.0.1:8000         0.0.0.0:0              LISTENING       116100
  TCP    127.0.0.1:8000         127.0.0.1:55503        ESTABLISHED     116100
  TCP    127.0.0.1:4040         0.0.0.0:0              LISTENING       9021
  TCP    0.0.0.0:80             0.0.0.0:0              LISTENING       4
"""


def test_only_listening_rows_on_the_asked_port_are_read():
    assert port_guard.parse_windows_listeners(NETSTAT, 8000) == [116100]
    assert port_guard.parse_windows_listeners(NETSTAT, 4040) == [9021]
    assert port_guard.parse_windows_listeners(NETSTAT, 9999) == []


def test_a_port_that_is_a_prefix_of_another_is_not_confused():
    # 8000 must not match 80, nor 80 match 8000.
    assert 4 not in port_guard.parse_windows_listeners(NETSTAT, 8000)
    assert port_guard.parse_windows_listeners(NETSTAT, 80) == [4]


def test_posix_process_ids_are_read():
    assert port_guard.parse_posix_listeners("4123\n4124\n") == [4123, 4124]
    assert port_guard.parse_posix_listeners("") == []
    assert port_guard.parse_posix_listeners("not-a-pid\n") == []


def test_a_free_port_needs_no_replacing(monkeypatch):
    monkeypatch.setattr(port_guard, "running_app", lambda port, timeout=1.5: None)
    monkeypatch.setattr(port_guard, "is_free", lambda port: True)
    assert port_guard.replace_previous(8000, log=lambda *a: None) is True


def test_another_application_is_never_stopped(monkeypatch):
    killed = []
    monkeypatch.setattr(port_guard, "running_app",
                        lambda port, timeout=1.5: {"app": "SomethingElse"})
    monkeypatch.setattr(port_guard, "stop", lambda pid: killed.append(pid))
    said = []
    assert port_guard.replace_previous(8000, log=said.append) is False
    assert killed == []
    assert any("another application" in m for m in said)


def test_a_previous_solarfit_is_closed(monkeypatch):
    stopped, forced = [], []
    monkeypatch.setattr(port_guard, "running_app",
                        lambda port, timeout=1.5: {"app": "SolarFit"})
    monkeypatch.setattr(port_guard, "listeners", lambda port: [4321])
    monkeypatch.setattr(port_guard, "stop", lambda pid: stopped.append(pid))
    monkeypatch.setattr(port_guard, "force", lambda pid: forced.append(pid))
    monkeypatch.setattr(port_guard, "wait_until_free", lambda port, timeout=0: True)
    assert port_guard.replace_previous(8000, log=lambda *a: None) is True
    assert stopped == [4321]
    assert forced == []


def test_a_stubborn_process_is_forced_then_reported(monkeypatch):
    forced = []
    monkeypatch.setattr(port_guard, "running_app",
                        lambda port, timeout=1.5: {"app": "SolarFit"})
    monkeypatch.setattr(port_guard, "listeners", lambda port: [4321])
    monkeypatch.setattr(port_guard, "stop", lambda pid: None)
    monkeypatch.setattr(port_guard, "force", lambda pid: forced.append(pid))
    monkeypatch.setattr(port_guard, "wait_until_free", lambda port, timeout=0: False)
    said = []
    assert port_guard.replace_previous(8000, log=said.append) is False
    assert forced == [4321]
    assert any("did not close" in m for m in said)


def test_an_unidentifiable_holder_is_not_guessed_at(monkeypatch):
    monkeypatch.setattr(port_guard, "running_app",
                        lambda port, timeout=1.5: {"app": "SolarFit"})
    monkeypatch.setattr(port_guard, "listeners", lambda port: [])
    said = []
    assert port_guard.replace_previous(8000, log=said.append) is False
    assert any("could not be identified" in m for m in said)


def test_a_free_port_reads_as_free():
    import socket

    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen(1)
        busy = taken.getsockname()[1]
        assert port_guard.is_free(busy) is False
    assert port_guard.is_free(busy) is True
