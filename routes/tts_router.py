import asyncio
import base64
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from core.logger import setup_logger
from tts_services.xttx_v2_service import SAMPLE_RATE

router = APIRouter()
logger = setup_logger("tts_router")

def pcm16_to_base64(pcm: bytes) -> str:
    return base64.b64encode(pcm).decode("utf-8")


@router.websocket("/stream")
async def tts_stream(ws: WebSocket):
    from services.tts_service import get_tts_service
    tts_service = get_tts_service()

    await ws.accept()
    cancel_event = asyncio.Event()
    bytes_generated = 0
    session_id = ws.query_params.get("session_id")
    if session_id:
        logger.info(f"TTS WS connected, session_id={session_id}")

    try:
        while True:
            try:
                msg = await ws.receive_json()
            except json.JSONDecodeError:
                logger.warning("Received invalid JSON on TTS WebSocket")
                continue
            except Exception as e:
                logger.error(f"Error receiving message: {e}")
                continue

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
                logger.info(f"TTS init received (session_id={session_id})")
                # No-op for now; keep connection warm
                continue

            if event == "synthesize":
                text = msg.get("text") or msg.get("payload") or ""
                voice = msg.get("voice")
                lang_in = msg.get("language") or msg.get("locale")
                if isinstance(lang_in, str) and "-" in lang_in:
                    lang_in = lang_in.split("-")[0].lower()
                language = (lang_in or "en")
                speed = msg.get("speed", 1.0)

                logger.info(
                    f"TTS synthesize: text_length={len(text)}, voice={voice}, language={language}, speed={speed}"
                )

                async def run():
                    nonlocal bytes_generated
                    frame_count = 0
                    async for pcm in tts_service.stream(
                        text=text,
                        voice=voice,
                        language=language,
                        speed=speed,
                        cancel_event=cancel_event,
                    ):
                        if cancel_event.is_set():
                            break
                        bytes_generated += len(pcm)
                        frame_count += 1
                        # Send raw PCM16 bytes as binary websocket frames
                        await ws.send_bytes(pcm)
                        if frame_count == 1 or frame_count % 10 == 0:
                            logger.debug(f"TTS sent frame {frame_count}, {bytes_generated} bytes so far")

                    # After streaming completes, send done event with duration
                    try:
                        total_samples = bytes_generated // 2
                        duration = round(total_samples / float(SAMPLE_RATE), 3)
                    except Exception:
                        duration = None

                    logger.info(f"TTS done: {frame_count} frames, {bytes_generated} bytes, duration={duration}s")
                    await ws.send_json({
                        "event": "done",
                        "duration": duration,
                    })

                asyncio.create_task(run())
                continue

            if event == "cancel":
                logger.info(f"TTS cancel received (session_id={session_id})")
                cancel_event.set()
                # Inform client that we acknowledged cancel (optional)
                await ws.send_json({"event": "cancel_ack"})
                break

            logger.warning(f"TTS received unknown event: {event} (raw={msg})")

    except WebSocketDisconnect:
        logger.debug("TTS client disconnected")
        cancel_event.set()
    except Exception as e:
        logger.error(f"TTS error: {e}")
