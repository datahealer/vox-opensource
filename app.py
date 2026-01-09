
from fastapi import FastAPI
from core.logger import setup_logger
from fastapi.middleware.cors import CORSMiddleware
from services.tts_service import set_tts_service
from services.stt_service import set_stt_service
from routes.tts_router import router as tts_router
from routes.stt_router import router as stt_router

logger = setup_logger("vox.app")

set_tts_service("xtts")
set_stt_service("faster_whisper")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # allow all for testing
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tts_router, prefix="/tts")
app.include_router(stt_router, prefix="/stt")

@app.on_event("startup")
def startup():
    logger.info("🚀 Vox starting STT AND TTS")
   
    
