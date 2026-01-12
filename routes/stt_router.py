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
            # Use receive() to get either text or binary message
            try:
                message = await ws.receive()
                logger.debug(f"STT received message: {list(message.keys())}")
            except Exception as e:
                logger.debug(f"STT receive error: {type(e).__name__}: {e}")
                continue

            # Handle binary audio frames
            if "bytes" in message:
                data = message["bytes"]
                logger.debug(f"STT received binary frame: {len(data)} bytes")
                # Convert binary PCM16 to float32 and append to buffer
                chunk = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                audio_buffer = np.concatenate([audio_buffer, chunk])
                continue

            # Handle JSON messages
            if "text" in message:
                try:
                    msg = json.loads(message["text"])
                except json.JSONDecodeError:
                    logger.debug("Received invalid JSON")
                    continue

                # Handle JSON command messages
                msg_type = msg.get("type")
                event = msg.get("event")
                logger.debug(f"STT received JSON: type={msg_type}, event={event}")

                if event == "init":
                    logger.info(f"STT init received (session_id={session_id})")
                    # Acknowledge init message
                    try:
                        await ws.send_json({"event": "init_ack"})
                        logger.debug(f"STT init_ack sent")
                    except Exception as e:
                        logger.error(f"Failed to send init_ack: {e}")
                        break
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
                            "event": "transcript",
                            "text": result["text"]
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
                                "event": "transcript",
                                "text": result["text"]
                            })

                    await ws.send_json({"event": "done"})
                    break

                elif msg_type == "cancel" or event == "cancel":
                    logger.info(f"STT cancel received: reason={msg.get('reason', 'unknown')}")
                    await ws.send_json({
                        "event": "cancel_ack"
                    })
                    break


    except WebSocketDisconnect:
        logger.debug("STT client disconnected")
    except Exception as e:
        logger.error(f"STT error: {e}")
        try:
            await ws.close(code=1011, reason=str(e))
        except:
            pass
