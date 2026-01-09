import asyncio
import base64
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import numpy as np
from core.logger import setup_logger

router = APIRouter()
logger = setup_logger("stt_router")

@router.websocket("/stream")
async def stt_stream(ws: WebSocket):
    from services.stt_service import get_stt_service
    stt_service = get_stt_service()
    await ws.accept()

    audio_buffer = np.zeros(0, dtype=np.float32)
    stt_service.reset()  # Reset state for new session

    session_id = ws.query_params.get("session_id")
    if session_id:
        logger.info(f"STT WS connected, session_id={session_id}")

    try:
        while True:
            # Try to receive either JSON (commands) or binary (audio frames)
            is_json = False
            try:
                msg = await ws.receive_json()
                is_json = True
            except json.JSONDecodeError:
                pass
            except Exception as e:
                logger.debug(f"STT receive error: {type(e).__name__}")
                continue

            if is_json:
                # Handle JSON command messages
                msg_type = msg.get("type")
                event = msg.get("event")
                logger.debug(f"STT received JSON: type={msg_type}, event={event}")

                if event == "init":
                    logger.info(f"STT init received (session_id={session_id})")
                    continue

                if msg_type == "audio_chunk" or event == "audio_chunk":
                    b64_audio = msg.get("audio")
                    if not b64_audio:
                        logger.debug("Received empty audio_chunk")
                        continue
                    logger.debug(f"Received audio_chunk: {len(b64_audio)} bytes (b64)")

                    # Decode and append to buffer
                    chunk = stt_service.decode_pcm_base64(b64_audio)
                    audio_buffer = np.concatenate([audio_buffer, chunk])

                    # Process buffer and get transcriptions
                    processed_samples = 0
                    async for result in stt_service.transcribe_stream(audio_buffer):
                        await ws.send_json({
                            "type": "transcript",
                            "text": result["text"],
                            "is_final": result["is_final"],
                            "confidence": result["confidence"]
                        })
                        # Track how much we've processed
                        processed_samples += stt_service.chunk_samples

                    # Remove processed audio from buffer
                    if processed_samples > 0:
                        audio_buffer = audio_buffer[processed_samples:]

                elif msg_type == "end_stream" or event == "end_stream":
                    logger.info("STT end_stream received")
                    # Process any remaining audio
                    if len(audio_buffer) > 0:
                        result = stt_service.process_remaining(audio_buffer)
                        if result:
                            await ws.send_json({
                                "type": "transcript",
                                "text": result["text"],
                                "is_final": True,
                                "confidence": result["confidence"]
                            })

                    await ws.send_json({"type": "complete"})
                    break

                elif msg_type == "cancel" or event == "cancel":
                    logger.info(f"STT cancel received: reason={msg.get('reason', 'unknown')}")
                    await ws.send_json({
                        "type": "cancelled",
                        "reason": msg.get("reason", "unknown")
                    })
                    break

            else:
                # Binary frame: audio data
                try:
                    data = await ws.receive_bytes()
                    logger.debug(f"STT received binary frame: {len(data)} bytes")
                    # Convert binary PCM16 to float32 and append to buffer
                    chunk = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                    audio_buffer = np.concatenate([audio_buffer, chunk])
                    # Don't transcribe yet; wait for end_stream or timeout
                except Exception as e:
                    logger.debug(f"STT binary receive error: {type(e).__name__}")
                    continue

    except WebSocketDisconnect:
        logger.debug("STT client disconnected")
    except Exception as e:
        logger.error(f"STT error: {e}")
        try:
            await ws.close(code=1011, reason=str(e))
        except:
            pass