
from fastapi import FastAPI
from core.logger import setup_logger
from fastapi.middleware.cors import CORSMiddleware
from services.tts_service import set_tts_service
from services.stt_service import set_stt_service
# from routes.tts_router import router as tts_router  # Batch TTS (legacy)
from routes.tts_router_streaming import router as tts_router  # Streaming TTS (experimental)
from routes.stt_router import router as stt_router
from routes.stt_router_2 import router as stt2_router
from routes.llm_router import router as llm_router
from services.llm_service import set_llm_service,get_llm_service

logger = setup_logger("vox.app")

set_tts_service("xtts")
set_stt_service("faster_whisper")
set_llm_service("qwen")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # allow all for testing
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tts_router, prefix="/tts")  # Using streaming router
app.include_router(stt_router, prefix="/stt")
app.include_router(llm_router, prefix="/llm")
app.include_router(stt2_router, prefix="/stt2")

@app.on_event("startup")
def startup():
    logger.info("🚀 Vox starting - TTS Mode: Streaming (experimental)")
    llm_service = get_llm_service()
    model_id = llm_service.MODEL_ID
    logger.info("llm service INITIALIZED %s", model_id)
    llm_service.load()
    logger.info("Llm service LOADED %s", model_id)
    logger.info("💡 To revert to batch TTS: comment streaming import, uncomment legacy import in app.py")


