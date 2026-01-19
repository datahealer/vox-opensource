# STT Audio Reception Issue - Analysis & Diagnostic

## Problem Identified

**Main Server** is sending audio to AI Server's STT service, but the AI Server shows:
- ✅ WebSocket connected
- ✅ Init message received and ack sent
- ❌ **NO audio frames received** (Messages count = 1, Binary frames = 0)
- ❌ **STT timeout** every 5 seconds

---

## What's Happening

### Main Server (Server 1) Logs
```
12:56:14 - DEBUG - Sending 320 bytes PCM16 to STT client
12:56:14 - DEBUG - PCM16 audio sent to STT successfully
12:56:19 - WARNING - STT timeout after 5 seconds  ← Waiting for response that never comes
```

### AI Server (Server 2) Logs BEFORE Enhancement
```
[2026-01-12 12:56:05] [INFO] [stt_router] STT WS CONNECTED: session_id=...
[2026-01-12 12:56:05] [INFO] [stt_router] [Init] init_ack sent

⏳ [NOTHING AFTER THIS - No audio logs]

[Result after 60 seconds]
STT WS DISCONNECTED: session_id=...
  - Messages: 1  ← Only init
  - Binary frames: 0  ← No audio!
  - Total samples: 0
```

---

## Root Cause: Audio Not Reaching STT Handler

The WebSocket connection exists and can receive messages (init worked), but subsequent audio frames are NOT being logged. This suggests:

1. **Most Likely**: Audio frames are being sent but the `ws.receive()` loop isn't logging them
2. **Also Possible**: Main server stopped sending after init
3. **Network Issue**: Frames lost between servers (but init worked fine)

---

## Enhanced Logging Solution

### What I Added

**1. Detailed Message Reception Logging**
```python
logger.info(f"[Loop] Waiting for message #{message_count + 1}...")
message = await ws.receive()
message_count += 1
logger.info(f"[Message #{message_count}] RECEIVED: Keys: {list(message.keys())}")
```

**2. Binary Frame Logging (✅ = new)**
```python
if "bytes" in message:
    logger.info(f"[Binary Frame #{audio_frame_count}] ✅ RECEIVED: {len(data)} bytes")
    logger.info(f"[Binary Frame #{audio_frame_count}] ✅ Buffer updated: {len(audio_buffer)} samples")
```

**3. Status Logging After Init**
```python
logger.info(f"[Init] 🔄 Ready to receive audio frames on this WebSocket")
```

**4. Catch-All for Unknown Messages**
```python
else:
    logger.warning(f"[Message #{message_count}] ⚠️ UNKNOWN message format")
```

---

## Diagnostic Tool Added

**File**: `diagnostic_stt.py`

This tool:
1. Connects to STT WebSocket
2. Sends init message
3. Sends 10 binary audio frames (320 bytes each)
4. Sends end_stream
5. Reports what was received

**Expected Output** (if working):
```
✅ Connected! WebSocket established
✅ Init message sent
✅ Received: {'event': 'init_ack'}
✅ [1/10] Binary frame sent
✅ [2/10] Binary frame sent
... (more frames) ...
✅ Test completed successfully!
```

**Actual Output** (if broken):
```
✅ Connected! WebSocket established
✅ Init message sent
✅ Received: {'event': 'init_ack'}
✅ [1/10] Binary frame sent
⏳ [TIMES OUT - no response]
```

---

## How to Debug Now

### Step 1: Start AI Server with Enhanced Logging
```bash
cd /home/vansh/vox-opensource-clone/vox-opensource-alok
uvicorn app:app --host 127.0.0.1 --port 8002 2>&1 | tee server.log
```

### Step 2: Run Diagnostic
```bash
python3 diagnostic_stt.py
```

### Step 3: Monitor Logs
```bash
# In another terminal
tail -f server.log | grep -E "RECEIVED|DISCONNECTED|Ready to receive|Binary Frame"
```

### Step 4: Interpret Results

#### **If you see "Binary Frame" messages:**
✅ Audio is being received!
❌ Problem is in transcription logic (Faster Whisper)
→ Check [faster_whisper_service.py](faster_whisper_service.py) logs

#### **If you DON'T see "Binary Frame" messages:**
❌ Audio NOT reaching AI server
→ Check network connectivity
→ Verify Main Server is sending to correct endpoint
→ Check Main Server logs for send errors

---

## Key Changes Made

### File: `routes/stt_router.py`

**Before**: Silent about incoming frames (only logged JSON events)
```
[Init] init_ack sent
```

**After**: Logs EVERY message received
```
[Loop] Waiting for message #2...
[Message #2] RECEIVED: Keys: ['bytes']
[Binary Frame #1] ✅ RECEIVED: 320 bytes
[Binary Frame #1] ✅ Buffer updated: 320 samples (0.02s)
```

---

## New Files Created

1. **[diagnostic_stt.py](diagnostic_stt.py)** (4.2 KB)
   - Standalone diagnostic tool
   - Tests audio frame reception
   - Verifies WebSocket communication

2. **[STT_DIAGNOSTIC_GUIDE.md](STT_DIAGNOSTIC_GUIDE.md)** (7.0 KB)
   - Step-by-step diagnostic instructions
   - Troubleshooting tree
   - Expected outputs for each scenario

---

## Quick Reference: What Logs Mean

### ✅ Logs You SHOULD See

```
[stt_router] STT WS CONNECTED: session_id=...
[stt_router] [Message #1] RECEIVED: Keys: ['text']
[stt_router] [JSON Message #1] ✅ RECEIVED: type=None, event=init
[stt_router] [Init] ✅ init_ack sent
[stt_router] 🔄 Ready to receive audio frames on this WebSocket
[stt_router] [Message #2] RECEIVED: Keys: ['bytes']
[stt_router] [Binary Frame #1] ✅ RECEIVED: 320 bytes
[stt_router] [Binary Frame #1] ✅ Buffer updated: 320 samples (0.02s)
```

### ⚠️ Logs That Indicate Problems

```
[Loop] Timeout waiting for message  ← ws.receive() timing out
[Binary Frame] Error: ...            ← Audio decode error
[Message] UNKNOWN message format     ← Getting unexpected data
[Loop] WebSocket disconnected        ← Connection dropped
```

---

## Expected Behavior AFTER Fix

Once audio reception is working, you should see:

```
[2026-01-12 12:56:05] [stt_router] STT WS CONNECTED: session_id=caf6e09d-3f8c-4e12-8646-92fa79874ef8
[2026-01-12 12:56:05] [stt_router] [Init] ✅ init_ack sent
[2026-01-12 12:56:14] [stt_router] [Message #2] RECEIVED: Keys: ['bytes']
[2026-01-12 12:56:14] [stt_router] [Binary Frame #1] ✅ RECEIVED: 320 bytes
[2026-01-12 12:56:14] [stt_router] [Binary Frame #1] ✅ Buffer updated: 320 samples (0.02s)

[whisper_stt] [transcribe_chunk #1] Audio sufficient, starting transcription...
[whisper_stt] [transcribe_chunk #1] Segment 1: text='hello'
[whisper_stt] [transcribe_chunk #1] RETURNING: {'text': 'hello', ...}

[stt_router] [Message #N] Transcript #1: 'hello'
[stt_router] [Message #N] Sent transcript #1 to client
```

---

## Next Actions

1. ✅ Enhanced logging deployed to `routes/stt_router.py`
2. ✅ Diagnostic tool created: `diagnostic_stt.py`
3. ✅ Diagnostic guide created: `STT_DIAGNOSTIC_GUIDE.md`
4. 📋 **Run diagnostic** to identify where audio is lost
5. 🔧 Apply fix based on diagnostic results

---

## Diagnostic Commands (Copy-Paste Ready)

```bash
# Terminal 1: Start AI server
cd /home/vansh/vox-opensource-clone/vox-opensource-alok && \
uvicorn app:app --host 127.0.0.1 --port 8002 2>&1 | tee server.log

# Terminal 2: Run diagnostic
cd /home/vansh/vox-opensource-clone/vox-opensource-alok && \
python3 diagnostic_stt.py

# Terminal 3: Monitor logs
cd /home/vansh/vox-opensource-clone/vox-opensource-alok && \
tail -f server.log | grep -E "RECEIVED|DISCONNECTED|Ready to receive|Binary Frame|Waiting for"
```

---

## Outcome Possible Scenarios

| Scenario | Log Shows | Next Step |
|----------|-----------|-----------|
| **Audio Received** | `Binary Frame #1 ✅ RECEIVED` | Check Whisper transcription logs |
| **Audio Not Received** | Only `init_ack sent` then `DISCONNECTED` | Check Main Server sending |
| **Frame Size Wrong** | `Binary Frame: 160 bytes` (not 320) | Verify audio format conversion |
| **Connection Drops** | `WebSocket disconnected` after init | Check network/firewall |
| **Loop Timeout** | `Timeout waiting for message` | Check ws.receive() settings |

---

**The enhanced logging will definitively show WHERE the audio is being lost!**

Run diagnostic and share the output to identify the exact issue. 🔍

