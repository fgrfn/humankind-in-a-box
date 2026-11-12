"""Run the API with uvicorn, in its own process next to the worker."""

from __future__ import annotations

import multiprocessing
from multiprocessing.process import BaseProcess
from pathlib import Path
from typing import Any

from hiab.config import Settings
from hiab.logging_setup import get_logger, setup_logging

log = get_logger("api")


def serve(settings_data: dict[str, Any], db_path: str) -> None:
    """Entry point of the API process. Takes plain data so it works with 'spawn'."""
    import uvicorn

    from hiab.api.app import create_app
    from hiab.packs import load_packs

    settings = Settings.model_validate(settings_data)
    setup_logging(
        settings.log_level,
        settings.log_levels,
        settings.data_dir / "logs" if settings.log_to_file else None,
    )
    packs = load_packs(settings.packs, settings.data_dir)
    app = create_app(
        Path(db_path),
        packs,
        settings.language,
        data_dir=settings.data_dir,
        api_token=settings.api_token,
        pace=settings.pace,
    )
    log.info("api listening", extra={"bind": settings.bind, "port": settings.port})
    uvicorn.run(app, host=settings.bind, port=settings.port, log_level="warning", access_log=False)


def start_api_process(settings: Settings, db_path: Path) -> BaseProcess:
    # model_dump keeps the real secrets: the child needs them, and nothing is printed here.
    context = multiprocessing.get_context("spawn")
    process = context.Process(
        target=serve,
        args=(settings.model_dump(mode="json"), str(db_path)),
        name="hiab-api",
        daemon=True,
    )
    process.start()
    return process
