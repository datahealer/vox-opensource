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


@router.post("/stream")
def generate_stream(req):
    from services.llm_service import get_llm_service
    llm_service = get_llm_service()
    if not req.prompt.strip() or not req.session_id:
        raise HTTPException(400, "Prompt and session_id cannot be empty")

    session_id = req.session_id
    session = llm_session_manager.create(session_id)
    generator = llm_service.generate_stream(
        prompt=req.prompt,
        session=session,
        max_new_tokens=req.max_new_tokens,
        temperature=req.temperature,
        top_p=req.top_p,
    )

    return StreamingResponse(
        generator,
        media_type="text/plain",
    )


@router.websocket("/stream/ws")
async def generate_stream_ws(ws: WebSocket):
    from services.llm_service import get_llm_service
    llm_service = get_llm_service()
    await ws.accept()

    session = None
    try:
        data = await ws.receive_json()

        session_id = data["session_id"]
        prompt = data["prompt"]

        session = llm_session_manager.create(session_id)

        generator = llm_service.generate_stream(
            session=session,
            prompt=prompt,
            max_new_tokens=data.get("max_new_tokens"),
            temperature=data.get("temperature"),
            top_p=data.get("top_p"),
        )

        for token in generator:
            await ws.send_text(token)

    except WebSocketDisconnect:
        # ✅ client closed → DO NOTHING to socket
        if session:
            llm_session_manager.cancel(session_id)

    except Exception as e:
        logger.exception("WebSocket error")
        if ws.client_state.name == "CONNECTED":
            await ws.send_text(f"[ERROR] {str(e)}")

    finally:
        if session:
            llm_session_manager.cleanup(session_id)

        # ✅ ONLY close if still connected
        if ws.client_state.name == "CONNECTED":
            await ws.close()



@router.post("/session/{session_id}/cancel")
def cancel_session(session_id: str):
    llm_session_manager.cancel(session_id)
    return {"status": "cancelled"}




# @router.websocket("/stream/ws")
# async def generate_stream_ws(ws: WebSocket):
#     from services.llm_service import get_llm_service
#     llm_service = get_llm_service()

#     await ws.accept()

#     session = None
#     tokens_generated = 0

#     try:
#         data = await ws.receive_json()

#         if data.get("type") != "request":
#             await ws.close(code=1003)
#             return

#         session_id = data["session_id"]
#         messages = data["messages"]

#         session = llm_session_manager.create(session_id)

#         generator = llm_service.generate_stream(
#             session=session,
#             messages=messages,
#             max_new_tokens=data.get("max_tokens"),
#         )

#         for token in generator:
#             tokens_generated += 1
#             await ws.send_json({
#                 "type": "token",
#                 "text": token,
#                 "is_final": False
#             })

#         # ✅ final signal
#         await ws.send_json({
#             "type": "token",
#             "text": "",
#             "is_final": True
#         })

#     except WebSocketDisconnect:
#         if session:
#             session.cancel_event.set()

#     except Exception as e:
#         logger.exception("LLM WS error")
#         if ws.client_state.name == "CONNECTED":
#             await ws.send_json({
#                 "type": "error",
#                 "message": str(e)
#             })

#     finally:
#         if session and session.cancel_event.is_set():
#             await ws.send_json({
#                 "type": "cancelled",
#                 "reason": "call_ended",
#                 "tokens_generated": tokens_generated
#             })

#         if session:
#             llm_session_manager.cleanup(session.session_id)

#         if ws.client_state.name == "CONNECTED":
#             await ws.close()
