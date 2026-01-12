from llm_services.lamma_malverick_service import LammaMaverick
from llm_services.Qwen2_5_service import QwenService
from tts_services.xttx_v2_service import XTTSService
from stt_services.faster_whisper_service import WhisperSTTService

lamma_malverick = LammaMaverick()
qwen = QwenService()
xtts_v2 = XTTSService()
faster_whisper = WhisperSTTService()

