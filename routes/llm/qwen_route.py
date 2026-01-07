from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from transformers import TextIteratorStreamer
import threading
from models.llm.llm_model import GenerateRequest
from services.llm.registry import qwen
from services.sessions.registry import session_manager
from core.logger import setup_logger

logger = setup_logger("vox.route.llm.qwen")

router = APIRouter()


MODEL_ID = "Qwen/Qwen2.5-1.5B-Instruct"

@router.post("/generate")
def generate(req: GenerateRequest):
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")

    try:
        return qwen.generate_response(
            prompt=req.prompt,
            max_new_tokens=req.max_new_tokens,
            temperature=req.temperature,
            top_p=req.top_p,
        )
    except Exception as e:
        logger.exception("Qwen generate error")
        raise HTTPException(status_code=500, detail=str(e))
    
    
@router.websocket("/stream-with-session")
async def llm_stream(ws: WebSocket):
    await ws.accept()

    try:
        data = await ws.receive_json()
        session_id = data["session_id"]
        prompt = data["prompt"]

        session = session_manager.create(session_id)

        streamer = TextIteratorStreamer(
            qwen.tokenizer,
            skip_prompt=True,
            skip_special_tokens=True,
        )

        messages = [
            {"role": "system", "content": "You are Qwen, a helpful assistant."},
            {"role": "user", "content": prompt},
        ]

        text_prompt = qwen.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )

        inputs = qwen.tokenizer([text_prompt], return_tensors="pt")
        inputs = {k: v.to(qwen.model.device) for k, v in inputs.items()}

        generation_kwargs = dict(
            **inputs,
            max_new_tokens=data.get("max_new_tokens", 512),
            temperature=data.get("temperature", 0.7),
            top_p=data.get("top_p", 0.9),
            do_sample=True,
        )

        def run():
            qwen.generate_stream(session, streamer, generation_kwargs)

        threading.Thread(target=run, daemon=True).start()

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
@router.post("/session/{session_id}/cancel")
def cancel_session(session_id: str):
    session_manager.cancel(session_id)
    return {"status": "cancelled"}
@router.get("/health")
def health():
    return {
        "status": "ok",
        "model_loaded": qwen.model is not None,
        "model_id": MODEL_ID,
        "device": str(qwen.model.device),
        "active_sessions": len(session_manager.sessions),
    }
