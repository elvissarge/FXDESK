"""Paper-trading session manager used by the web API."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fxdesk.brokers.paper import PaperBroker
from fxdesk.data import DataService
from fxdesk.live.feed import build_feed
from fxdesk.live.runner import PaperRunner
from fxdesk.web.serialize import jsonable

logger = logging.getLogger(__name__)


def _as_list(value: Any, default: list[str]) -> list[str]:
    if value is None:
        return list(default)
    if isinstance(value, str):
        items = [part.strip() for part in value.split(",") if part.strip()]
    else:
        items = [str(part).strip() for part in value if str(part).strip()]
    return items or list(default)


def load_paper_state(path: str | Path, config: dict[str, Any]) -> dict[str, Any]:
    initial = float(
        config.get("paper", {}).get(
            "initial_balance",
            config.get("account", {}).get("initial_balance", 10000.0),
        )
    )
    currency = str(config.get("account", {}).get("currency", "USD"))
    target = Path(path)

    balance = initial
    realized = 0.0
    positions: list[dict[str, Any]] = []
    closed: list[dict[str, Any]] = []

    if target.exists():
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            balance = float(data.get("balance", initial))
            realized = float(data.get("realized_pnl", 0.0))
            positions = list(data.get("positions", []))
            closed = list(data.get("closed", []))
        except (OSError, ValueError, TypeError):
            logger.warning("could not read paper state file %s", target)

    unrealized = sum(float(item.get("profit", 0.0) or 0.0) for item in positions)
    equity = balance + unrealized

    return {
        "state_file": str(target),
        "account": {
            "balance": round(balance, 2),
            "equity": round(equity, 2),
            "realized_pnl": round(realized, 2),
            "currency": currency,
        },
        "positions": jsonable(positions),
        "closed": jsonable(closed[-100:]),
        "closed_count": len(closed),
    }


class PaperSession:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._params: dict[str, Any] | None = None
        self._cycles = 0
        self._last_cycle: str | None = None
        self._error: str | None = None

    @property
    def default_state_file(self) -> str:
        return str(
            self.config.get("paper", {}).get("state_file", "paper_state.json")
        )

    def running(self) -> bool:
        thread = self._thread
        return bool(thread is not None and thread.is_alive())

    def _normalize(self, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "symbols": [
                item.upper()
                for item in _as_list(
                    params.get("symbols") or params.get("symbol"),
                    ["EURUSD", "GBPUSD"],
                )
            ],
            "timeframe": str(params.get("timeframe") or "1h"),
            "strategies": _as_list(
                params.get("strategies") or params.get("strategy"),
                ["composite"],
            ),
            "poll_seconds": float(params.get("poll_seconds") or 15),
            "allow_continuation": bool(params.get("allow_continuation", False)),
            "state_file": str(params.get("state_file") or self.default_state_file),
            "initial_balance": params.get("initial_balance"),
            "reset": bool(params.get("reset", False)),
        }

    def _build_runner(self, params: dict[str, Any]):
        broker = PaperBroker(self.config, initial_balance=params.get("initial_balance"))
        data = DataService(self.config)
        feed = build_feed(self.config, data=data)
        runner = PaperRunner(
            self.config,
            broker=broker,
            feed=feed,
            data=data,
            state_file=params["state_file"],
        )
        return broker, feed, runner

    def start(self, params: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize(params)
        with self._lock:
            if self.running():
                raise RuntimeError("paper session is already running")

            if normalized["reset"]:
                Path(normalized["state_file"]).unlink(missing_ok=True)

            self._params = normalized
            self._stop.clear()
            self._error = None
            self._cycles = 0
            self._last_cycle = None
            self._thread = threading.Thread(
                target=self._loop,
                args=(normalized,),
                name="fxdesk-paper",
                daemon=True,
            )
            self._thread.start()

        return self.status()

    def _loop(self, params: dict[str, Any]) -> None:
        broker = feed = None
        try:
            broker, feed, runner = self._build_runner(params)
            while not self._stop.is_set():
                runner.cycle(
                    params["symbols"],
                    params["timeframe"],
                    params["strategies"],
                    allow_continuation=params["allow_continuation"],
                )
                with self._lock:
                    self._cycles += 1
                    self._last_cycle = datetime.now(timezone.utc).isoformat()
                self._stop.wait(max(params["poll_seconds"], 1.0))
        except Exception as exc:  # noqa: BLE001 - reported through status
            logger.exception("paper session failed")
            with self._lock:
                self._error = str(exc)
        finally:
            if broker is not None:
                broker.save_state(params["state_file"])
            if feed is not None:
                feed.close()
            with self._lock:
                self._thread = None

    def stop(self) -> dict[str, Any]:
        with self._lock:
            thread = self._thread
        self._stop.set()
        if thread is not None:
            thread.join(timeout=10.0)
        return self.status()

    def cycle(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            if self.running():
                raise RuntimeError("paper session is running; stop it before a manual cycle")
            normalized = self._normalize(params) if params else self._params

        if normalized is None:
            raise RuntimeError("paper session is not configured; start it or pass parameters")

        if normalized["reset"]:
            Path(normalized["state_file"]).unlink(missing_ok=True)

        broker, feed, runner = self._build_runner(normalized)
        try:
            opened = runner.cycle(
                normalized["symbols"],
                normalized["timeframe"],
                normalized["strategies"],
                allow_continuation=normalized["allow_continuation"],
            )
        finally:
            broker.save_state(normalized["state_file"])
            feed.close()

        self._params = normalized
        self._last_cycle = datetime.now(timezone.utc).isoformat()
        return {
            "opened": [jsonable(plan.to_dict()) for plan in opened],
            "status": self.status(normalized["state_file"]),
        }

    def reset(self, state_file: str | None = None) -> dict[str, Any]:
        with self._lock:
            if self.running():
                raise RuntimeError("stop the paper session before resetting")
            target = Path(state_file or self.default_state_file)
            existed = target.exists()
            target.unlink(missing_ok=True)
        return {"state_file": str(target), "removed": existed}

    def status(self, state_file: str | None = None) -> dict[str, Any]:
        with self._lock:
            params = self._params
            target = (
                state_file
                or (params or {}).get("state_file")
                or self.default_state_file
            )
            state = load_paper_state(target, self.config)
            state.update(
                {
                    "running": self.running(),
                    "params": jsonable(params),
                    "cycles": self._cycles,
                    "last_cycle": self._last_cycle,
                    "error": self._error,
                }
            )
            return state

    def shutdown(self) -> None:
        try:
            self.stop()
        except Exception:
            logger.debug("paper session shutdown failed", exc_info=True)
