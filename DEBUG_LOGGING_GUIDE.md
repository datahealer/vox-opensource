# STT (Faster Whisper) Debug Logging Guide

## Overview
Comprehensive debug logging has been added to the STT (Speech-to-Text) service to trace the entire audio transcription pipeline and identify issues with Faster Whisper model.

---

## Files Enhanced

### 1. **stt_services/faster_whisper_service.py**
- Added logger initialization: `logger = setup_logger("whisper_stt")`
- Added transcription counter and detailed state tracking

### 2. **routes/stt_router.py**
- Enhanced with detailed message flow tracking
- Added session lifecycle logging
- Added statistics on disconnect

---

## Log Trace Flow

### **Initialization Phase**
```
[INFO] Initializing WhisperSTTService: model_size=large, device=cuda
[INFO] Whisper model initialized: chunk_samples=32000, min_samples=16000
[DEBUG] SAMPLE_RATE=16000, CHUNK_MS=2000, MIN_AUDIO_LENGTH=1.0
```

**What to look for:**
- ✅ Model loads successfully with correct device (cuda/cpu)
- ✅ Chunk/minimum sample sizes match expected values
- ❌ CUDA errors or model loading failures

---

### **WebSocket Connection Phase**
```
═══════════════════════════════════════════════════════════
[INFO] STT WS CONNECTED: session_id=6e386589-d3d2-4f16-a978-0bfdd55a81ea
═══════════════════════════════════════════════════════════
```

**What to look for:**
- ✅ Session ID is properly received
- ✅ Connection accepted
- ❌ WebSocket handshake failures

---

### **Initialization Message Phase**
```
[Message #1] Keys: ['event', 'call_session_id', 'service_type']
[INFO] [Init] STT init received (session_id=6e386589-d3d2-4f16-a978-0bfdd55a81ea)
[INFO] [Init] init_ack sent
```

**What to look for:**
- ✅ Init message received with correct structure
- ✅ init_ack successfully sent back
- ❌ Missing event/call_session_id/service_type fields

---

### **Audio Reception Phase**

#### Binary Frames (from Twilio):
```
[Binary Frame #1] Received: 160 bytes
[Binary Frame #1] Audio buffer now: 160 samples (0.01s)
```

#### JSON Audio Chunks (from main server):
```
[audio_chunk #1] Received: 2880 bytes (b64)
[decode_pcm_base64] base64 input: 3840 chars → 2880 bytes
[decode_pcm_base64] PCM16 samples: 1440
[decode_pcm_base64] Converted to float32: 1440 samples, min=-0.005432, max=0.001923
[audio_chunk #1] Audio buffer after append: 1600 samples (0.10s)
```

**What to look for:**
- ✅ Base64 decode ratio correct (1.33x for base64 encoding)
- ✅ Audio samples converted to float32 with reasonable min/max values
- ✅ Buffer accumulating samples
- ❌ Negative sample counts or decode errors
- ❌ Audio values at extremes (min/max close to ±1.0) = clipping

---

### **Transcription Phase**

#### Transcription Start:
```
[audio_chunk #1] Starting transcription from buffer (1600 samples)
[transcribe_chunk #1] START - audio_chunk: 1600 samples, min=-0.005432, max=0.001923
```

#### Transcription Processing:
```
[transcribe_chunk #1] Audio sufficient, starting transcription...
[transcribe_chunk #1] Segment 1: text='hello', confidence=N/A
[transcribe_chunk #1] Segment 2: text=' how are you', confidence=N/A
[INFO] [transcribe_chunk #1] Transcription result: 'hello how are you' (18 chars, 2 segments)
```

**What to look for:**
- ✅ Transcription completes within reasonable time
- ✅ Segments detected and concatenated
- ✅ Text contains actual words (not silence)
- ❌ "SKIP - insufficient audio" = buffer too small
- ❌ Empty transcription result
- ❌ Timeout or model hanging

#### Transcription Output:
```
[INFO] [transcribe_chunk #1] RETURNING: {'text': 'hello how are you', 'is_final': True, 'confidence': 0.95}
[INFO] [audio_chunk #1] Transcript #1: 'hello how are you'
[audio_chunk #1] Sent transcript #1 to client
```

**What to look for:**
- ✅ Result contains non-empty text
- ✅ Confidence score present
- ✅ Transcript sent to client successfully
- ❌ No result returned (check why above)
- ❌ Error sending transcript

---

### **Buffer Management Phase**
```
[audio_chunk #1] Removing 32000 processed samples from buffer
[audio_chunk #1] Buffer after removal: 0 samples
```

**What to look for:**
- ✅ Processed samples removed from buffer
- ✅ Buffer decreases after processing
- ❌ Buffer grows infinitely (transcription not happening)

---

### **Stream End Phase**
```
[end_stream] Received end_stream signal
[end_stream] Processing remaining 8000 samples (0.50s)
[process_remaining] START - buffer: 8000 samples (0.50s)
[process_remaining] Buffer sufficient, processing remaining audio
[process_remaining] Result: 'goodbye'
[end_stream] Final result: 'goodbye'
[end_stream] Done event sent
```

**What to look for:**
- ✅ Remaining audio processed
- ✅ Final result captured
- ✅ Done event sent
- ❌ Buffer too small for final processing
- ❌ Error sending done event

---

### **Disconnection Phase**
```
═══════════════════════════════════════════════════════════
STT WS DISCONNECTED: session_id=6e386589-d3d2-4f16-a978-0bfdd55a81ea
  - Messages: 42
  - Binary frames: 6
  - JSON audio_chunks: 36
  - Total samples: 86400 (5.40s)
═══════════════════════════════════════════════════════════
```

**What to look for:**
- ✅ Proper disconnect summary
- ✅ Total samples match expected call duration
- ❌ Premature disconnection
- ❌ Mismatched sample count

---

## Common Issues & Diagnostics

### Issue: "SKIP - insufficient audio"
```
[transcribe_chunk #1] SKIP - insufficient audio: 1200 < 16000 (min_samples)
```
**Cause:** Buffer has < 1 second of audio (16000 samples @ 16kHz)
**Solution:** Check MIN_AUDIO_LENGTH and SAMPLE_RATE settings

---

### Issue: "No text detected in segments"
```
[transcribe_chunk #1] Transcription result: '' (0 chars, 0 segments)
[transcribe_chunk #1] No text detected in segments
```
**Cause:** Whisper detected silence/noise, no actual speech
**Solution:** Check input audio quality, VAD settings

---

### Issue: "No transcripts generated"
```
[audio_chunk #1] No transcripts generated
```
**Cause:** Buffer processing returned no results
**Solution:** Check audio content, transcribe_chunk logic

---

### Issue: Audio values at extremes
```
[decode_pcm_base64] Converted to float32: 1440 samples, min=-0.998, max=0.999
```
**Cause:** Audio is clipping (distorted)
**Solution:** Check source audio levels, reduce gain

---

### Issue: Model not responding
```
[transcribe_chunk #1] Audio sufficient, starting transcription...
[5-minute timeout - no further logs]
```
**Cause:** Whisper model hanging or CUDA memory issues
**Solution:** Check GPU memory, restart service, try CPU mode

---

## Performance Metrics to Track

From the logs, you can calculate:

```python
# From log entry:
# [audio_chunk #1] Audio buffer after append: 1600 samples (0.10s)

Audio Duration = samples / SAMPLE_RATE
                = 1600 / 16000 = 0.10 seconds

# Transcription should complete within:
- < 2 seconds for small chunks (2000ms CHUNK_MS)
- GPU latency: ~100-500ms per 2-second chunk
- CPU latency: ~500-2000ms per 2-second chunk
```

---

## Log Levels Explained

| Level | Color | When | Examples |
|-------|-------|------|----------|
| **DEBUG** | Gray | Detailed tracing | Audio sample counts, buffer operations |
| **INFO** | Blue | Major milestones | WS connected, transcript received, done |
| **WARNING** | Yellow | Potential issues | Timeouts, large gaps |
| **ERROR** | Red | Problems | Decode failures, model crashes |

---

## Enabling Maximum Verbosity

Edit [core/logger.py](core/logger.py) to set log level:

```python
# In logger.py
log_level = logging.DEBUG  # Change to DEBUG for maximum detail
```

---

## Sample Complete Call Flow

Here's a complete successful transcription with logging:

```
═══════════════════════════════════════════════════════════
STT WS CONNECTED: session_id=abc123
═══════════════════════════════════════════════════════════
[INFO] [Init] STT init received
[INFO] [Init] init_ack sent
[audio_chunk #1] Received: 2880 bytes (b64)
[decode_pcm_base64] base64 input: 3840 chars → 2880 bytes
[audio_chunk #1] Audio buffer after append: 1440 samples (0.09s)
[audio_chunk #1] Starting transcription from buffer (1440 samples)
[transcribe_chunk #1] SKIP - insufficient audio: 1440 < 16000
[audio_chunk #2] Received: 2880 bytes (b64)
[audio_chunk #2] Audio buffer after append: 2880 samples (0.18s)
... (more audio chunks)
[audio_chunk #12] Audio buffer after append: 32000 samples (2.00s)
[audio_chunk #12] Starting transcription from buffer (32000 samples)
[transcribe_chunk #1] Audio sufficient, starting transcription...
[transcribe_chunk #1] Segment 1: text='hello'
[transcribe_chunk #1] Transcription result: 'hello' (5 chars, 1 segment)
[INFO] [audio_chunk #12] Transcript #1: 'hello'
[audio_chunk #12] Sent transcript #1 to client
[end_stream] Received end_stream signal
[end_stream] Processing remaining 8000 samples (0.50s)
[process_remaining] Result: 'goodbye'
[end_stream] Final result: 'goodbye'
[end_stream] Done event sent
═══════════════════════════════════════════════════════════
STT WS DISCONNECTED: session_id=abc123
  - Total samples: 40000 (2.50s)
═══════════════════════════════════════════════════════════
```

---

## Next Steps for Debugging

1. **Run a test call** and capture the logs
2. **Look for the "START" markers** to identify where issues occur
3. **Check transcription accuracy** - compare expected vs actual text
4. **Monitor timings** - note how long transcription takes
5. **Track buffer growth** - ensure it's being consumed
6. **Verify audio quality** - check min/max values aren't clipping

