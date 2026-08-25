from __future__ import annotations

import signal
import threading
import time
from http.server import ThreadingHTTPServer
from typing import Callable

from history_broker import HistoryBroker


SHUTDOWN_JOIN_SECONDS = 5.0


def log(message: str) -> None:
    print(
        f"{time.strftime('%Y-%m-%d %H:%M:%S')} [CORE] {message}",
        flush=True,
    )


def build_servers():
    import prompt_ui
    import suggestion_bridge

    servers = []
    try:
        servers.append(
            (
                "control-center",
                ThreadingHTTPServer(
                    (prompt_ui.HOST, prompt_ui.PORT),
                    prompt_ui.Handler,
                ),
            )
        )
        servers.append(
            (
                "suggestion-bridge",
                ThreadingHTTPServer(
                    (
                        suggestion_bridge.HOST,
                        suggestion_bridge.PORT,
                    ),
                    suggestion_bridge.Handler,
                ),
            )
        )
        return servers
    except Exception:
        for _name, server in servers:
            try:
                server.server_close()
            except Exception:
                pass
        raise


def _run_component(
    name: str,
    target: Callable[[], None],
    stop_event: threading.Event,
    failure_event: threading.Event,
) -> None:
    try:
        target()
    except BaseException as exc:
        if not stop_event.is_set():
            log(
                f"{name} failed: "
                f"{type(exc).__name__}: {exc}"
            )
            failure_event.set()
    finally:
        if not stop_event.is_set():
            log(f"{name} stopped unexpectedly")
            failure_event.set()


def main() -> int:
    import worker

    stop_event = threading.Event()
    failure_event = threading.Event()

    broker = HistoryBroker()
    servers = []
    threads: list[threading.Thread] = []
    server_threads: list[threading.Thread] = []
    exit_code = 0

    def request_stop(signum, _frame):
        log(f"received signal {signum}; shutting down")
        stop_event.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    try:
        # One persistent process owns the lightweight History broker.
        # The scientific History engine remains a disposable subprocess.
        broker.start()

        servers = build_servers()

        worker_thread = threading.Thread(
            target=_run_component,
            args=(
                "metadata-worker",
                lambda: worker.main(
                    stop_event=stop_event,
                    manage_history_broker=False,
                ),
                stop_event,
                failure_event,
            ),
            name="metadata-worker",
            daemon=True,
        )
        threads.append(worker_thread)

        for name, server in servers:
            thread = threading.Thread(
                target=_run_component,
                args=(
                    name,
                    lambda server=server: server.serve_forever(
                        poll_interval=0.5
                    ),
                    stop_event,
                    failure_event,
                ),
                name=name,
                daemon=True,
            )
            threads.append(thread)
            server_threads.append(thread)

        for thread in threads:
            thread.start()

        log(
            "unified core ready: metadata worker + Control Center + "
            "suggestion bridge + History broker"
        )

        while not stop_event.wait(0.5):
            dead = [
                thread.name
                for thread in threads
                if not thread.is_alive()
            ]
            if dead:
                log(
                    "component thread stopped unexpectedly: "
                    + ", ".join(dead)
                )
                failure_event.set()

            if failure_event.is_set():
                exit_code = 1
                stop_event.set()
                break

    finally:
        stop_event.set()

        # serve_forever() runs in dedicated threads, so shutdown() is safe.
        for (_, server), thread in zip(
            servers,
            server_threads,
        ):
            if thread.is_alive():
                try:
                    server.shutdown()
                except Exception as exc:
                    log(
                        "HTTP shutdown warning: "
                        f"{type(exc).__name__}: {exc}"
                    )

        for _, server in servers:
            try:
                server.server_close()
            except Exception:
                pass

        for thread in threads:
            thread.join(timeout=SHUTDOWN_JOIN_SECONDS)

        broker.stop()

        alive = [
            thread.name
            for thread in threads
            if thread.is_alive()
        ]
        if alive:
            log(
                "components still active during final shutdown: "
                + ", ".join(alive)
            )

        log("unified core stopped")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
