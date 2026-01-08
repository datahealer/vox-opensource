from sessions.session import LLMSession
import threading

class LLMSessionManager:
    def __init__(self):
        self._sessions: dict[str, LLMSession] = {}
        self._lock = threading.Lock()

    def create(self, session_id: str) -> LLMSession:
        with self._lock:
            session = LLMSession(session_id)
            self._sessions[session_id] = session
            return session

    def get(self, session_id: str) -> LLMSession | None:
        return self._sessions.get(session_id)

    def cancel(self, session_id: str):
        session = self.get(session_id)
        if session:
            session.cancel()

    def cleanup(self, session_id: str):
        with self._lock:
            self._sessions.pop(session_id, None)

    @property
    def active(self) -> int:
        return len(self._sessions)
