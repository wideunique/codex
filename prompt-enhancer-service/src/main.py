from __future__ import annotations

import argparse
import logging
import signal
import sys
from typing import Optional

import uvicorn

from .app import create_app
from .config import load_config, parse_host_port


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Prompt Enhancer Service (Python)")
    parser.add_argument("--config", default="", help="path to YAML config file")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    try:
        cfg = load_config(args.config)
    except Exception as e:
        logging.getLogger("bootstrap").error("failed to load config: %s", e)
        return 1

    app = create_app(cfg)
    host, port = parse_host_port(cfg.server.address)
    logging.getLogger("bootstrap").info("starting prompt enhancer service", extra={"address": cfg.server.address})

    # Map write timeout to uvicorn's timeout-keep-alive as a rough analogue.
    # Starlette/uvicorn do not provide per-request write timeouts directly.
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=host,
            port=port,
            timeout_keep_alive=int(max(5, cfg.server.write_timeout_s)),
            log_level="info",
        )
    )

    # Graceful shutdown is handled by uvicorn; just run.
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
