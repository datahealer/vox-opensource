import asyncio
import websockets
import json

async def test_stream():
    url = "ws://127.0.0.1:8000/quenRouter/ws/generate"  # or /llm/stream if using session version
    async with websockets.connect(url) as ws:
        # Send prompt
        await ws.send(json.dumps({
            "prompt": "Hello, can you explain quantum physics in simple terms?",
            "max_new_tokens": 50,
            "temperature": 0.7,
            "top_p": 0.9
        }))

        print("Streaming response:\n")
        while True:
            try:
                token = await ws.recv()
                if token == "[[END]]":
                    print("\n✅ Stream ended")
                    break
                print(token, end="", flush=True)
            except websockets.ConnectionClosed:
                break

asyncio.run(test_stream())
