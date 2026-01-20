import asyncio
import base64
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import numpy as np
from core.logger import setup_logger

router = APIRouter()
logger = setup_logger("stt_router")

@router.get("/health")
def health():
    from services.stt_service import get_stt_service
    stt_service = get_stt_service()
    return {
        "status": "ok",
        "service": "faster_whisper",
        "model_size": getattr(stt_service, 'model_size', 'unknown'),
    }

@router.websocket("/stream")
async def stt_stream(ws: WebSocket):
    from services.stt_service import get_stt_service
    stt_service = get_stt_service()
    await ws.accept()

    audio_buffer = np.zeros(0, dtype=np.float32)
    expected_chunk_id = 1  # ✅ NEW: Track expected chunk_id for sequence validation
    stt_service.reset()  # Reset state for new session

    session_id = ws.query_params.get("session_id")
    logger.info(f"═══════════════════════════════════════════════════════════")
    logger.info(f"STT WS CONNECTED: session_id={session_id}")
    logger.info(f"═══════════════════════════════════════════════════════════")

    message_count = 0
    audio_frame_count = 0
    audio_chunk_count = 0
    total_audio_samples = 0

    try:
        while True:
            # Use receive() to get either text or binary message
            try:
                logger.debug(f"[Loop] Waiting for message #{message_count + 1}...")
                message = await ws.receive()
                message_count += 1
                logger.info(f"[Message #{message_count}] RECEIVED: Keys: {list(message.keys())}")
            except asyncio.TimeoutError:
                logger.warning(f"[Loop] Timeout waiting for message")
                continue
            except WebSocketDisconnect:
                logger.warning(f"[Loop] WebSocket disconnected while waiting for message")
                raise
            except RuntimeError as e:
                if "Cannot call" in str(e) and "disconnect message" in str(e):
                    logger.debug(f"[Loop] WebSocket already disconnected, exiting loop")
                    break
                logger.error(f"[Loop] Runtime error: {e}", exc_info=True)
                break
            except Exception as e:
                logger.error(f"[Loop] Receive error: {type(e).__name__}: {e}", exc_info=True)
                break

            # Handle binary audio frames
            if "bytes" in message:
                audio_frame_count += 1
                data = message["bytes"]
                logger.info(f"[Binary Frame #{audio_frame_count}] ✅ RECEIVED: {len(data)} bytes")

                # Convert binary PCM16 to float32 and append to buffer
                try:
                    chunk = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                    audio_buffer = np.concatenate([audio_buffer, chunk])
                    total_audio_samples += len(chunk)
                    logger.info(f"[Binary Frame #{audio_frame_count}] ✅ Buffer updated: "
                                f"{len(audio_buffer)} samples ({len(audio_buffer) / 16000:.2f}s)")
                except Exception as e:
                    logger.error(f"[Binary Frame #{audio_frame_count}] ❌ Error: {e}", exc_info=True)
                    continue

                # Process buffer and get transcriptions
                logger.info(f"[Binary Frame #{audio_frame_count}] 🎤 Starting transcription from buffer "
                           f"({len(audio_buffer)} samples)")

                processed_samples = 0
                transcript_count = 0
                try:
                    async for result in stt_service.transcribe_stream(audio_buffer):
                        transcript_count += 1
                        logger.info(f"[Binary Frame #{audio_frame_count}] 📝 Transcript #{transcript_count}: '{result['text']}'")
                        try:
                            await ws.send_json({
                                "event": "transcript",
                                "text": result["text"]
                            })
                            logger.debug(f"[Binary Frame #{audio_frame_count}] ✅ Sent transcript #{transcript_count} to client")
                        except Exception as e:
                            logger.error(f"[Binary Frame #{audio_frame_count}] ❌ Error sending transcript: {e}")
                            break

                        # Track how much we've processed
                        processed_samples += stt_service.chunk_samples

                    if transcript_count == 0:
                        logger.debug(f"[Binary Frame #{audio_frame_count}] No transcripts generated (buffer may be too short)")

                    # Remove processed audio from buffer
                    if processed_samples > 0:
                        logger.debug(f"[Binary Frame #{audio_frame_count}] Removing {processed_samples} processed samples from buffer")
                        audio_buffer = audio_buffer[processed_samples:]
                        logger.debug(f"[Binary Frame #{audio_frame_count}] Buffer after removal: {len(audio_buffer)} samples")

                except Exception as e:
                    logger.error(f"[Binary Frame #{audio_frame_count}] ❌ Transcription error: {e}", exc_info=True)

                continue

            # Handle JSON messages
            if "text" in message:
                try:
                    msg = json.loads(message["text"])
                except json.JSONDecodeError:
                    logger.warning(f"[JSON] ❌ Invalid JSON received")
                    continue

                # Handle JSON command messages
                msg_type = msg.get("type")
                event = msg.get("event")
                logger.info(f"[JSON Message #{message_count}] ✅ RECEIVED: type={msg_type}, event={event}")

                if event == "init":
                    logger.info(f"[Init] ✅ STT init received (session_id={session_id})")
                    # Acknowledge init message
                    try:
                        await ws.send_json({"event": "init_ack"})
                        logger.info(f"[Init] ✅ init_ack sent - now entering message receive loop")
                        logger.info(f"[Init] 🔄 Ready to receive audio frames on this WebSocket")
                    except Exception as e:
                        logger.error(f"[Init] ❌ Failed to send init_ack: {e}")
                        break
                    continue

                if msg_type == "audio_chunk" or event == "audio_chunk":
                    audio_chunk_count += 1

                    # ✅ NEW: Extract protocol fields (chunk_id and is_final)
                    chunk_id = msg.get("chunk_id")
                    is_final = msg.get("is_final", False)
                    b64_audio = msg.get("audio")

                    # Validate message
                    if not chunk_id:
                        logger.error(f"[audio_chunk #{audio_chunk_count}] Missing chunk_id")
                        continue

                    logger.info(f"[audio_chunk #{audio_chunk_count}] Received: chunk_id={chunk_id}, is_final={is_final}, "
                               f"audio_bytes={len(b64_audio) if b64_audio else 0}")

                    # Decode and append to buffer (skip if empty audio, but still process is_final below)
                    if b64_audio:
                        try:
                            chunk = stt_service.decode_pcm_base64(b64_audio)
                            audio_buffer = np.concatenate([audio_buffer, chunk])
                            total_audio_samples += len(chunk)
                            logger.info(f"[audio_chunk #{audio_chunk_count}] Buffer size: "
                                       f"{len(audio_buffer)} samples ({len(audio_buffer) / 16000:.2f}s)")
                        except Exception as e:
                            logger.error(f"[audio_chunk #{audio_chunk_count}] Error decoding audio: {e}", exc_info=True)
                            continue
                    else:
                        logger.debug(f"[audio_chunk #{audio_chunk_count}] Empty audio (finalization signal)")

                    # ✅ CRITICAL: Only process when utterance is complete (is_final=true)
                    if not is_final:
                        logger.debug(f"[audio_chunk #{audio_chunk_count}] Buffering chunk (is_final=false), "
                                    f"waiting for more chunks")
                        continue

                    # is_final=true: Process complete utterance
                    logger.info(f"[audio_chunk #{audio_chunk_count}] Utterance complete (is_final=true). "
                               f"Processing {len(audio_buffer)} samples ({len(audio_buffer) / 16000:.2f}s)")

                    if len(audio_buffer) == 0:
                        logger.warning(f"[audio_chunk #{audio_chunk_count}] Empty utterance (is_final=true with no audio)")
                        expected_chunk_id = 1  # Reset for next utterance
                        continue

                    # ✅ Process complete utterance (all buffered chunks together)
                    try:
                        result = await stt_service.transcribe_complete_utterance(audio_buffer)
                        if result:
                            logger.info(f"[audio_chunk #{audio_chunk_count}] Transcript: '{result['text']}'")
                            try:
                                await ws.send_json({
                                    "event": "transcript",
                                    "text": result["text"]
                                })
                                logger.debug(f"[audio_chunk #{audio_chunk_count}] Sent transcript to client")
                            except Exception as e:
                                logger.error(f"[audio_chunk #{audio_chunk_count}] Error sending transcript: {e}")
                        else:
                            logger.debug(f"[audio_chunk #{audio_chunk_count}] No transcription result")
                    except Exception as e:
                        logger.error(f"[audio_chunk #{audio_chunk_count}] Transcription error: {e}", exc_info=True)

                    # ✅ Clear buffer for next utterance and reset chunk_id counter
                    audio_buffer = np.zeros(0, dtype=np.float32)
                    expected_chunk_id = 1
                    logger.debug(f"[audio_chunk #{audio_chunk_count}] Buffer cleared, ready for next utterance")

                elif msg_type == "end_stream" or event == "end_stream":
                    logger.info(f"[end_stream] Received end_stream signal")
                    logger.info(f"[end_stream] Processing remaining {len(audio_buffer)} samples ({len(audio_buffer) / 16000:.2f}s)")

                    # Process any remaining audio
                    if len(audio_buffer) > 0:
                        result = stt_service.process_remaining(audio_buffer)
                        if result:
                            logger.info(f"[end_stream] Final result: '{result['text']}'")
                            try:
                                await ws.send_json({
                                    "event": "transcript",
                                    "text": result["text"]
                                })
                            except Exception as e:
                                logger.error(f"[end_stream] Error sending final transcript: {e}")
                        else:
                            logger.debug(f"[end_stream] No result from remaining audio")
                    else:
                        logger.debug(f"[end_stream] No remaining audio to process")

                    try:
                        await ws.send_json({"event": "done"})
                        logger.info(f"[end_stream] Done event sent")
                    except Exception as e:
                        logger.error(f"[end_stream] Error sending done event: {e}")
                    break

                elif msg_type == "cancel" or event == "cancel":
                    reason = msg.get('reason', 'unknown')
                    logger.info(f"[cancel] STT cancel received: reason={reason}")
                    try:
                        await ws.send_json({"event": "cancel_ack"})
                        logger.debug(f"[cancel] cancel_ack sent")
                    except Exception as e:
                        logger.error(f"[cancel] Error sending cancel_ack: {e}")
                    break

                else:
                    # Unknown JSON message type - log it
                    logger.warning(f"[JSON Message #{message_count}] ⚠️ UNKNOWN message type: {list(msg.keys())}")
                    logger.debug(f"[JSON Message #{message_count}] Full message: {msg}")
                    continue

            else:
                # Unknown message format
                logger.warning(f"[Message #{message_count}] ⚠️ UNKNOWN message format: {list(message.keys())}")
                continue

    except WebSocketDisconnect:
        logger.info(f"═══════════════════════════════════════════════════════════")
        logger.info(f"STT WS DISCONNECTED: session_id={session_id}")
        logger.info(f"  - Messages: {message_count}")
        logger.info(f"  - Binary frames: {audio_frame_count}")
        logger.info(f"  - JSON audio_chunks: {audio_chunk_count}")
        logger.info(f"  - Total samples: {total_audio_samples} ({total_audio_samples / 16000:.2f}s)")
        logger.info(f"═══════════════════════════════════════════════════════════")
    except Exception as e:
        logger.error(f"STT error: {type(e).__name__}: {e}", exc_info=True)
        try:
            await ws.close(code=1011, reason=str(e))
        except:
            pass
