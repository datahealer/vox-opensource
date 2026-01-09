# import asyncio
# import websockets
# import json

# async def test_stream():
#     url = "ws://127.0.0.1:8000/llm/stream/ws"  # or /llm/stream if using session version
#     async with websockets.connect(url) as ws:
#         # Send prompt
#         await ws.send(json.dumps({
#             "prompt": "Hello, can you explain quantum physics in simple terms?",
#             "session_id":"sess123",
#             "max_new_tokens": 50,
#             "temperature": 0.7,
#             "top_p": 0.9
#         }))

#         print("Streaming response:\n")
#         while True:
#             try:
#                 token = await ws.recv()
#                 if token == "[[END]]":
#                     print("\n✅ Stream ended")
#                     break
#                 print(token, end="", flush=True)
#             except websockets.ConnectionClosed:
#                 break

# asyncio.run(test_stream())


import asyncio
import websockets
import json

async def test_stream():
    url = "ws://127.0.0.1:8000/llm/stream/ws"

    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({
            "type": "request",
            "session_id": "sess123",
            "messages": [
                {"role": "user", "content": "Hello, can you explain quantum physics in simple terms?"}
            ],
            "max_new_tokens": 50
        }))

        print("Streaming response:\n")

        while True:
            try:
                msg = await ws.recv()
                data = json.loads(msg)

                if data["type"] == "token":
                    if data.get("is_final"):
                        print("\n\n✅ Stream ended")
                        break

                    print(data["text"], end="", flush=True)

                elif data["type"] == "error":
                    print("\n❌ Error:", data["message"])
                    break

            except websockets.ConnectionClosed:
                print("\n🔌 Connection closed")
                break

asyncio.run(test_stream())

