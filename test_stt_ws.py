# import asyncio
# import websockets
# import base64
# import numpy as np
# import wave
# import json
# from scipy.signal import resample

# SAMPLE_RATE = 16000  # server expects 16kHz
# CHANNELS = 1
# SAMPLE_WIDTH = 2  # 16-bit PCM

# def read_wav_convert(path: str):
#     """Read a WAV file and convert to 16kHz mono 16-bit PCM if needed."""
#     wf = wave.open(path, "rb")
#     orig_rate = wf.getframerate()
#     orig_channels = wf.getnchannels()
#     orig_width = wf.getsampwidth()

#     raw = wf.readframes(wf.getnframes())
#     audio = np.frombuffer(raw, dtype=np.int16)

#     # If stereo, convert to mono
#     if orig_channels > 1:
#         audio = audio.reshape(-1, orig_channels)
#         audio = audio.mean(axis=1).astype(np.int16)

#     # If sample rate != 16kHz, resample
#     if orig_rate != SAMPLE_RATE:
#         num_samples = int(len(audio) * SAMPLE_RATE / orig_rate)
#         audio = resample(audio, num_samples).astype(np.int16)

#     return audio

# async def send_audio():
#     ws_url = "ws://localhost:8000/stt/stream"
#     async with websockets.connect(ws_url) as ws:
#         audio = read_wav_convert("output.wav")
#         chunk_id = 0
#         frames_per_chunk = SAMPLE_RATE // 4  # ~250ms chunks

#         for start in range(0, len(audio), frames_per_chunk):
#             chunk = audio[start:start + frames_per_chunk]
#             audio_chunk = base64.b64encode(chunk.tobytes()).decode("utf-8")

#             await ws.send(json.dumps({
#                 "type": "audio_chunk",
#                 "audio": audio_chunk,
#                 "chunk_id": f"chunk_{chunk_id:04d}"
#             }))

#             chunk_id += 1
#             await asyncio.sleep(0.05)

#         # indicate finished
#         await ws.send(json.dumps({
#             "type": "cancel",
#             "reason": "finished"
#         }))

#         # receive final server messages
#         async for msg in ws:
#             data = json.loads(msg)
#             print(data)
#             if data.get("type") == "cancelled":
#                 break

# asyncio.run(send_audio())

# import asyncio
# import websockets
# import base64
# import json
# import numpy as np
# import soundfile as sf
# import resampy

# WS_URL = "ws://localhost:8000/stt/stream"
# CHUNK_MS = 500  # milliseconds per chunk
# TARGET_SR = 16000  # Whisper expects 16kHz

# async def send_audio(wav_path: str):
#     # Load audio with soundfile
#     audio, sr = sf.read(wav_path, dtype='float32')
    
#     # Convert to mono if needed
#     if audio.ndim > 1:
#         audio = np.mean(audio, axis=1)
    
#     # Resample to 16kHz if needed
#     if sr != TARGET_SR:
#         audio = resampy.resample(audio, sr, TARGET_SR)
#         sr = TARGET_SR

#     # Convert float32 [-1,1] to PCM16
#     pcm16 = (audio * 32767).astype(np.int16)

#     # Connect to server
#     async with websockets.connect(WS_URL) as ws:
#         # Send audio in CHUNK_MS slices
#         samples_per_chunk = int(TARGET_SR * CHUNK_MS / 1000)
#         idx = 0
#         for start in range(0, len(pcm16), samples_per_chunk):
#             chunk = pcm16[start:start + samples_per_chunk]
#             b64_chunk = base64.b64encode(chunk.tobytes()).decode('utf-8')

#             await ws.send(json.dumps({
#                 "type": "audio_chunk",
#                 "audio": b64_chunk,
#                 "chunk_id": f"chunk_{idx:04d}"
#             }))
#             idx += 1
#             await asyncio.sleep(CHUNK_MS / 1000)

#         # Indicate finished
#         await ws.send(json.dumps({
#             "type": "cancel",
#             "reason": "finished"
#         }))

#         # Receive transcripts
#         async for msg in ws:
#             data = json.loads(msg)
#             if data.get("type") == "transcript":
#                 print(f"[STT] {data['text']} (final={data.get('is_final', False)})")
#             elif data.get("type") == "cancelled":
#                 print("[INFO] STT session ended by server.")
#                 break

# if __name__ == "__main__":
#     import sys
#     wav_file = sys.argv[1] if len(sys.argv) > 1 else "output.wav"
#     asyncio.run(send_audio(wav_file))



import asyncio
import websockets
import base64
import wave
import json
import numpy as np
from scipy import signal

WS_URL = "ws://localhost:8001/stt/stream/ws"
TARGET_SR = 16000  # Whisper expects 16kHz
CHUNK_MS = 500  # Send 500ms chunks

def convert_wav_to_16khz_mono(wav_path: str) -> np.ndarray:
    """
    Read WAV file and convert to 16kHz mono PCM16 format.
    Returns: numpy array of int16 samples
    """
    with wave.open(wav_path, "rb") as wf:
        # Get original parameters
        orig_sr = wf.getframerate()
        orig_channels = wf.getnchannels()
        orig_width = wf.getsampwidth()
        n_frames = wf.getnframes()
        
        print(f"[INFO] Original: {orig_sr}Hz, {orig_channels} channels, {orig_width} bytes/sample")
        
        # Read raw audio
        raw_data = wf.readframes(n_frames)
        
        # Convert to numpy array based on sample width
        if orig_width == 1:  # 8-bit
            audio = np.frombuffer(raw_data, dtype=np.uint8).astype(np.float32)
            audio = (audio - 128) / 128.0  # Convert to [-1, 1]
        elif orig_width == 2:  # 16-bit
            audio = np.frombuffer(raw_data, dtype=np.int16).astype(np.float32)
            audio = audio / 32768.0  # Convert to [-1, 1]
        elif orig_width == 3:  # 24-bit
            # Handle 24-bit audio
            audio = np.frombuffer(raw_data, dtype=np.uint8)
            audio = audio.reshape(-1, 3)
            audio = np.pad(audio, ((0, 0), (0, 1)), mode='constant')
            audio = audio.view(np.int32).astype(np.float32)
            audio = audio / 2147483648.0
        else:
            raise ValueError(f"Unsupported sample width: {orig_width}")
        
        # Convert stereo to mono if needed
        if orig_channels == 2:
            audio = audio.reshape(-1, 2)
            audio = np.mean(audio, axis=1)
        elif orig_channels > 2:
            audio = audio.reshape(-1, orig_channels)
            audio = np.mean(audio, axis=1)
        
        # Resample to 16kHz if needed
        if orig_sr != TARGET_SR:
            num_samples = int(len(audio) * TARGET_SR / orig_sr)
            audio = signal.resample(audio, num_samples)
            print(f"[INFO] Resampled from {orig_sr}Hz to {TARGET_SR}Hz")
        
        # Convert back to PCM16
        audio = np.clip(audio, -1.0, 1.0)  # Ensure in range
        pcm16 = (audio * 32767).astype(np.int16)
        
        print(f"[INFO] Converted to: {TARGET_SR}Hz, 1 channel, {len(pcm16)} samples ({len(pcm16)/TARGET_SR:.2f}s)")
        
        return pcm16

async def send_audio(wav_path: str):
    """
    Send audio file to STT WebSocket server in chunks.
    """
    print(f"[INFO] Loading audio from: {wav_path}")
    
    # Convert audio to proper format
    audio_data = convert_wav_to_16khz_mono(wav_path)
    
    # Connect to WebSocket
    print(f"[INFO] Connecting to {WS_URL}")
    async with websockets.connect(WS_URL) as ws:
        print("[INFO] Connected! Streaming audio...")
        
        # Calculate samples per chunk
        samples_per_chunk = int(TARGET_SR * CHUNK_MS / 1000)
        total_chunks = (len(audio_data) + samples_per_chunk - 1) // samples_per_chunk
        
        chunk_id = 0
        
        # Send audio in chunks
        for start in range(0, len(audio_data), samples_per_chunk):
            end = min(start + samples_per_chunk, len(audio_data))
            chunk = audio_data[start:end]

            
            # Encode to base64
            audio_b64 = base64.b64encode(chunk.tobytes()).decode('utf-8')
            
            # Send      
            await ws.send(json.dumps({
                "type": "audio_chunk",
                "audio": audio_b64,
                "chunk_id": f"chunk_{chunk_id:04d}"
            }))
            
            chunk_id += 1
            
            # Progress indicator
            if chunk_id % 10 == 0:
                progress = (chunk_id / total_chunks) * 100
                print(f"[PROGRESS] Sent {chunk_id}/{total_chunks} chunks ({progress:.1f}%)")
            
            # Simulate real-time streaming
            await asyncio.sleep(CHUNK_MS / 1000)
        
        print(f"[INFO] Sent all {chunk_id} chunks. Sending end signal...")
        
        # Signal end of stream
        await ws.send(json.dumps({
            "type": "end_stream"
        }))
        
        # Collect all transcripts
        full_transcript = []
        
        # Receive transcripts
        async for msg in ws:
            data = json.loads(msg)
            msg_type = data.get("type")
            
            if msg_type == "transcript":
                text = data.get("text", "")
                is_final = data.get("is_final", False)
                confidence = data.get("confidence", 0.0)
                
                print(f"[STT] {'[FINAL]' if is_final else '[PARTIAL]'} {text} (confidence: {confidence:.3f})")
                
                if is_final and text:
                    full_transcript.append(text)
                    
            elif msg_type == "complete":
                print("[INFO] Transcription complete!")
                break
                
            elif msg_type == "cancelled":
                reason = data.get("reason", "unknown")
                print(f"[INFO] Session cancelled: {reason}")
                break
        
        # Print full transcript
        if full_transcript:
            print("\n" + "="*60)
            print("FULL TRANSCRIPT:")
            print("="*60)
            print(" ".join(full_transcript))
            print("="*60)
        else:
            print("\n[WARNING] No transcript received!")

async def test_simple():
    """Quick test with a single chunk"""
    print("[TEST] Running simple test...")
    
    async with websockets.connect(WS_URL) as ws:
        # Create a simple test audio (1 second of silence)
        test_audio = np.zeros(TARGET_SR, dtype=np.int16)
        audio_b64 = base64.b64encode(test_audio.tobytes()).decode('utf-8')
        
        await ws.send(json.dumps({
            "type": "audio_chunk",
            "audio": audio_b64,
            "chunk_id": "test_001"
        }))
        
        await ws.send(json.dumps({"type": "end_stream"}))
        
        async for msg in ws:
            data = json.loads(msg)
            print(f"[RESPONSE] {data}")
            if data.get("type") in ["complete", "cancelled"]:
                break
        
        print("[TEST] Simple test complete!")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        wav_file = sys.argv[1]
    else:
        wav_file = "voices/default.wav"
    
    print("="*60)
    print("STT WebSocket Client Test")
    print("="*60)
    
    try:
        # Run main test
        asyncio.run(send_audio(wav_file))
        
        # Uncomment to run simple connectivity test
        # asyncio.run(test_simple())
        
    except FileNotFoundError:
        print(f"\n[ERROR] Audio file not found: {wav_file}")
        print("Usage: python test_client.py [path/to/audio.wav]")
    except websockets.exceptions.WebSocketException as e:
        print(f"\n[ERROR] WebSocket error: {e}")
        print("Is the server running at ws://localhost:8001?")
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")
        import traceback
        traceback.print_exc()