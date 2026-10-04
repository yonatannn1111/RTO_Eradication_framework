import socket
from dataclasses import dataclass


@dataclass
class PLCStatus:
    modbus_open: bool
    s7_open: bool
    https_open: bool
    errors: list


def check_port(host: str, port: int, timeout: float = 2.0) -> bool:
    """Return True if a TCP port is accepting connections."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def verify_plc(host: str, modbus_port: int = 502,
               s7_port: int = 102, https_port: int = 8443) -> PLCStatus:
    """
    Check that the three OpenPLC services are reachable.
    """
    errors = []

    modbus = check_port(host, modbus_port)
    if not modbus:
        errors.append(f"Modbus port {modbus_port} not reachable")

    s7 = check_port(host, s7_port)
    if not s7:
        errors.append(f"S7 port {s7_port} not reachable")

    https = check_port(host, https_port)
    if not https:
        errors.append(f"HTTPS port {https_port} not reachable (web UI down?)")

    return PLCStatus(
        modbus_open=modbus,
        s7_open=s7,
        https_open=https,
        errors=errors,
    )


def require_plc(host: str, **kwargs) -> PLCStatus:
    """Like verify_plc, but raises if Modbus (the critical service) is down."""
    status = verify_plc(host, **kwargs)
    if not status.modbus_open:
        raise ConnectionError(
            f"OpenPLC at {host} is not accepting Modbus connections"
        )
    return status


if __name__ == "__main__":
    s = verify_plc("127.0.0.1")
    print(f"Modbus: {'UP' if s.modbus_open else 'DOWN'}")
    print(f"S7:     {'UP' if s.s7_open else 'DOWN'}")
    print(f"HTTPS:  {'UP' if s.https_open else 'DOWN'}")
    for e in s.errors:
        print(f"  ! {e}")
