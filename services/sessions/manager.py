from services.sessions.session import InferenceSession

class SessionManager:
    def __init__(self):
        self.sessions: dict[str, InferenceSession] = {}

    def create(self, session_id: str) -> InferenceSession:
        session = InferenceSession(session_id)
        self.sessions[session_id] = session
        return session

    def get(self, session_id: str):
        return self.sessions.get(session_id)

    def cancel(self, session_id: str):
        session = self.sessions.pop(session_id, None)
        if session:
            session.cancel()

    def cleanup(self, session_id: str):
        self.sessions.pop(session_id, None)
