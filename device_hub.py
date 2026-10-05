"""
device_hub.py
Manages connected TG452s + relay of archive requests over WebSocket.
"""
import json
import queue
import threading

_sessions = {}
_lock = threading.Lock()


class DeviceSession:
    def __init__(self, station_id, ws):
        self.station_id = station_id
        self.ws = ws
        self.browser_streams = []
        self.browser_lock = threading.Lock()
        self.sync_exports = []
        self.sync_lock = threading.Lock()
        self.thread = threading.Thread(target=self._reader, daemon=True)
        self.thread.start()

    def _reader(self):
        while True:
            try:
                raw = self.ws.receive(timeout=300)
            except Exception:
                break
            if raw is None:
                break
            try:
                msg = json.loads(raw)
            except Exception:
                continue

            t = msg.get("type")

            if t == "archive_chunk":
                with self.browser_lock:
                    for bws in list(self.browser_streams):
                        try:
                            bws.send(raw)
                        except Exception:
                            pass
                with self.sync_lock:
                    for exp in list(self.sync_exports):
                        try:
                            exp["queue"].put(("chunk", msg.get("data", "")))
                        except Exception:
                            pass

            elif t == "archive_end":
                with self.browser_lock:
                    for bws in list(self.browser_streams):
                        try:
                            bws.send(json.dumps({"type": "archive_end", "size": msg.get("size", 0)}))
                        except Exception:
                            pass
                        try:
                            bws.close()
                        except Exception:
                            pass
                    self.browser_streams.clear()
                with self.sync_lock:
                    for exp in list(self.sync_exports):
                        try:
                            exp["queue"].put(("end", msg.get("size", 0)))
                        except Exception:
                            pass
                    self.sync_exports.clear()

            elif t == "error":
                err = msg.get("message", "unknown error")
                with self.browser_lock:
                    for bws in list(self.browser_streams):
                        try:
                            bws.send(json.dumps({"type": "error", "message": err}))
                        except Exception:
                            pass
                        try:
                            bws.close()
                        except Exception:
                            pass
                    self.browser_streams.clear()
                with self.sync_lock:
                    for exp in list(self.sync_exports):
                        try:
                            exp["queue"].put(("error", err))
                        except Exception:
                            pass
                    self.sync_exports.clear()

    def add_browser_streamer(self, browser_ws):
        with self.browser_lock:
            self.browser_streams.append(browser_ws)

    def remove_browser_streamer(self, browser_ws):
        with self.browser_lock:
            if browser_ws in self.browser_streams:
                self.browser_streams.remove(browser_ws)

    def start_sync_export(self):
        q = queue.Queue()
        with self.sync_lock:
            self.sync_exports.append({"queue": q})
        try:
            self.ws.send(json.dumps({"type": "give_archive"}))
        except Exception as e:
            raise RuntimeError(f"failed to send give_archive: {e}")
        return q


def register(station_id, ws):
    with _lock:
        old = _sessions.get(station_id)
        _sessions[station_id] = DeviceSession(station_id, ws)
        return old


def unregister(station_id, ws):
    with _lock:
        sess = _sessions.get(station_id)
        if sess and sess.ws is ws:
            del _sessions[station_id]


def get(station_id):
    with _lock:
        return _sessions.get(station_id)


def online_stations():
    with _lock:
        return list(_sessions.keys())