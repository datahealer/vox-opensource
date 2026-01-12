import asyncio
import base64
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import numpy as np

router = APIRouter()

@router.websocket("/stream")
async def stt_stream(ws: WebSocket):
    from services.stt_service import get_stt_service
    stt_service = get_stt_service()
    await ws.accept()
    
    audio_buffer = np.zeros(0, dtype=np.float32)
    stt_service.reset()  # Reset state for new session

    try:
        while True:
            msg = await ws.receive_json()
            msg_type = msg.get("type")

            if msg_type == "audio_chunk":
                b64_audio = msg.get("audio")
                if not b64_audio:
                    continue

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
                
            elif msg_type == "end_stream":
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
                
            elif msg_type == "cancel":
                await ws.send_json({
                    "type": "cancelled",
                    "reason": msg.get("reason", "unknown")
                })
                break

    except WebSocketDisconnect:
        print("[STT] Client disconnected")
    except Exception as e:
        print(f"[STT] Error: {e}")
        import traceback
        traceback.print_exc()
        try:
            await ws.close(code=1011, reason=str(e))
        except:
            pass