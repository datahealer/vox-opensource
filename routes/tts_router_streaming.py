import asyncio
import json
import os
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from core.logger import setup_logger
from tts_services.xttx_v2_streaming_service import XTTSStreamingService, SAMPLE_RATE

router = APIRouter()
logger = setup_logger("tts_router_streaming")

# ──────────────────────────────────────────────────────────────────────────
# TTS Debug Logger (non-blocking, independent of core flow)
# ──────────────────────────────────────────────────────────────────────────
DEBUG_TTS_RESPONSES = os.getenv("DEBUG_TTS_RESPONSES", "true").lower() == "true"
DEBUG_TTS_DIR = Path("tts_debug_responses")
if DEBUG_TTS_RESPONSES:
    DEBUG_TTS_DIR.mkdir(exist_ok=True)
    logger.info(f"[TTS Debug] Enabled: responses will be saved to {DEBUG_TTS_DIR}")

# Async queue for non-blocking writes
_tts_debug_queue = asyncio.Queue() if DEBUG_TTS_RESPONSES else None
_tts_debug_writer_task = None

async def _tts_debug_writer():
    """Background task: write TTS responses to disk without blocking main flow."""
    if not DEBUG_TTS_RESPONSES:
        return

    logger.info("[TTS Debug] Writer thread started")
    while True:
        try:
            item = await _tts_debug_queue.get()
            if item is None:  # Shutdown signal
                logger.info("[TTS Debug] Writer thread shutting down")
                break

            synthesis_id, chunk_idx, chunk_data, metadata = item

            # Create session directory
            session_dir = DEBUG_TTS_DIR / f"synthesis_{synthesis_id}"
            session_dir.mkdir(exist_ok=True)

            # Write audio chunk
            if chunk_idx >= 0:
                chunk_file = session_dir / f"chunk_{chunk_idx:03d}.pcm16"
                chunk_file.write_bytes(chunk_data)

            # Write metadata on first chunk
            if chunk_idx == -1 and metadata:
                meta_file = session_dir / "metadata.json"
                meta_file.write_text(json.dumps(metadata, indent=2))

        except Exception as e:
            logger.warning(f"[TTS Debug] Writer error: {e}")

async def _ensure_debug_writer():
    """Ensure background writer task is running."""
    global _tts_debug_writer_task
    if DEBUG_TTS_RESPONSES and (_tts_debug_writer_task is None or _tts_debug_writer_task.done()):
        _tts_debug_writer_task = asyncio.create_task(_tts_debug_writer())
        logger.info("[TTS Debug] Writer task created")

def _queue_tts_debug(synthesis_id: int, chunk_idx: int, chunk_data: bytes, metadata: dict = None):
    """Queue a TTS response chunk for debug logging (non-blocking)."""
    if DEBUG_TTS_RESPONSES and _tts_debug_queue:
        try:
            _tts_debug_queue.put_nowait((synthesis_id, chunk_idx, chunk_data, metadata))
        except asyncio.QueueFull:
            logger.warning(f"[TTS Debug] Queue full, dropping chunk {chunk_idx}")

# ──────────────────────────────────────────────────────────────────────────
# Initialize streaming TTS service (singleton)
_tts_service = None

SUPPORTED_VOICES = {"nova", "alloy", "echo", "fable", "onyx", "shimmer"}
MIN_SPEED = 0.25
MAX_SPEED = 4.0


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
                raw = await ws.receive()
                # Handle explicit disconnect/control frames
                if set(["type", "code", "reason"]).issubset(raw.keys()):
                    logger.info(f"TTS disconnect/control: {raw}")
                    raise WebSocketDisconnect(code=raw.get("code", 1000))

                if "text" in raw:
                    try:
                        msg = json.loads(raw["text"])
                    except json.JSONDecodeError:
                        logger.warning("Received invalid JSON on TTS WebSocket")
                        continue
                elif "bytes" in raw:
                    logger.warning("Binary message received on TTS control channel; ignoring")
                    continue
                else:
                    logger.warning(f"Unknown message envelope on TTS WebSocket: {raw}")
                    continue
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
                try:
                    await ws.send_json({"event": "init_ack"})
                except Exception as e:
                    logger.warning(f"Failed to send init_ack: {e}")
                continue

            if event == "synthesize":
                synthesis_id = msg.get("synthesis_id")
                text = msg.get("text") or msg.get("payload") or ""
                voice = msg.get("voice") or "nova"
                lang_in = msg.get("language") or msg.get("locale")
                if isinstance(lang_in, str) and "-" in lang_in:
                    lang_in = lang_in.split("-")[0].lower()
                language = lang_in or "en"
                speed = msg.get("speed", 1.0)

                if synthesis_id is None:
                    await ws.send_json({"event": "error", "message": "Missing synthesis_id", "synthesis_id": synthesis_id})
                    continue

                if not text.strip():
                    await ws.send_json({
                        "event": "error",
                        "message": "Text required",
                        "synthesis_id": synthesis_id,
                    })
                    continue

                if speed < MIN_SPEED or speed > MAX_SPEED:
                    await ws.send_json({
                        "event": "error",
                        "message": f"speed must be between {MIN_SPEED} and {MAX_SPEED}",
                        "synthesis_id": synthesis_id,
                    })
                    continue

                if voice not in SUPPORTED_VOICES:
                    await ws.send_json({
                        "event": "error",
                        "message": f"Voice '{voice}' not available",
                        "synthesis_id": synthesis_id,
                        "error_code": "INVALID_VOICE",
                    })
                    continue

                logger.info(
                    f"TTS Streaming synthesize: synthesis_id={synthesis_id}, text_length={len(text)}, voice={voice}, language={language}, speed={speed}"
                )

                async def run():
                    nonlocal bytes_generated
                    bytes_generated = 0  # Reset for this synthesis
                    frame_count = 0
                    import time
                    start_time = time.time()

                    # Ensure debug writer is running
                    await _ensure_debug_writer()

                    # Queue metadata for this synthesis
                    if DEBUG_TTS_RESPONSES:
                        _queue_tts_debug(
                            synthesis_id,
                            -1,  # Metadata marker
                            b"",
                            {
                                "synthesis_id": synthesis_id,
                                "text": text,
                                "voice": voice,
                                "language": language,
                                "speed": speed,
                                "timestamp": datetime.now().isoformat(),
                            }
                        )

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

                            # Queue for debug logging (non-blocking, put_nowait is O(1))
                            if DEBUG_TTS_RESPONSES:
                                _queue_tts_debug(synthesis_id, frame_count - 1, pcm)

                            if frame_count == 1 or frame_count % 10 == 0:
                                logger.debug(f"TTS sent frame {frame_count}, {bytes_generated} bytes so far")

                        # After streaming completes, send done event with duration
                        if not cancel_event.is_set():
                            try:
                                total_samples = bytes_generated // 2
                                duration = round(total_samples / float(SAMPLE_RATE), 3)
                                duration_ms = int(duration * 1000) if duration is not None else None
                            except Exception:
                                duration = None
                                duration_ms = None

                            logger.info(
                                f"TTS Streaming done: synthesis_id={synthesis_id}, frames={frame_count}, bytes={bytes_generated}, duration={duration}s"
                            )
                            try:
                                await ws.send_json(
                                    {
                                        "event": "done",
                                        "synthesis_id": synthesis_id,
                                        "duration_ms": duration_ms,
                                    }
                                )
                                logger.info(
                                    f"✅ TTS Streaming done event sent successfully (session_id={session_id}, synthesis_id={synthesis_id}, duration={duration}s)"
                                )
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
