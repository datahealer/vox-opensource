from llm_services.lamma_malverick_service import LammaMaverick
from llm_services.Qwen2_5_service import QwenService

lamma_malverick = LammaMaverick()
qwen = QwenService()

_services = {
    "lammaMaverick": lamma_malverick,
    "qwen": qwen
}

_current_llm_service = None

def set_llm_service(llm_name: str):
    global _current_llm_service
    if llm_name not in _services:
        raise ValueError(f"Unknown LLM service: {llm_name}")
    _current_llm_service = _services[llm_name]


def get_llm_service():
    if _current_llm_service is None:
        raise RuntimeError("LLM service not initialized")
    return _current_llm_service
