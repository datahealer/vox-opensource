import asyncio
import base64
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()

def pcm16_to_base64(pcm: bytes) -> str:
    return base64.b64encode(pcm).decode("utf-8")


@router.websocket("/stream/ws")
async def tts_stream(ws: WebSocket):
    from services.tts_service import get_tts_service
    tts_service = get_tts_service()
    
    await ws.accept()
    cancel_event = asyncio.Event()
    bytes_generated = 0

    try:
        while True:
            msg = await ws.receive_json()

            if msg["type"] == "request":
                async def run():
                    nonlocal bytes_generated
                    idx = 0

                    async for pcm in tts_service.stream(
                        text=msg["text"],
                        voice=msg.get("voice"),
                        language=msg.get("language"),
                        speed=msg.get("speed", 1.0),
                        cancel_event=cancel_event,
                    ):
                        bytes_generated += len(pcm)

                        await ws.send_json({
                            "type": "audio_chunk",
                            "chunk_id": f"chunk_{idx:04d}",
                            "audio": pcm16_to_base64(pcm),
                            "is_final": False,
                        })
                        idx += 1

                    await ws.send_json({
                        "type": "audio_chunk",
                        "audio": "",
                        "is_final": True,
                    })

                asyncio.create_task(run())

            elif msg["type"] == "cancel":
                cancel_event.set()
                await ws.send_json({
                    "type": "cancelled",
                    "reason": msg.get("reason"),
                    "bytes_generated": bytes_generated,
                })
                break

    except WebSocketDisconnect:
        cancel_event.set()
