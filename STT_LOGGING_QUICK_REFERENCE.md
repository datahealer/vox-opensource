# STT Debug Logging - Quick Reference

## What Was Added

### ✅ **faster_whisper_service.py** Enhancements

| Method | Logging Added |
|--------|---------------|
| `__init__` | Model initialization, device, sample rates |
| `decode_pcm_base64()` | Base64 decode stats, audio min/max values |
| `transcribe_chunk()` | Audio sufficiency check, segment details, confidence scores |
| `transcribe_stream()` | Chunk processing, buffer management |
| `process_remaining()` | Final audio processing |
| `reset()` | Session state reset |

**Key Metrics Logged:**
- Audio sample counts (total, processed, remaining)
- Audio duration in seconds (samples / 16000)
- Min/max audio values (clipping detection)
- Segment count and text content
- Confidence scores
- State transitions

---

### ✅ **stt_router.py** Enhancements

| Phase | Logging Added |
|-------|---------------|
| Connection | Session ID, WebSocket acceptance |
| Initialization | Init message received, init_ack sent |
| Binary Frames | Frame count, byte count, buffer status |
| JSON Audio Chunks | Decode verification, buffer updates |
| Transcription | Start/stop markers, result yield points |
| Buffer Management | Processed samples removed, remaining samples |
| Stream End | Final processing, done event |
| Disconnection | Summary statistics |

**Key Metrics Logged:**
- Total message count
- Binary frame count
- JSON chunk count
- Total audio samples (in seconds)
- Session ID throughout

---

## Log Output Examples

### 🟢 Healthy Transcription
```
[transcribe_chunk #1] Audio sufficient, starting transcription...
[transcribe_chunk #1] Segment 1: text='hello'
[transcribe_chunk #1] Transcription result: 'hello' (5 chars, 1 segment)
[audio_chunk #1] Transcript #1: 'hello'
[audio_chunk #1] Sent transcript #1 to client
```

### 🔴 Silent/No Speech
```
[transcribe_chunk #1] Audio sufficient, starting transcription...
[transcribe_chunk #1] Transcription result: '' (0 chars, 0 segments)
[transcribe_chunk #1] No text detected in segments
```

### 🟡 Buffer Too Small
```
[transcribe_chunk #1] SKIP - insufficient audio: 1200 < 16000 (min_samples)
```

### 🔴 Audio Clipping
```
[decode_pcm_base64] min=-0.998, max=0.999  ← Too close to extremes!
```

---

## Commands to View Logs

### Real-time monitoring
```bash
# Terminal 1: Start server
uvicorn app:app --reload

# Terminal 2: Monitor logs
tail -f logs/vox.log.* | grep -E "(whisper_stt|stt_router)"
```

### Filter specific patterns
```bash
# Only whisper service logs
grep "whisper_stt" logs/vox.log.*

# Only STT router logs
grep "stt_router" logs/vox.log.*

# Transcription results only
grep "RETURNING\|Transcript #" logs/vox.log.*

# Errors and warnings
grep -E "ERROR|WARNING" logs/vox.log.*

# Connection lifecycle
grep "CONNECTED\|DISCONNECTED" logs/vox.log.*

# Specific chunk details
grep "\[audio_chunk" logs/vox.log.*
```

---

## Interpreting Sample Counts

```
Buffer = 32000 samples @ 16kHz
       = 32000 / 16000 = 2 seconds of audio

Chunk Size = 32000 samples
           = 2 seconds (set by CHUNK_MS=2000)

Min Samples = 16000 samples
            = 1 second (set by MIN_AUDIO_LENGTH=1.0)

Expected Transcription Time:
- GPU: 100-500ms per 2-second chunk
- CPU: 500-2000ms per 2-second chunk
```

---

## Checking Audio Quality

From this log line:
```
[decode_pcm_base64] Converted to float32: 1440 samples, min=-0.005432, max=0.001923
```

**Good Range:** `-0.5 < min/max < 0.5` (plenty of headroom)
```
✅ min=-0.005432, max=0.001923  (very quiet, but not silent)
✅ min=-0.250000, max=0.245000  (normal speech)
✅ min=-0.950000, max=0.920000  (loud speech)
```

**Problem Range:** Close to ±1.0 (clipping/distortion)
```
❌ min=-0.998, max=0.999         (severely clipped!)
❌ min=-0.100, max=0.098         (very quiet - might be silence)
```

---

## Buffer Growth Pattern

Healthy pattern:
```
Buffer: 160 → 320 → 480 → ... → 16000 → 32000 [TRANSCRIBE] → 0 → 160 → ...
         ↑ accumulating samples until min required ↑ processes ↑ empties ↑ starts over
```

Problem pattern (stuck buffer):
```
Buffer: 160 → 320 → 480 → 640 → 800 → ... → grows infinitely
         ↑ accumulates but never processes = transcription not triggered
```

---

## Performance Expectations

### Latency per 2-second chunk:
| Setup | Latency |
|-------|---------|
| GPU (CUDA) | 100-300ms |
| GPU (CPU fallback) | 1-3 seconds |
| CPU only | 2-5 seconds |

### Total time for full call:
```
Call duration: 30 seconds
Chunk size: 2 seconds each
Number of chunks: 30 / 2 = 15 chunks
Processing time: 15 × 200ms = 3 seconds
Total time: 30s (call) + 3s (processing) ≈ 33 seconds
```

---

## Troubleshooting Checklist

When logs show no transcriptions:

- [ ] Check for "Audio sufficient, starting transcription..."
  - If missing → buffer never reaches min_samples

- [ ] Check for "Transcription result:" with empty text
  - If yes → Whisper detected no speech

- [ ] Check audio min/max values
  - If near ±1.0 → audio clipping
  - If near 0 → very quiet or silence

- [ ] Check Whisper model loading
  - Look for "Whisper model initialized" at startup
  - Check for CUDA/device errors

- [ ] Check buffer management
  - Count audio_chunk messages
  - Verify buffer size increases
  - Verify buffer decreases after transcription

- [ ] Check model response time
  - Measure time between "starting transcription..." and next log
  - If > 10s → model hung or CUDA issue

---

## Files Modified

1. **stt_services/faster_whisper_service.py**
   - Added logger initialization
   - Enhanced all major methods with detailed logging
   - Added transcription counter and state tracking

2. **routes/stt_router.py**
   - Added detailed message flow tracking
   - Added session lifecycle logging (CONNECTED/DISCONNECTED)
   - Added statistics collection and summary

3. **DEBUG_LOGGING_GUIDE.md** (new)
   - Complete logging reference
   - Sample flows
   - Issue diagnosis guide

---

## Next Test Steps

1. **Start the server** with enhanced logging:
   ```bash
   uvicorn app:app --reload
   ```

2. **Make a test call** with speech:
   ```bash
   python test_stt_ws.py
   ```

3. **Monitor logs** in another terminal:
   ```bash
   tail -f logs/vox.log.* | grep -E "(whisper_stt|stt_router)"
   ```

4. **Analyze output** using this guide to identify:
   - Audio reception status
   - Buffer accumulation
   - Transcription completion
   - Error points

5. **Share logs** if issues persist - the detailed logging will show exactly where the problem occurs!
