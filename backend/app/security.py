"""Políticas de seguridad: límite de intentos de login y destinos de diagnóstico."""
import ipaddress
import time


class LoginLimiter:
    def __init__(self, max_failures: int = 5, window_seconds: int = 300, clock=time.monotonic):
        self.max_failures, self.window, self._clock = max_failures, window_seconds, clock
        self._failures: dict[str, list[float]] = {}

    def _recent(self, key: str) -> list[float]:
        now = self._clock()
        kept = [t for t in self._failures.get(key, []) if now - t < self.window]
        if kept:
            self._failures[key] = kept
        else:
            self._failures.pop(key, None)
        return kept

    def is_blocked(self, key: str) -> bool:
        return len(self._recent(key)) >= self.max_failures

    def register_failure(self, key: str) -> None:
        self._recent(key)
        self._failures.setdefault(key, []).append(self._clock())

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)


def is_diagnostic_target_allowed(host: str) -> bool:
    """Bloquea loopback, link-local (incluye metadatos cloud 169.254.169.254),
    multicast, no especificadas y reservadas. Las redes privadas RFC1918 se permiten
    porque son el objetivo normal de un inventario de red."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return not (ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved)
