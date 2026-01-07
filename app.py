
from fastapi import FastAPI
from services.llm.registry import lamma_malverick,qwen
from routes.llm.lamma_malverick_router import router as lammaMaverickRouter
from routes.llm.qwen_route import router as qwenRouter
from core.logger import setup_logger
from fastapi.middleware.cors import CORSMiddleware

logger = setup_logger("vox.app")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # allow all for testing
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(lammaMaverickRouter,prefix="/lammaMaverick")
app.include_router(
    qwenRouter,
    prefix="/qwen",
    tags=["Qwen LLM"],
)

@app.on_event("startup")
def startup():
    logger.info("🚀 Vox starting")
    # lamma_malverick.load()
    qwen.load()
