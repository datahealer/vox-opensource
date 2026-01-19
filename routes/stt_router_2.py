import asyncio
import json
import time
import wave
from pathlib import Path

import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core.logger import setup_logger

router = APIRouter()
logger = setup_logger("stt_router")

RECORD_DIR = Path("stt_incoming_audio")
RECORD_DIR.mkdir(exist_ok=True)

SAMPLE_RATE = 16000
MAX_BUFFER_SECONDS = 30
MAX_BUFFER_SAMPLES = SAMPLE_RATE * MAX_BUFFER_SECONDS


@router.websocket("/stream")
async def stt_stream(ws: WebSocket):
    from services.stt_service import get_stt_service

    stt_service = get_stt_service()
    await ws.accept()

    # ──────────────────────────────
    # Session / state
    # ──────────────────────────────
    session_id = (ws.query_params.get("session_id") or "unknown").replace("/", "_")
    recording_enabled = False
    expected_chunk_id = 1

    audio_buffer = np.zeros(0, dtype=np.float32)
    total_samples = 0

    wav_recorder = None
    wav_path = None

    stt_service.reset()

    logger.info("═══════════════════════════════════════════════")
    logger.info(f"STT WS CONNECTED: session_id={session_id}")
    logger.info("═══════════════════════════════════════════════")

    try:
        while True:
            message = await ws.receive()

            # ──────────────────────────────
            # BINARY PCM16 AUDIO
            # ──────────────────────────────
            if "bytes" in message:
                if not recording_enabled:
                    continue

                data: bytes = message["bytes"]

                # Record
                if wav_recorder:
                    wav_recorder.writeframes(data)

                # Convert → float32
                chunk = (
                    np.frombuffer(data, dtype=np.int16)
                    .astype(np.float32) / 32768.0
                )

                audio_buffer = np.concatenate([audio_buffer, chunk])
                total_samples += len(chunk)

            # ──────────────────────────────
            # JSON MESSAGES
            # ──────────────────────────────
            elif "text" in message:
                try:
                    msg = json.loads(message["text"])
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON received")
                    continue

                event = msg.get("event")
                msg_type = msg.get("type")

                # ───────── INIT ─────────
                if event == "init":
                    recording_enabled = True

                    wav_path = RECORD_DIR / f"stt_{session_id}_{int(time.time())}.wav"
                    wav_recorder = wave.open(str(wav_path), "wb")
                    wav_recorder.setnchannels(1)
                    wav_recorder.setsampwidth(2)
                    wav_recorder.setframerate(SAMPLE_RATE)

                    logger.info(f"[STT] 🎙️ Recording started → {wav_path}")
                    await ws.send_json({"event": "init_ack"})
                    continue

                # ───────── AUDIO CHUNK (JSON) ─────────
                if msg_type == "audio_chunk" or event == "audio_chunk":
                    if not recording_enabled:
                        continue

                    chunk_id = msg.get("chunk_id")
                    is_final = msg.get("is_final", False)
                    b64_audio = msg.get("audio")

                    if chunk_id != expected_chunk_id:
                        logger.error(
                            f"Chunk order error: expected={expected_chunk_id}, got={chunk_id}"
                        )
                        audio_buffer = np.zeros(0, dtype=np.float32)
                        expected_chunk_id = 1
                        continue

                    expected_chunk_id += 1

                    if not b64_audio:
                        continue

                    # Decode → float32
                    chunk = stt_service.decode_pcm_base64(b64_audio)

                    # Record SAME audio
                    pcm16 = (chunk * 32767).astype(np.int16).tobytes()
                    if wav_recorder:
                        wav_recorder.writeframes(pcm16)

                    audio_buffer = np.concatenate([audio_buffer, chunk])
                    total_samples += len(chunk)

                    if not is_final:
                        continue

                    # Process full utterance
                    result = await stt_service.transcribe_complete_utterance(audio_buffer)
                    if result:
                        await ws.send_json({
                            "event": "transcript",
                            "text": result["text"]
                        })

                    audio_buffer = np.zeros(0, dtype=np.float32)
                    expected_chunk_id = 1
                    continue

                # ───────── END STREAM ─────────
                if msg_type == "end_stream" or event == "end_stream":
                    if len(audio_buffer) > 0:
                        result = stt_service.process_remaining(audio_buffer)
                        if result:
                            await ws.send_json({
                                "event": "transcript",
                                "text": result["text"]
                            })

                    await ws.send_json({"event": "done"})
                    break

                # ───────── CANCEL ─────────
                if msg_type == "cancel" or event == "cancel":
                    await ws.send_json({"event": "cancel_ack"})
                    break

            # ──────────────────────────────
            # BUFFER SAFETY
            # ──────────────────────────────
            if len(audio_buffer) > MAX_BUFFER_SAMPLES:
                logger.error("Audio buffer overflow – trimming")
                audio_buffer = audio_buffer[-MAX_BUFFER_SAMPLES:]

    except WebSocketDisconnect:
        logger.info("STT WS DISCONNECTED")

    except Exception as e:
        logger.error(f"STT error: {type(e).__name__}: {e}", exc_info=True)
        try:
            await ws.close(code=1011)
        except:
            pass

    finally:
        if wav_recorder:
            wav_recorder.close()
            logger.info(f"[STT] 🎙️ Recording closed → {wav_path}")

        logger.info(
            f"Session finished: samples={total_samples} "
            f"({total_samples / SAMPLE_RATE:.2f}s)"
        )
