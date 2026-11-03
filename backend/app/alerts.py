"""Reglas de alerta (Sprint 7). La evaluación es una función pura y fácil de probar."""
import asyncio
import json
import logging
import os
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AlertThresholds:
    failures: int = 3          # sondeos consecutivos sin respuesta => caída
    latency_ms: int = 200      # latencia considerada alta
    latency_samples: int = 3   # sondeos consecutivos sobre el umbral


def thresholds_from_env() -> AlertThresholds:
    return AlertThresholds(
        failures=max(1, int(os.getenv("ALERT_FAILURES", "3"))),
        latency_ms=max(1, int(os.getenv("ALERT_LATENCY_MS", "200"))),
        latency_samples=max(1, int(os.getenv("ALERT_LATENCY_SAMPLES", "3"))),
    )


def evaluate(history: list[tuple[str, int | None]], th: AlertThresholds) -> str:
    """history: [(estado, latencia_ms)] del más reciente al más antiguo.

    Devuelve 'caida', 'latencia_alta', 'ok' o 'indeterminado' (pocos datos).
    """
    if len(history) >= th.failures and all(e == "sin_respuesta" for e, _ in history[: th.failures]):
        return "caida"
    recent = history[: th.latency_samples]
    if len(recent) >= th.latency_samples and all(
        e == "disponible" and lat is not None and lat > th.latency_ms for e, lat in recent
    ):
        return "latencia_alta"
    if history and history[0][0] == "disponible":
        return "ok"
    return "indeterminado"


def build_message(kind: str, host: str, th: AlertThresholds) -> str:
    if kind == "caida":
        return f"{host}: {th.failures} sondeos consecutivos sin respuesta"
    if kind == "latencia_alta":
        return f"{host}: latencia superior a {th.latency_ms} ms en {th.latency_samples} sondeos"
    return f"{host}: servicio recuperado"


def _post(url: str, payload: dict) -> None:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5):  # noqa: S310 (esquema validado)
        pass


async def send_webhook(payload: dict) -> bool:
    url = os.getenv("ALERT_WEBHOOK_URL", "").strip()
    if not url:
        return False
    if urlparse(url).scheme not in ("http", "https"):
        logger.error("ALERT_WEBHOOK_URL debe usar http o https")
        return False
    try:
        await asyncio.to_thread(_post, url, payload)
        return True
    except Exception:
        logger.exception("No se pudo entregar el webhook de alerta")
        return False
