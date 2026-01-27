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
        "model": llm_service.MODEL_ID,
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

    # Get session_id from query params
    session_id = ws.query_params.get("session_id")
    if not session_id:
        logger.error("LLM WS: Missing session_id in query params")
        await ws.close(code=1003, reason="Missing session_id")
        return

    session = None
    tokens_generated = 0
    closed = False
    initialized = False

    try:
        # Handle init message first (required by protocol)
        data = await ws.receive_json()
        logger.info("LLM WS received: %s", data.keys())

        event = data.get("event")

        if event != "init":
            logger.error(f"LLM WS: First message must be init, got event={event}")
            await ws.send_json({
                "event": "error",
                "message": "first message must be init",
                "error_code": "invalid_request",
            })
            await ws.close(code=1003, reason="init required")
            return

        call_session_id = data.get("call_session_id")
        service_type = data.get("service_type")
        if not call_session_id or service_type != "llm":
            await ws.send_json({
                "event": "error",
                "message": "invalid init payload",
                "error_code": "invalid_request",
            })
            await ws.close(code=1003, reason="invalid init")
            return

        initialized = True
        logger.info(f"LLM init received (session_id={session_id}, call_session_id={call_session_id})")
        try:
            await ws.send_json({"event": "init_ack"})
            logger.info("LLM init_ack sent, waiting for generate request")
        except Exception as e:
            logger.error(f"LLM init_ack failed (session_id={session_id}): {e}")
            return

        # Main loop: allow multiple generate turns per connection
        while True:
            try:
                if not initialized:
                    # If init was missing, we already read first message into `data`
                    pass
                else:
                    data = await ws.receive_json()
                    logger.info("LLM WS received: %s", data.keys())

                event = data.get("event")

                if event == "generate":
                    # Per-turn state reset
                    tokens_generated = 0
                    turn_started = ws.application_state if False else None
                    import time
                    start_time = time.time()

                    # Cleanup any previous session before creating a new one
                    if session:
                        llm_session_manager.cleanup(session.session_id)
                        session = None

                    request_id = data.get("request_id")
                    messages = data.get("messages", [])
                    max_tokens = data.get("max_tokens", 1024)
                    agent_id = data.get("agent_id")

                    if request_id is None:
                        logger.error("LLM generate: Missing request_id")
                        await ws.send_json({
                            "event": "error",
                            "message": "Missing request_id",
                            "error_code": "invalid_request",
                        })
                        continue

                    if not messages:
                        logger.error("LLM generate: Empty messages array")
                        await ws.send_json({
                            "event": "error",
                            "message": "Empty messages array",
                            "error_code": "invalid_request",
                            "request_id": request_id,
                        })
                        continue

                    logger.info(
                        f"LLM generating for session_id={session_id}, request_id={request_id}, messages={len(messages)}, max_tokens={max_tokens}, agent_id={agent_id}"
                    )

                    session = llm_session_manager.create(session_id)

                    try:
                        generator = llm_service.generate_stream(
                            session=session,
                            messages=messages,
                            max_new_tokens=max_tokens,
                        )

                        # Stream tokens
                        for token in generator:
                            if session.cancel_event.is_set():
                                logger.info(f"LLM generation cancelled (session_id={session_id})")
                                await ws.send_json({
                                    "event": "cancel_ack",
                                    "tokens_generated": tokens_generated,
                                    "finish_reason": "cancel"
                                })
                                break

                            tokens_generated += 1
                            await ws.send_json({
                                "event": "token",
                                "text": token,
                                "request_id": request_id,
                            })

                        if session.cancel_event.is_set():
                            # Ensure session is cleaned before next turn
                            continue

                        # Send done event
                        duration_ms = int((time.time() - start_time) * 1000)
                        logger.info(
                            f"LLM generation complete (session_id={session_id}, request_id={request_id}, tokens={tokens_generated}, duration_ms={duration_ms})"
                        )
                        await ws.send_json({
                            "event": "done",
                            "request_id": request_id,
                            "total_tokens": tokens_generated,
                            "duration_ms": duration_ms,
                            "finish_reason": "stop",
                        })

                    except Exception as e:
                        logger.error(f"LLM generation error (session_id={session_id}): {e}", exc_info=True)
                        await ws.send_json({
                            "event": "error",
                            "message": str(e),
                            "error_code": "model_error",
                            "request_id": request_id,
                        })

                    finally:
                        if session:
                            llm_session_manager.cleanup(session.session_id)
                            session = None

                elif event == "cancel":
                    reason = data.get("reason", "unknown")
                    logger.info(f"LLM cancel received: reason={reason}")
                    if session:
                        session.cancel_event.set()
                    await ws.send_json({
                        "event": "cancel_ack",
                        "tokens_generated": tokens_generated,
                        "finish_reason": "cancel",
                        "request_id": data.get("request_id"),
                    })

                else:
                    logger.warning(f"LLM WS: Unknown event type: {event}")
                    await ws.send_json({
                        "event": "error",
                        "message": f"Unknown event type: {event}",
                        "error_code": "invalid_request"
                    })

                # After the first loop iteration, consider init done
                initialized = True

            except WebSocketDisconnect:
                raise
            except Exception as e:
                logger.error(f"LLM loop error (session_id={session_id}): {e}", exc_info=True)
                try:
                    await ws.send_json({
                        "event": "error",
                        "message": str(e),
                        "error_code": "internal_error"
                    })
                except RuntimeError:
                    pass
                # Continue loop to allow further messages if socket remains open

    except WebSocketDisconnect as e:
        if session:
            session.cancel_event.set()
        closed = True
        logger.info(f"LLM WS disconnected (session_id={session_id}, code={e.code if hasattr(e, 'code') else 'unknown'})")

    except Exception as e:
        logger.exception(f"LLM WS error (session_id={session_id}): {type(e).__name__}: {e}")
        if not closed:
            try:
                await ws.send_json({
                    "event": "error",
                    "message": str(e),
                    "error_code": "internal_error"
                })
            except RuntimeError:
                logger.warning(f"LLM WS: Failed to send error event (session_id={session_id})")

    finally:
        if session:
            llm_session_manager.cleanup(session.session_id)

        if not closed:
            try:
                await ws.close(code=1000)
            except RuntimeError:
                pass

        logger.info(f"LLM WS session cleanup complete (session_id={session_id})")


@router.post("/session/{session_id}/cancel")
def cancel_session(session_id: str):
    llm_session_manager.cancel(session_id)
    return {"status": "cancelled"}


