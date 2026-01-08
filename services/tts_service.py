from services.registry import xtts_v2

_services = {
    "xtts": xtts_v2
}

_current_tts_service = None

def set_tts_service(tts_name: str):
    global _current_tts_service
    if tts_name not in _services:
        raise ValueError(f"Unknown TTS service: {tts_name}")
    _current_tts_service = _services[tts_name]


def get_tts_service():
    if _current_tts_service is None:
        raise RuntimeError("TTS service not initialized")
    return _current_tts_service
