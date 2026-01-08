from services.registry import faster_whisper

_services = {
    "faster_whisper": faster_whisper
}

_current_stt_service = None

def set_stt_service(stt_name: str):
    global _current_stt_service
    if stt_name not in _services:
        raise ValueError(f"Unknown STT service: {stt_name}")
    _current_stt_service = _services[stt_name]


def get_stt_service():
    if _current_stt_service is None:
        raise RuntimeError("STT service not initialized")
    return _current_stt_service
