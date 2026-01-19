#!/usr/bin/env python3
"""
Diagnostic script to verify STT WebSocket communication.
This helps identify if audio is being received by the STT service.
"""

import asyncio
import websockets
import json
import numpy as np
import base64
import sys
from datetime import datetime

# Configuration
STT_URL = "ws://localhost:8002/stt/stream?session_id=test-diagnostic-session"
TARGET_SR = 16000
CHUNK_MS = 20  # 20ms chunks
NUM_CHUNKS = 10  # Send 10 chunks

async def log(message, level="INFO"):
    """Log with timestamp"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [{level}] {message}")

async def diagnostic_test():
    """Run diagnostic test"""
    try:
        await log(f"🔍 Starting diagnostic test")
        await log(f"📍 STT URL: {STT_URL}")
        await log(f"📍 Target: 16kHz mono PCM16 binary frames")
        await log(f"📍 Will send {NUM_CHUNKS} chunks of 20ms each")

        # Connect
        await log("🔗 Connecting to STT service...")
        async with websockets.connect(STT_URL) as ws:
            await log(f"✅ Connected! WebSocket established")

            # Send init
            await log("📤 Sending init message...")
            await ws.send(json.dumps({
                "event": "init",
                "call_session_id": "test-diagnostic-session",
                "service_type": "stt"
            }))
            await log("✅ Init message sent")

            # Wait for init_ack
            await log("⏳ Waiting for init_ack...")
            response = await ws.recv()
            data = json.loads(response)
            await log(f"✅ Received: {data}")

            if data.get("event") != "init_ack":
                await log(f"⚠️ Expected init_ack but got: {data}", "WARNING")

            # Generate and send dummy audio
            await log(f"🔊 Generating {NUM_CHUNKS} audio chunks...")
            samples_per_chunk = int(TARGET_SR * CHUNK_MS / 1000)  # 320 samples for 20ms @ 16kHz

            for chunk_id in range(NUM_CHUNKS):
                # Generate dummy PCM16 audio (small values to avoid clipping)
                audio_pcm16 = np.random.randint(-1000, 1000, samples_per_chunk, dtype=np.int16)

                # Send as binary frame
                await log(f"📤 [{chunk_id+1}/{NUM_CHUNKS}] Sending binary audio frame: {len(audio_pcm16.tobytes())} bytes")
                await ws.send(audio_pcm16.tobytes())
                await log(f"✅ [{chunk_id+1}/{NUM_CHUNKS}] Binary frame sent")

                # Wait a bit between frames
                await asyncio.sleep(CHUNK_MS / 1000)

                # Check if any response
                try:
                    response = await asyncio.wait_for(ws.recv(), timeout=0.1)
                    data = json.loads(response) if response.startswith('{') else response
                    await log(f"📥 [{chunk_id+1}/{NUM_CHUNKS}] Received response: {data}")
                except asyncio.TimeoutError:
                    pass  # No immediate response

            # Send end_stream
            await log("📤 Sending end_stream...")
            await ws.send(json.dumps({"event": "end_stream"}))
            await log("✅ end_stream sent")

            # Wait for done
            await log("⏳ Waiting for done event...")
            try:
                response = await asyncio.wait_for(ws.recv(), timeout=2)
                data = json.loads(response)
                await log(f"✅ Received: {data}")
            except asyncio.TimeoutError:
                await log("⚠️ Timeout waiting for done event", "WARNING")

            await log("✅ Test completed successfully!")

    except Exception as e:
        await log(f"❌ Error: {e}", "ERROR")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("\n" + "="*70)
    print("STT WEBSOCKET DIAGNOSTIC TEST")
    print("="*70 + "\n")

    asyncio.run(diagnostic_test())

    print("\n" + "="*70)
    print("Diagnostic complete. Check AI server logs for 'Binary Frame' messages.")
    print("="*70 + "\n")
