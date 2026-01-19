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
    session_id = "test-session-123"
    url = f"ws://127.0.0.1:8000/llm/stream?session_id={session_id}"

    async with websockets.connect(url) as ws:
        # Send init message first
        await ws.send(json.dumps({
            "event": "init",
            "call_session_id": session_id,
            "service_type": "llm"
        }))

        # Wait for init_ack
        msg = await ws.recv()
        init_ack = json.loads(msg)
        print(f"Received: {init_ack}")

        # Send generate request
        await ws.send(json.dumps({
            "event": "generate",
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Hello, can you explain quantum physics in simple terms?"}
            ],
            "max_tokens": 100
        }))

        print("\nStreaming response:\n")
        token_count = 0

        while True:
            try:
                msg = await ws.recv()
                data = json.loads(msg)
                event = data.get("event")

                if event == "token":
                    token_count += 1
                    print(data["text"], end="", flush=True)

                elif event == "done":
                    print(f"\n\n✅ Stream ended")
                    print(f"Total tokens: {data.get('total_tokens')}")
                    print(f"Finish reason: {data.get('finish_reason')}")
                    break

                elif event == "error":
                    print(f"\n❌ Error: {data.get('message')}")
                    print(f"Error code: {data.get('error_code')}")
                    break

            except websockets.ConnectionClosed:
                print("\n🔌 Connection closed")
                break

asyncio.run(test_stream())

