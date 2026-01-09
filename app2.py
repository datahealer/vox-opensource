
from fastapi import FastAPI
from core.logger import setup_logger
from fastapi.middleware.cors import CORSMiddleware
from services.llm_service import set_llm_service,get_llm_service
from routes.llm_router import router as llm_router


logger = setup_logger("vox.app")

set_llm_service("qwen")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # allow all for testing
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(llm_router, prefix="/llm")

@app.on_event("startup")
def startup():
    logger.info("🚀 Vox starting LLLM")
    llm_service = get_llm_service()
    model_id = llm_service.MODEL_ID
    logger.info("llm service INITIALIZED %s", model_id)
    llm_service.load()
    logger.info("Llm service LOADED %s", model_id)
    
