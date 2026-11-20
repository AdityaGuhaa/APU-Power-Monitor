"""
APU-Power-Monitor - Real-time integrated-graphics telemetry
Copyright (c) 2026 Aditya Guha
Licensed under the MIT License. See LICENSE file in the project root.

Flask + Socket.IO server. Streams normalized APU metrics to the browser over a
WebSocket at a configurable cadence (500 ms by default).

Async model: Socket.IO runs in `threading` mode, so the sampling loop is a real
OS thread. Hardware reads can block for as long as they like without stalling
the server's event loop, and no eventlet/gevent monkey-patching is needed.
"""

import atexit

from flask import Flask, jsonify, render_template
from flask_socketio import SocketIO, emit

import config
from apumon import __version__
from apumon.monitor import Monitor
from apumon.providers import select_provider

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.config["SECRET_KEY"] = config.SECRET_KEY

_socketio_options = {"async_mode": "threading"}
if config.CORS_ORIGINS:
    # Comma-separated list, or "*" to allow any origin. Default is same-origin.
    origins = config.CORS_ORIGINS.strip()
    _socketio_options["cors_allowed_origins"] = (
        "*" if origins == "*" else [o.strip() for o in origins.split(",") if o.strip()]
    )

socketio = SocketIO(app, **_socketio_options)

# ---------------------------------------------------------------------------
# Telemetry
# ---------------------------------------------------------------------------
provider = select_provider(name=config.PROVIDER, mock=config.MOCK_MODE)

monitor = Monitor(
    socketio,
    provider,
    interval_ms=config.POLL_INTERVAL_MS,
    idle_when_no_clients=config.IDLE_WHEN_NO_CLIENTS,
    power_limit=config.POWER_LIMIT_W,
    power_max_limit=config.POWER_MAX_LIMIT_W,
)

# Started at import, not inside __main__, so the stream also works when the
# app is served by gunicorn/waitress rather than `python app.py`.
monitor.start()
atexit.register(monitor.stop)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    """The dashboard."""
    return render_template(
        "index.html",
        version=__version__,
        history_seconds=config.HISTORY_SECONDS,
        interval_ms=config.POLL_INTERVAL_MS,
    )


@app.route("/api/meta")
def api_meta():
    """Stream description: provider, cadence, configured power envelope."""
    meta = monitor.meta()
    meta.update(
        {
            "version": __version__,
            "history_seconds": config.HISTORY_SECONDS,
            "history_points": config.history_points(),
            "clients": monitor.clients,
        }
    )
    return jsonify(meta)


@app.route("/api/snapshot")
def api_snapshot():
    """
    One reading over plain HTTP. Useful for scripting, smoke tests and health
    checks without opening a WebSocket.
    """
    payload = monitor.sample_once() or monitor.latest()
    if payload is None:
        return jsonify({"error": f"No data from provider '{provider.name}'."}), 503
    return jsonify(payload)


# ---------------------------------------------------------------------------
# Socket.IO events
# ---------------------------------------------------------------------------
@socketio.on("connect")
def handle_connect():
    count = monitor.client_connected()
    emit("apu_meta", monitor.meta())
    # Send the last known sample so the dashboard is populated immediately
    # instead of staying blank until the next tick.
    last = monitor.latest()
    if last is not None:
        emit("apu_data", last)
    print(f"[INFO] Client connected ({count} active).")


@socketio.on("disconnect")
def handle_disconnect(*_args):
    count = monitor.client_disconnected()
    print(f"[INFO] Client disconnected ({count} active).")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def _banner():
    settings = config.summary()
    width = 62
    print("=" * width)
    print(f"  APU-Power-Monitor v{__version__}")
    print(f"  Provider : {provider.name} - {provider.description}")
    print(f"  Sampling : every {settings['interval_ms']} ms, "
          f"{settings['history_seconds']} s window "
          f"({settings['history_points']} points)")
    if settings["power_limit_w"]:
        print(f"  Envelope : {settings['power_limit_w']} W sustained, "
              f"{settings['power_max_limit_w'] or settings['power_limit_w']} W max")
    else:
        print("  Envelope : not configured (power axis auto-scales) - "
              "set APU_POWER_LIMIT_W")
    print(f"  Dashboard: http://{settings['host']}:{settings['port']}")
    print("=" * width)


if __name__ == "__main__":
    _banner()
    try:
        socketio.run(
            app,
            host=config.HOST,
            port=config.PORT,
            debug=False,
            # This is a local, loopback-bound dashboard, so the Werkzeug server
            # is the right tool. Put it behind waitress/gunicorn if you expose
            # it beyond localhost.
            allow_unsafe_werkzeug=True,
        )
    except KeyboardInterrupt:
        print("\n[INFO] Shutting down.")
    finally:
        monitor.stop()
