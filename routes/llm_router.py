from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sessions.registry import llm_session_manager
from fastapi import WebSocket, WebSocketDisconnect
from core.logger import setup_logger

router = APIRouter()
logger = setup_logger("vox.route.llm.websocket")


@router.get("/health")
def health():
    from services.llm_service import get_llm_service
    llm_service = get_llm_service()
    return {
        "status": "ok",
        "model": llm_service.model_name,
        "active_sessions": len(llm_session_manager.sessions),
    }


@router.post("/generate")
def generate(req):
    from services.llm_service import get_llm_service
    llm_service = get_llm_service()
    if not req.prompt.strip():
        raise HTTPException(400, "Prompt cannot be empty")

    text = llm_service.generate(
        prompt=req.prompt,
        max_new_tokens=req.max_new_tokens,
        temperature=req.temperature,
        top_p=req.top_p,
    )

    return {"text": text}


@router.websocket("/stream")
async def generate_stream_ws(ws: WebSocket):
    from services.llm_service import get_llm_service
    llm_service = get_llm_service()

    await ws.accept()
    logger.info("LLM WS accepted, waiting for first message")

    session = None
    tokens_generated = 0
    closed = False

    try:
        data = await ws.receive_json()
        logger.info("LLM WS received: %s", data.keys())
        if data.get("type") =="cancel":
            await ws.send_json({
                "type":"cancelled",
                "reason":"call_ended",
                "token_generated":tokens_generated
            })

        elif data.get("type") != "request":
            await ws.close(code=1003)
            closed = True
            return

        session_id = data["session_id"]
        messages = data["messages"]

        session = llm_session_manager.create(session_id)

        generator = llm_service.generate_stream(
            session=session,
            messages=messages,
            max_new_tokens=data.get("max_tokens"),
        )

        for token in generator:
            tokens_generated += 1
            await ws.send_json({
                "type": "token",
                "text": token,
                "is_final": False
            })

        # final signal
        await ws.send_json({
            "type": "token",
            "text": "",
            "is_final": True
        })

    except WebSocketDisconnect:
        if session:
            session.cancel_event.set()
        closed = True

    except Exception as e:
        logger.exception("LLM WS error")
        if not closed:
            try:
                await ws.send_json({
                    "type": "error",
                    "message": str(e)
                })
            except RuntimeError:
                pass

    finally:
        if session:
            llm_session_manager.cleanup(session.session_id)

        if not closed:
            try:
                await ws.close()
            except RuntimeError:
                pass


@router.post("/session/{session_id}/cancel")
def cancel_session(session_id: str):
    llm_session_manager.cancel(session_id)
    return {"status": "cancelled"}


