import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from core.logger import setup_logger
from tts_services.xttx_v2_streaming_service import XTTSStreamingService, SAMPLE_RATE

router = APIRouter()
logger = setup_logger("tts_router_streaming")

# Initialize streaming TTS service (singleton)
_tts_service = None


def get_streaming_tts_service():
    global _tts_service
    if _tts_service is None:
        logger.info("Initializing XTTS Streaming Service (first access)...")
        _tts_service = XTTSStreamingService()
    return _tts_service


@router.get("/health")
def health():
    return {
        "status": "ok",
        "service": "xtts_v2_streaming",
        "sample_rate": SAMPLE_RATE,
    }

@router.websocket("/stream")
async def tts_stream(ws: WebSocket):
    tts_service = get_streaming_tts_service()

    await ws.accept()
    cancel_event = asyncio.Event()
    bytes_generated = 0
    session_id = ws.query_params.get("session_id")
    current_task = None
    client_addr = ws.client.host if ws.client else "unknown"

    if session_id:
        logger.info(f"TTS Streaming WS connected, session_id={session_id}, client={client_addr}")

    try:
        while True:
            try:
                msg = await ws.receive_json()
            except json.JSONDecodeError:
                logger.warning("Received invalid JSON on TTS WebSocket")
                continue
            except WebSocketDisconnect:
                logger.debug("TTS WebSocket disconnected while receiving")
                raise
            except Exception as e:
                logger.error(f"Error receiving message: {e}")
                break

            # Support both legacy {type:"request"} and new {event:"..."}
            msg_type = msg.get("type")
            event = msg.get("event")
            logger.debug(f"TTS received message: type={msg_type}, event={event}")

            # Normalize to event names
            if msg_type == "request":
                event = "synthesize"
            elif msg_type == "cancel":
                event = "cancel"

            if event == "init":
                logger.info(f"TTS Streaming init received (session_id={session_id})")
                # No-op for now; keep connection warm
                continue

            if event == "synthesize":
                text = msg.get("text") or msg.get("payload") or ""
                voice = msg.get("voice")
                lang_in = msg.get("language") or msg.get("locale")
                if isinstance(lang_in, str) and "-" in lang_in:
                    lang_in = lang_in.split("-")[0].lower()
                language = lang_in or "en"
                speed = msg.get("speed", 1.0)

                logger.info(
                    f"TTS Streaming synthesize: text_length={len(text)}, voice={voice}, language={language}, speed={speed}"
                )

                async def run():
                    nonlocal bytes_generated
                    bytes_generated = 0  # Reset for this synthesis
                    frame_count = 0
                    try:
                        async for pcm in tts_service.stream(
                            text=text,
                            voice=voice,
                            language=language,
                            speed=speed,
                            cancel_event=cancel_event,
                        ):
                            if cancel_event.is_set():
                                logger.debug(f"TTS synthesis cancelled at frame {frame_count}")
                                break
                            bytes_generated += len(pcm)
                            frame_count += 1
                            # Send raw PCM16 bytes as binary websocket frames
                            try:
                                await ws.send_bytes(pcm)
                            except Exception as e:
                                logger.warning(f"TTS failed to send frame {frame_count}: {e}")
                                break
                            if frame_count == 1 or frame_count % 10 == 0:
                                logger.debug(f"TTS sent frame {frame_count}, {bytes_generated} bytes so far")

                        # After streaming completes, send done event with duration
                        if not cancel_event.is_set():
                            try:
                                total_samples = bytes_generated // 2
                                duration = round(total_samples / float(SAMPLE_RATE), 3)
                            except Exception:
                                duration = None

                            logger.info(
                                f"TTS Streaming done: {frame_count} frames, {bytes_generated} bytes, duration={duration}s"
                            )
                            try:
                                await ws.send_json(
                                    {
                                        "event": "done",
                                        "duration": duration,
                                    }
                                )
                                logger.info(f"✅ TTS Streaming done event sent successfully (session_id={session_id}, duration={duration}s)")
                            except Exception as e:
                                logger.warning(f"TTS failed to send done event: {e}")
                    except Exception as e:
                        logger.error(f"TTS streaming synthesis error: {e}", exc_info=True)

                # Cancel any previous task
                if current_task and not current_task.done():
                    logger.debug("Cancelling previous TTS synthesis task")
                    cancel_event.set()
                    try:
                        await asyncio.wait_for(current_task, timeout=1.0)
                    except asyncio.TimeoutError:
                        current_task.cancel()
                    cancel_event.clear()

                current_task = asyncio.create_task(run())
                continue

            if event == "cancel":
                logger.info(f"TTS cancel received (session_id={session_id})")
                cancel_event.set()

                # Wait for current task to finish
                if current_task and not current_task.done():
                    try:
                        await asyncio.wait_for(current_task, timeout=2.0)
                    except asyncio.TimeoutError:
                        logger.warning("TTS task didn't finish in time, forcing cancellation")
                        current_task.cancel()

                # Inform client that we acknowledged cancel
                try:
                    await ws.send_json({"event": "cancel_ack"})
                except Exception as e:
                    logger.warning(f"Failed to send cancel_ack: {e}")
                continue  # Don't break, allow more requests

            logger.warning(f"TTS received unknown event: {event} (raw={msg})")

    except WebSocketDisconnect as e:
        close_code = getattr(e, "code", None) or 0
        close_reason = {
            1000: "normal closure (Server intentionally closed)",
            1001: "going away",
            1002: "protocol error",
            1003: "unsupported data",
            1006: "abnormal closure (network/crash)",
            1011: "server error",
        }.get(close_code, f"unknown code {close_code}")
        logger.info(
            f"TTS Streaming WS disconnected by client (session_id={session_id}, code={close_code}, reason={close_reason})"
        )
        cancel_event.set()
        # Wait for any running task to finish
        if current_task and not current_task.done():
            try:
                await asyncio.wait_for(current_task, timeout=1.0)
            except asyncio.TimeoutError:
                current_task.cancel()
    except Exception as e:
        logger.error(f"TTS Streaming error: {e}", exc_info=True)
    finally:
        # Ensure cleanup
        cancel_event.set()
        if current_task and not current_task.done():
            current_task.cancel()
            try:
                await current_task
            except asyncio.CancelledError:
                pass
        logger.info(f"TTS Streaming WS closed (session_id={session_id}, client={client_addr})")
