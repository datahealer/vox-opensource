# import asyncio
# import websockets
# import wave

# SAMPLE_RATE = 24000
# OUTPUT_FILE = "output.wav"

# async def main():
#     audio_data = bytearray()

#     async with websockets.connect("ws://localhost:8000/tts/stream/ws") as ws:
#         # Send TTS request
#         await ws.send(
#             '{"type":"request","text":"The weather is sunny today","language":"en","speed":1.0}'
#         )

#         while True:
#             msg = await ws.recv()

#             if isinstance(msg, bytes):
#                 # If server sends raw PCM bytes, append directly
#                 audio_data.extend(msg)
#             else:
#                 # If server sends JSON, parse it
#                 import json
#                 data = json.loads(msg)
#                 if data.get("type") == "audio_chunk" and "pcm16" in data:
#                     audio_data.extend(bytes(data["pcm16"]))
#                 if data.get("is_final", False):
#                     break

#     # Save WAV
#     with wave.open(OUTPUT_FILE, "wb") as wf:
#         wf.setnchannels(1)
#         wf.setsampwidth(2)  # 16-bit PCM
#         wf.setframerate(SAMPLE_RATE)
#         wf.writeframes(audio_data)

#     print(f"Saved TTS output to {OUTPUT_FILE}")

# asyncio.run(main())


import asyncio
import websockets
import json
import base64
import numpy as np
import wave

SAMPLE_RATE = 24000  # must match your XTTSService
OUTPUT_FILE = "output.wav"

async def main():
    audio_chunks = []

    async with websockets.connect("ws://localhost:8001/tts/stream/ws") as ws:
        # Send TTS request
        await ws.send(json.dumps({
            "type": "request",
            "text": "Hello this is your virtual assistant",
            "language": "en",
            "speed": 1.0
        }))

        # Receive chunks
        async for msg in ws:
            data = json.loads(msg)
            # print(data)  # <-- uncomment if you want to inspect messages

            if data["type"] == "audio_chunk":
                if data.get("is_final"):
                    break

                # decode base64 back to PCM16
                chunk_bytes = base64.b64decode(data["audio"])
                audio_chunks.append(np.frombuffer(chunk_bytes, dtype=np.int16))

    # Combine all chunks into a single array
    audio = np.concatenate(audio_chunks)

    # Save as WAV
    with wave.open(OUTPUT_FILE, "wb") as wf:
        wf.setnchannels(1)        # mono
        wf.setsampwidth(2)        # 16-bit PCM
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio.tobytes())

    print(f"Saved TTS output to {OUTPUT_FILE}")

# Run the async function
asyncio.run(main())

# import os
# from TTS.api import TTS

# # Ensure the directory exists
# os.makedirs("voices", exist_ok=True)

# tts = TTS(model_name="tts_models/en/ljspeech/tacotron2-DDC", gpu=False)

# tts.tts_to_file(
#     text="Hello, this is my default speaker for Vox TTS.",
#     file_path="voices/default.wav"
# )
