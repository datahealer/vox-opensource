# STT Debug Logging Enhancement Summary

## Overview
Added comprehensive debug logging to the Faster Whisper STT service to trace and diagnose transcription issues. The logging covers the complete pipeline from audio reception through transcription to completion.

---

## Files Enhanced

### 1. **stt_services/faster_whisper_service.py**

**Added:**
- Logger initialization: `logger = setup_logger("whisper_stt")`
- Transcription counter: `self.transcribe_count`
- Detailed logging in all major methods

**Methods Enhanced:**

#### `__init__()` - Model Initialization
```python
logger.info(f"Initializing WhisperSTTService: model_size={model_size}, device={device}")
logger.info(f"Whisper model initialized: chunk_samples={self.chunk_samples}, min_samples={self.min_samples}")
logger.debug(f"SAMPLE_RATE={SAMPLE_RATE}, CHUNK_MS={CHUNK_MS}, MIN_AUDIO_LENGTH={MIN_AUDIO_LENGTH}")
```

#### `decode_pcm_base64()` - Audio Decoding
- Log base64 decode results (chars → bytes)
- Log PCM16 to float32 conversion
- Log audio statistics (min/max values for clipping detection)
- Log any decode errors

#### `transcribe_chunk()` - Transcription
- Log chunk start with audio statistics
- Log audio sufficiency check
- Log individual segments detected
- Log final transcription result with character count
- Log incremental vs new transcription
- Log confidence scores
- Log any errors with full traceback

#### `transcribe_stream()` - Buffer Processing
- Log stream start with total samples
- Log each chunk processed with counter
- Log results yielded
- Log buffer state before/after each chunk
- Log stream completion with statistics

#### `process_remaining()` - Final Processing
- Log remaining audio size
- Log sufficiency check
- Log final results
- Log buffer management

#### `reset()` - Session Reset
- Log previous transcript being cleared
- Log counter reset

---

### 2. **routes/stt_router.py**

**Added:**
- Comprehensive message tracking with counters
- Session lifecycle logging (CONNECTED/DISCONNECTED)
- Statistics collection and summary on disconnect

**Tracking:**
- `message_count` - Total WebSocket messages
- `audio_frame_count` - Binary audio frames
- `audio_chunk_count` - JSON audio chunks
- `total_audio_samples` - Cumulative audio samples

**Enhanced Sections:**

#### Connection Phase
```
═══════════════════════════════════════════════════════════
STT WS CONNECTED: session_id={session_id}
═══════════════════════════════════════════════════════════
```

#### Message Reception
- Log message type and event
- Log byte/sample counts
- Log buffer sizes after each message

#### Transcription
- Log when transcription starts
- Log each transcript received
- Log transmission to client

#### Stream End
```
[end_stream] Processing remaining {len} samples ({duration}s)
[end_stream] Final result: '{text}'
[end_stream] Done event sent
```

#### Disconnection Summary
```
═══════════════════════════════════════════════════════════
STT WS DISCONNECTED: session_id={session_id}
  - Messages: {message_count}
  - Binary frames: {audio_frame_count}
  - JSON audio_chunks: {audio_chunk_count}
  - Total samples: {total_audio_samples} ({duration}s)
═══════════════════════════════════════════════════════════
```

---

## Key Logging Features

### 1. **Audio Quality Monitoring**
```python
min={float32_audio.min():.6f}, max={float32_audio.max():.6f}
```
- Detects clipping (values near ±1.0)
- Shows if audio is too quiet (values near 0.0)
- Helps validate audio source quality

### 2. **Buffer State Tracking**
```python
logger.debug(f"[audio_chunk #{audio_chunk_count}] Audio buffer now: "
            f"{len(audio_buffer)} samples ({len(audio_buffer) / SAMPLE_RATE:.2f}s)")
```
- Shows buffer accumulation
- Displays duration in seconds for easy interpretation
- Tracks buffer consumption after transcription

### 3. **Transcription Pipeline**
```python
logger.debug(f"[transcribe_chunk #{self.transcribe_count}] START - audio_chunk: ...")
logger.debug(f"[transcribe_chunk #{self.transcribe_count}] Segment {segment_count}: text=...")
logger.info(f"[transcribe_chunk #{self.transcribe_count}] RETURNING: {result}")
```
- Numbered chunks for easy tracking
- Shows segment-by-segment results
- Clear entry/exit points

### 4. **Error Context**
```python
except Exception as e:
    logger.error(f"[transcribe_chunk #{self.transcribe_count}] ERROR: {type(e).__name__}: {e}", exc_info=True)
```
- Full exception traceback
- Numbered context
- Helps identify exact failure point

### 5. **Session Statistics**
- Total samples received
- Message types processed
- Processing rate
- Disconnection reason

---

## Log Output Examples

### ✅ Successful Call
```
═══════════════════════════════════════════════════════════
STT WS CONNECTED: session_id=6e386589-d3d2-4f16-a978-0bfdd55a81ea
═══════════════════════════════════════════════════════════
[INFO] [Init] STT init received
[audio_chunk #1] Audio buffer after append: 16000 samples (1.00s)
[transcribe_chunk #1] Audio sufficient, starting transcription...
[transcribe_chunk #1] Segment 1: text='Hello, how can I help you?'
[transcribe_chunk #1] RETURNING: {'text': 'Hello, how can I help you?', ...}
[audio_chunk #1] Transcript #1: 'Hello, how can I help you?'
[end_stream] Done event sent
═══════════════════════════════════════════════════════════
STT WS DISCONNECTED: session_id=6e386589-d3d2-4f16-a978-0bfdd55a81ea
  - Total samples: 96000 (6.00s)
═══════════════════════════════════════════════════════════
```

### ❌ Silent/Noise Issues
```
[transcribe_chunk #1] Audio sufficient, starting transcription...
[transcribe_chunk #1] Transcription result: '' (0 chars, 0 segments)
[transcribe_chunk #1] No text detected in segments
```

### ❌ Clipping
```
[decode_pcm_base64] min=-0.998, max=0.999
```

### ❌ Very Quiet
```
[decode_pcm_base64] min=-0.001, max=0.001
```

---

## Diagnostic Capabilities

The enhanced logging allows you to diagnose:

| Issue | Detection |
|-------|-----------|
| No audio received | Count binary frames and audio_chunk messages |
| Audio decoding failures | Check decode_pcm_base64 error logs |
| Buffer not accumulating | Monitor buffer size growth |
| Transcription not triggered | Check for "Audio sufficient" message |
| Model hanging | Measure time between "starting transcription" logs |
| No results from Whisper | Check for empty segment results |
| Audio quality issues | Inspect min/max audio values |
| Silent audio | Check if min/max near 0.0 |
| Clipped audio | Check if min/max near ±1.0 |
| Buffer leak | Monitor remaining samples increase |
| Slow processing | Track transcription time per chunk |

---

## Performance Metrics Available

From logs, calculate:

```python
# Audio duration
duration_seconds = samples / 16000

# Transcription latency (from logs)
start_time = timestamp of "starting transcription..."
end_time = timestamp of "RETURNING:"
latency = end_time - start_time

# Buffer accumulation rate
samples_per_message = buffer_size_after / message_count

# Processing efficiency
chunks_processed = grep "RETURNING" | wc -l
total_time = end - start
processing_time = total_time - audio_duration
efficiency = audio_duration / total_time
```

---

## Testing Recommendations

### Before Changes
```bash
uvicorn app:app --reload 2>&1 | tee server.log
```

### Make Test Call
```bash
python test_stt_ws.py
```

### Review Logs
```bash
# All STT logs
grep -E "(whisper_stt|stt_router)" server.log

# Transcription results only
grep "RETURNING\|Transcript #\|CONNECTED\|DISCONNECTED" server.log

# Errors only
grep "ERROR\|Exception" server.log

# Buffer state
grep "Audio buffer" server.log

# Session summary
grep "═══" server.log
```

---

## What This Enables

✅ **Complete audit trail** of audio from input to transcription output
✅ **Buffer state visibility** to diagnose accumulation issues
✅ **Transcription timing** to identify performance bottlenecks
✅ **Audio quality checks** to detect clipping or silence
✅ **Error context** with full stack traces and numbered chunks
✅ **Session statistics** for post-call analysis
✅ **Root cause analysis** of why transcriptions don't return
✅ **Performance baseline** for optimization

---

## Next Steps

1. **Run with test calls** and capture logs
2. **Look for "CONNECTED/DISCONNECTED" separators** to isolate calls
3. **Check for "RETURNING:" messages** to verify transcriptions happen
4. **Inspect audio min/max values** for quality issues
5. **Measure latencies** to identify performance problems
6. **Share logs** if issues persist - detailed logging now provides complete visibility

---

