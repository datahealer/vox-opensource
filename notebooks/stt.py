import asyncio
import json
import sys

try:
    import websockets
except ImportError:
    print("websockets not installed, trying to import...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "websockets"])
    import websockets

async def test():
    try:
        print("Connecting to ws://127.0.0.1:8002/stt/stream...")
        # Use shorter timeout to fail faster
        async with websockets.connect(
            "ws://127.0.0.1:8002/stt/stream?session_id=test124",
            ping_interval=None,  # Disable ping/pong
            close_timeout=5
        ) as ws:
            print("✓ Connected!")

            # Send init message as JSON
            init_msg = {
                "event": "init",
                "call_session_id": "test123",
                "service_type": "stt"
            }
            print(f"Sending init: {init_msg}")
            await ws.send(json.dumps(init_msg))
            print("✓ Init sent, waiting for response...")

            # Try to receive response with timeout
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=3.0)
                print(f"✓ Received: {msg}")
            except asyncio.TimeoutError:
                print("✗ No response from server to init")

    except asyncio.TimeoutError:
        print("✗ Timeout during connection handshake")
    except ConnectionRefusedError:
        print("✗ Connection refused")
    except OSError as e:
        print(f"✗ Connection error: {e}")
    except Exception as e:
        print(f"✗ {type(e).__name__}: {e}")

print("Python version:", sys.version)
print("Starting async test...")
asyncio.run(test())
