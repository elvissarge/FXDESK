"""FastAPI application exposing fxdesk research and paper-trading features."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from fxdesk.config import load_config
from fxdesk.data import DataService
from fxdesk.errors import FxDeskError
from fxdesk.strategies.registry import strategy_names
from fxdesk.symbols import KNOWN, known_symbols
from fxdesk.timeframes import supported_timeframes
from fxdesk.web.jobs import JobManager
from fxdesk.web.paper import PaperSession
from fxdesk.web.serialize import jsonable
from fxdesk.web.services import (
    run_backtest,
    run_data_fetch,
    run_signals,
    run_walkforward,
)

VERSION = "0.1.0"


class BacktestRequest(BaseModel):
    symbol: str = "EURUSD"
    timeframe: str = "1h"
    strategy: str = "composite"
    start: str | None = None
    end: str | None = None
    provider: str | None = None
    balance: float | None = None
    spread: float | None = None
    commission: float | None = None
    slippage: float | None = None
    risk: float | None = None
    monte_carlo: int | None = None
    seed: int = 0
    refresh: bool = False
    use_cache: bool = True
    save: bool = False
    plot: bool = False
    output_dir: str = "reports"


class WalkForwardRequest(BacktestRequest):
    strategy: str = "trend_ma"
    grid: dict[str, list[Any]] | None = None
    train_bars: int | None = None
    test_bars: int | None = None
    step_bars: int | None = None
    objective: str | None = None
    min_train_trades: int | None = None
    max_combinations: int | None = None


class SignalsRequest(BaseModel):
    symbols: str | list[str] = "EURUSD,GBPUSD,USDJPY"
    timeframe: str = "1h"
    strategies: str | list[str] = "composite"
    equity: float | None = None
    live: bool = False
    allow_continuation: bool = True
    max_plans: int | None = None


class DataFetchRequest(BaseModel):
    symbol: str = "EURUSD"
    timeframe: str = "1d"
    start: str | None = None
    end: str | None = None
    provider: str | None = None
    refresh: bool = False
    use_cache: bool = True
    limit: int = Field(default=500, ge=1, le=5000)


class PaperStartRequest(BaseModel):
    symbols: str | list[str] = "EURUSD,GBPUSD"
    timeframe: str = "1h"
    strategies: str | list[str] = "composite"
    poll_seconds: float = Field(default=15.0, ge=1.0)
    allow_continuation: bool = False
    state_file: str | None = None
    initial_balance: float | None = None
    reset: bool = False


class PaperResetRequest(BaseModel):
    state_file: str | None = None


def _config_from_env() -> dict[str, Any]:
    return load_config(os.environ.get("FXDESK_CONFIG") or None)


def _handle_sync(func, config: dict[str, Any], params: dict[str, Any]):
    try:
        return func(config, params)
    except FxDeskError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def create_app(config: dict[str, Any] | None = None) -> FastAPI:
    app = FastAPI(
        title="fxdesk API",
        version=VERSION,
        description="Research, backtesting, walk-forward and paper trading.",
    )
    app.state.config = config or _config_from_env()
    workers = int(os.environ.get("FXDESK_WEB_WORKERS", "2"))
    app.state.jobs = JobManager(max_workers=workers)
    app.state.paper = PaperSession(app.state.config)

    origins = [
        origin.strip()
        for origin in os.environ.get(
            "FXDESK_WEB_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
        ).split(",")
        if origin.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    token = os.environ.get("FXDESK_WEB_TOKEN", "")

    @app.middleware("http")
    async def api_token(request: Request, call_next):
        if token and request.url.path not in ("/health", "/api/health"):
            supplied = request.headers.get("x-api-key", "")
            if not supplied:
                authorization = request.headers.get("authorization", "")
                if authorization.lower().startswith("bearer "):
                    supplied = authorization[7:]
            if supplied != token:
                return JSONResponse(
                    status_code=401, content={"detail": "invalid or missing API token"}
                )
        return await call_next(request)

    @app.on_event("shutdown")
    def _shutdown() -> None:
        app.state.paper.shutdown()
        app.state.jobs.shutdown()

    router = APIRouter(prefix="/api")

    @router.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": "fxdesk-api", "version": VERSION}

    @router.get("/meta")
    def meta(request: Request) -> dict[str, Any]:
        cfg = request.app.state.config
        service = DataService(cfg)
        try:
            providers = service.provider_status()
        except Exception:
            providers = {}
        return {
            "version": VERSION,
            "strategies": strategy_names(),
            "timeframes": supported_timeframes(),
            "symbols": known_symbols(),
            "providers": providers,
            "account": cfg.get("account", {}),
            "backtest": cfg.get("backtest", {}),
            "walkforward": cfg.get("walkforward", {}),
            "paper": cfg.get("paper", {}),
            "strategy_params": cfg.get("strategies", {}),
        }

    @router.get("/strategies")
    def strategies(request: Request) -> dict[str, Any]:
        return jsonable(request.app.state.config.get("strategies", {}))

    @router.get("/symbols")
    def symbols() -> list[dict[str, Any]]:
        return [
            {
                "symbol": spec.symbol,
                "base": spec.base,
                "quote": spec.quote,
                "digits": spec.digits,
                "pip_size": spec.pip_size,
                "contract_size": spec.contract_size,
                "kind": spec.kind,
            }
            for spec in (KNOWN[code] for code in known_symbols())
        ]

    @router.get("/providers")
    def providers(request: Request) -> dict[str, bool]:
        try:
            return DataService(request.app.state.config).provider_status()
        except Exception:
            return {}

    @router.get("/timeframes")
    def timeframes() -> list[str]:
        return supported_timeframes()

    @router.post("/backtest", status_code=202)
    def backtest(request: Request, payload: BacktestRequest) -> dict[str, Any]:
        params = payload.model_dump()
        job_id = request.app.state.jobs.submit(
            "backtest", run_backtest, request.app.state.config, params, params=params
        )
        return {"job_id": job_id, "status": "queued"}

    @router.post("/walkforward", status_code=202)
    def walkforward(request: Request, payload: WalkForwardRequest) -> dict[str, Any]:
        params = payload.model_dump()
        job_id = request.app.state.jobs.submit(
            "walkforward", run_walkforward, request.app.state.config, params, params=params
        )
        return {"job_id": job_id, "status": "queued"}

    @router.get("/jobs")
    def jobs(request: Request, limit: int = 50) -> list[dict[str, Any]]:
        return request.app.state.jobs.list(limit=limit)

    @router.get("/jobs/{job_id}")
    def job(request: Request, job_id: str) -> dict[str, Any]:
        payload = request.app.state.jobs.get(job_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="job not found")
        return payload

    @router.post("/signals")
    def signals(request: Request, payload: SignalsRequest) -> dict[str, Any]:
        return _handle_sync(
            run_signals, request.app.state.config, payload.model_dump()
        )

    @router.post("/data/fetch")
    def data_fetch(request: Request, payload: DataFetchRequest) -> dict[str, Any]:
        return _handle_sync(
            run_data_fetch, request.app.state.config, payload.model_dump()
        )

    @router.get("/paper/status")
    def paper_status(request: Request, state_file: str | None = None) -> dict[str, Any]:
        return request.app.state.paper.status(state_file)

    @router.post("/paper/start", status_code=202)
    def paper_start(request: Request, payload: PaperStartRequest) -> dict[str, Any]:
        try:
            return request.app.state.paper.start(payload.model_dump())
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/paper/stop")
    def paper_stop(request: Request) -> dict[str, Any]:
        return request.app.state.paper.stop()

    @router.post("/paper/cycle")
    def paper_cycle(
        request: Request, payload: PaperStartRequest | None = None
    ) -> dict[str, Any]:
        try:
            return request.app.state.paper.cycle(
                payload.model_dump() if payload else None
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except FxDeskError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/paper/reset")
    def paper_reset(request: Request, payload: PaperResetRequest) -> dict[str, Any]:
        try:
            return request.app.state.paper.reset(payload.state_file)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    app.include_router(router)

    @app.get("/health")
    def root_health() -> dict[str, Any]:
        return {"status": "ok", "service": "fxdesk-api", "version": VERSION}

    return app


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run(
        "fxdesk.web.app:app",
        host=os.environ.get("FXDESK_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("FXDESK_API_PORT", "8000")),
        reload=os.environ.get("FXDESK_API_RELOAD", "").lower() in ("1", "true", "yes"),
    )


if __name__ == "__main__":
    main()
