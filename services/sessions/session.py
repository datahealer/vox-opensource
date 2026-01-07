import threading
import time

class InferenceSession:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.cancel_event = threading.Event()
        self.started_at = time.time()

    def cancel(self):
        self.cancel_event.set()
