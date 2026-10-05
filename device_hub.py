import json
import queue
import threading

# station_id -> DeviceSession
_sessions = {}
_lock = threading.Lock()


class DeviceSession:
    def __init__(self, station_id, ws):
        self.station_id = station_id
        self.ws = ws
        self.req_queue = queue.Queue()
        self.busy = False
        self.busy_lock = threading.Lock()
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def _worker(self):
        while True:
            browser_ws = self.req_queue.get()
            if browser_ws is None:
                break
            try:
                self._serve(browser_ws)
            except Exception as e:
                try:
                    browser_ws.send(json.dumps({"type": "error", "message": str(e)}))
                except Exception:
                    pass
            finally:
                try:
                    browser_ws.close()
                except Exception:
                    pass
                with self.busy_lock:
                    self.busy = False

    def _serve(self, browser_ws):
        # Ask device for its CSV
        self.ws.send(json.dumps({"type": "give_archive"}))
        browser_ws.send(json.dumps({"type": "start", "station": self.station_id}))

        while True:
            raw = self.ws.receive(timeout=180)
            if raw is None:
                raise Exception("device timeout")
            msg = json.loads(raw)
            t = msg.get("type")

            if t == "archive_chunk":
                browser_ws.send(raw)  # forward as-is
            elif t == "archive_end":
                browser_ws.send(json.dumps({"type": "end"}))
                return
            elif t == "error":
                raise Exception(msg.get("message", "device error"))
            # ignore other messages (heartbeats)

    def is_busy(self):
        with self.busy_lock:
            return self.busy

    def mark_busy(self):
        with self.busy_lock:
            if self.busy:
                return False
            self.busy = True
            return True

    def enqueue(self, browser_ws):
        self.req_queue.put(browser_ws)


def register(station_id, ws):
    with _lock:
        old = _sessions.get(station_id)
        _sessions[station_id] = DeviceSession(station_id, ws)
        return old


def unregister(station_id, ws):
    with _lock:
        sess = _sessions.get(station_id)
        # Only unregister if it's still the same session
        if sess and sess.ws is ws:
            del _sessions[station_id]
            sess.req_queue.put(None)


def get(station_id):
    with _lock:
        return _sessions.get(station_id)


def online_stations():
    with _lock:
        return list(_sessions.keys())