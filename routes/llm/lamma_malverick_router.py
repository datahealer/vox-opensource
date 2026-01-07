from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from models.llm.llm_model import GenerateRequest
from services.llm.registry import lamma_malverick
from transformers import TextIteratorStreamer
import threading
from core.logger import setup_logger
from services.sessions.registry import session_manager


logger = setup_logger("vox.route.llm.malverick")
router = APIRouter()

MODEL_ID = "meta-llama/Llama-4-Maverick-17B-128E-Instruct"

## GENERATE AND RETURNS LLM RESPONSE
@router.post("/generate")
def generate(req: GenerateRequest):
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")

    try:
        return lamma_malverick.generate_response(
            prompt=req.prompt,
            max_new_tokens=req.max_new_tokens,
            temperature=req.temperature,
            top_p=req.top_p,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


## WEBSOCKET FOR LLM RESPONSE STREAM WITH SESSION MANAGEMENT
@router.websocket("/stream-with-session")
async def llm_stream(ws: WebSocket):
    await ws.accept()

    data = await ws.receive_json()
    session_id = data["session_id"]
    prompt = data["prompt"]

    session = session_manager.create(session_id)

    streamer = TextIteratorStreamer(
        lamma_malverick.processor,
        skip_prompt=True,
        skip_special_tokens=True,
    )

    inputs = lamma_malverick.processor(prompt, return_tensors="pt")
    inputs = {k: v.to(lamma_malverick.model.device) for k, v in inputs.items()}

    generation_kwargs = dict(
        **inputs,
        max_new_tokens=data.get("max_new_tokens", 512),
        temperature=data.get("temperature", 0.7),
        top_p=data.get("top_p", 0.9),
        do_sample=True,
    )

    def run():
        lamma_malverick.generate_stream(session, streamer, generation_kwargs)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    try:
        for token in streamer:
            if session.cancel_event.is_set():
                break
            await ws.send_text(token)
    except WebSocketDisconnect:
        session_manager.cancel(session_id)
    finally:
        session_manager.cleanup(session_id)
        if ws.client_state.name != "DISCONNECTED":
            await ws.close()


## CANCEL LLM SESSION
@router.post("/session/{session_id}/cancel")
def cancel_session(session_id: str):
    session_manager.cancel(session_id)
    return {"status": "cancelled"}


@router.get("/health")
def health():
    return {
        "status": "ok",
        "model_loaded": lamma_malverick.model is not None,
        "device": "cuda",
        "active_sessions": len(session_manager.sessions),
    }
