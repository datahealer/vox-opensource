# STT Diagnostic Guide - Audio Reception Issue

## Problem Summary

Main server is sending audio to AI Server (Server 2), but:
- ❌ **No audio reception logs** on AI server
- ❌ **STT timeout** after 5 seconds (repeatedly)
- ❌ **No transcriptions** returned

---

## Root Cause Analysis

Looking at the logs:

**Main Server (sends):**
```
2026-01-12 12:56:14 - DEBUG - Sending 320 bytes PCM16 to STT client
2026-01-12 12:56:14 - DEBUG - PCM16 audio sent to STT successfully
2026-01-12 12:56:19 - WARNING - STT timeout after 5 seconds
```

**AI Server (should receive):**
```
[2026-01-12 12:56:05] [Init] ✅ init_ack sent - now entering message receive loop
[2026-01-12 12:56:05] 🔄 Ready to receive audio frames on this WebSocket

⚠️ [NO LOGS FOR AUDIO RECEPTION]  ⚠️

[2026-01-12 12:56:48] STT WS DISCONNECTED: session_id=...
  - Messages: 1 (only init message)
  - Binary frames: 0  ← This is the problem!
```

**The Issue:** Messages are being sent but NOT received by the STT WebSocket listener.

---

## Possible Causes

1. **Audio not reaching Server 2** (network/DNS issue)
2. **WebSocket connection dropped after init** (TCP reset)
3. **Message receive loop hanging** (asyncio issue)
4. **Wrong endpoint** (audio sent to different port/path)
5. **Firewall/Network** blocking frames (but init works?)

---

## Diagnostic Steps

### Step 1: Run the Diagnostic Test

```bash
cd /home/vansh/vox-opensource-clone/vox-opensource-alok

# Terminal 1: Start AI server
uvicorn app:app --host 127.0.0.1 --port 8002 2>&1 | tee server.log

# Terminal 2: Run diagnostic
python3 diagnostic_stt.py
```

### Step 2: Monitor AI Server Logs

```bash
# Terminal 3: Watch logs in real-time
tail -f server.log | grep -E "(Binary Frame|audio_chunk|Message #|DISCONNECTED)"
```

### Step 3: Interpret Results

#### ✅ **If you see "Binary Frame" logs:**
```
[2026-01-12 12:56:05] [INFO] [stt_router] [Init] ✅ init_ack sent
[2026-01-12 12:56:05] [INFO] [stt_router] [Binary Frame #1] ✅ RECEIVED: 320 bytes
[2026-01-12 12:56:05] [INFO] [stt_router] [Binary Frame #2] ✅ RECEIVED: 320 bytes
```
**Meaning:** Audio reception is working! Problem is in transcription logic.

#### ❌ **If you DON'T see "Binary Frame" logs:**
```
[2026-01-12 12:56:05] [INFO] [stt_router] [Init] ✅ init_ack sent
[2026-01-12 12:56:05] [INFO] [stt_router] 🔄 Ready to receive audio frames
⏳ [WAITS BUT NO LOGS]
[2026-01-12 12:56:10] [INFO] [stt_router] STT WS DISCONNECTED: session_id=...
  - Messages: 1
  - Binary frames: 0
```
**Meaning:** Audio NOT reaching Server 2. Check:
- Is Main Server actually sending to localhost:8002?
- Is the session_id matching?
- Network/firewall blocking?

---

## What the Diagnostic Does

1. **Connects** to `ws://localhost:8002/stt/stream`
2. **Sends init** message
3. **Waits for init_ack** (should arrive)
4. **Sends 10 binary audio frames** (320 bytes each = 20ms @ 16kHz)
5. **Sends end_stream**
6. **Waits for done event**

---

## Expected Diagnostic Output

### ✅ **Healthy Output:**
```
[2026-01-12 12:56:05] [INFO] 🔍 Starting diagnostic test
[2026-01-12 12:56:05] [INFO] 🔗 Connecting to STT service...
[2026-01-12 12:56:05] [INFO] ✅ Connected! WebSocket established
[2026-01-12 12:56:05] [INFO] 📤 Sending init message...
[2026-01-12 12:56:05] [INFO] ✅ Init message sent
[2026-01-12 12:56:05] [INFO] ⏳ Waiting for init_ack...
[2026-01-12 12:56:05] [INFO] ✅ Received: {'event': 'init_ack'}
[2026-01-12 12:56:05] [INFO] 🔊 Generating 10 audio chunks...
[2026-01-12 12:56:05] [INFO] 📤 [1/10] Sending binary audio frame: 320 bytes
[2026-01-12 12:56:05] [INFO] ✅ [1/10] Binary frame sent
... (more frames) ...
[2026-01-12 12:56:06] [INFO] ✅ Test completed successfully!
```

### ❌ **If Connection Fails:**
```
[2026-01-12 12:56:05] [INFO] 🔗 Connecting to STT service...
[2026-01-12 12:56:05] [ERROR] ❌ Error: [Errno 111] Connection refused
```
**Fix:** Make sure AI server is running on port 8002

### ❌ **If Init Fails:**
```
[2026-01-12 12:56:05] [INFO] ✅ Connected! WebSocket established
[2026-01-12 12:56:05] [INFO] ⏳ Waiting for init_ack...
[2026-01-12 12:56:10] [ERROR] ❌ Error: timeout
```
**Fix:** Check stt_router.py init_ack sending

### ❌ **If Audio Not Logged:**
```
[2026-01-12 12:56:05] [INFO] ✅ init_ack received
[2026-01-12 12:56:05] [INFO] 📤 [1/10] Sending binary audio frame: 320 bytes
[2026-01-12 12:56:05] [INFO] ✅ [1/10] Binary frame sent
[2026-01-12 12:56:06] [INFO] 📤 [2/10] Sending binary audio frame: 320 bytes
⏳ [CONTINUES SENDING BUT NO SERVER RESPONSE]
```
**Meanwhile on AI server logs:**
```
[Init] ✅ init_ack sent
🔄 Ready to receive audio frames

⏳ [NOTHING - ws.receive() is blocked or hanging]

STT WS DISCONNECTED
  - Messages: 1
  - Binary frames: 0
```
**Fix:** WebSocket connection likely dropped or not receiving frames

---

## AI Server Logs to Check

### Connection Phase
```
[stt_router] STT WS CONNECTED: session_id=...
[stt_router] [JSON Message #1] ✅ RECEIVED: type=None, event=init
[stt_router] [Init] ✅ init_ack sent
[stt_router] 🔄 Ready to receive audio frames on this WebSocket
```

### Audio Reception Phase
**Should see:**
```
[stt_router] [Message #2] RECEIVED: Keys: ['bytes']
[stt_router] [Binary Frame #1] ✅ RECEIVED: 320 bytes
[stt_router] [Binary Frame #1] ✅ Buffer updated: 320 samples (0.02s)
[stt_router] [Message #3] RECEIVED: Keys: ['bytes']
[stt_router] [Binary Frame #2] ✅ RECEIVED: 320 bytes
```

### Disconnection Phase
```
[stt_router] STT WS DISCONNECTED: session_id=...
  - Messages: 11 (init + 10 frames)
  - Binary frames: 10
  - Total samples: 3200 (0.20s)
```

---

## Troubleshooting Tree

```
Does diagnostic connect?
├─ NO → AI server not running on 8002
│       FIX: Check uvicorn command
│
└─ YES
   └─ Does init_ack arrive?
      ├─ NO → stt_router.py init handler broken
      │       FIX: Check Init event handler
      │
      └─ YES
         └─ Are audio frames logged?
            ├─ NO → Main server not sending OR
            │       WebSocket dropped after init
            │       FIX 1: Check Main Server logs
            │       FIX 2: Check network connectivity
            │       FIX 3: Increase ws.receive() timeout
            │
            └─ YES
               └─ Transcription logic issue
                   FIX: Check faster_whisper_service.py
```

---

## Next Steps

1. **Run diagnostic**: `python3 diagnostic_stt.py`
2. **Check AI server logs**: `tail -f server.log | grep -E "(Binary Frame|Message #)"`
3. **Identify which phase fails** (connection, init, audio, done)
4. **Share output** of diagnostic + relevant logs section
5. **Apply fix** based on findings

---

## Key Metrics to Monitor

From diagnostic output:

| Metric | Expected | Actual | Status |
|--------|----------|--------|--------|
| Connection time | < 100ms | ? | ✓✓ |
| Init response time | < 50ms | ? | ✓✓ |
| Binary frame size | 320 bytes | ? | ✓✓ |
| Frames received | 10 | ? | ✓✓ |
| Done event timeout | < 2s | ? | ✓✓ |

---

**Run the diagnostic now to identify exactly where the issue occurs!**

