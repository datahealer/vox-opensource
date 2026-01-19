# STT Enhanced Debug Logging - Summary

## What Was Done ✅

I've added comprehensive debug logging to your Faster Whisper STT service to help diagnose why user voice transcription isn't working despite the main server sending audio.

### Files Modified

**1. stt_services/faster_whisper_service.py**
- Added detailed logging at every step of the transcription pipeline
- Tracks audio quality (min/max values to detect clipping)
- Shows exactly when/why audio is skipped
- Reports transcription results with segment details
- Logs confidence scores

**2. routes/stt_router.py**
- Tracks incoming messages by type and count
- Monitors buffer accumulation and consumption
- Shows when transcription is triggered
- Logs session lifecycle (connected → processing → disconnected)
- Provides summary statistics on disconnect

### Key Logging Features

✅ **Audio Reception Tracking**
- Logs binary frame arrival with byte counts
- Logs JSON chunk decoding with base64 verification
- Shows audio buffer growth in samples and seconds

✅ **Audio Quality Detection**
- Min/max values to detect clipping (audio distortion)
- Detection of very quiet audio (might be silence)
- Validation that audio is in proper range

✅ **Transcription Pipeline**
- Shows when audio buffer is too small
- Logs each segment detected by Whisper
- Shows final transcription result
- Tracks incremental vs new content
- Reports confidence scores

✅ **Buffer Management**
- Tracks buffer accumulation
- Shows how many samples are processed
- Monitors buffer cleanup
- Detects buffer leaks (constantly growing)

✅ **Session Statistics**
- Connection/disconnection banners
- Total message count by type
- Total audio samples in seconds
- Useful for post-call analysis

---

## How to Use the Logs

### Start the Server
```bash
cd /home/vansh/vox-opensource-clone/vox-opensource-alok
uvicorn app:app --reload 2>&1 | tee run.log
```

### Make a Test Call
```bash
python test_stt_ws.py
```

### Monitor Logs in Real-Time
```bash
tail -f logs/vox.log.* | grep -E "(whisper_stt|stt_router)"
```

### Check for Specific Issues

**Check if audio is received:**
```bash
grep "Binary Frame\|audio_chunk" logs/vox.log.*
```

**Check if transcription is triggered:**
```bash
grep "Audio sufficient\|SKIP\|No text detected" logs/vox.log.*
```

**Check audio quality:**
```bash
grep "min=.*max=" logs/vox.log.*
# Values near ±1.0 = clipping
# Values near 0.0 = very quiet
```

**Check for errors:**
```bash
grep "ERROR\|Exception" logs/vox.log.*
```

**See session summary:**
```bash
grep "═══\|CONNECTED\|DISCONNECTED\|Total samples" logs/vox.log.*
```

---

## Expected Log Output (Healthy)

```
═══════════════════════════════════════════════════════════
STT WS CONNECTED: session_id=6e386589-d3d2-4f16-a978-0bfdd55a81ea
═══════════════════════════════════════════════════════════
[INFO] [Init] STT init received
[INFO] [audio_chunk #1] Audio buffer after append: 16000 samples (1.00s)
[INFO] [transcribe_chunk #1] Audio sufficient, starting transcription...
[INFO] [transcribe_chunk #1] Segment 1: text='Hello how are you'
[INFO] [transcribe_chunk #1] RETURNING: {'text': 'Hello how are you', 'is_final': True, 'confidence': 0.95}
[INFO] [audio_chunk #1] Transcript #1: 'Hello how are you'
[end_stream] Done event sent
═══════════════════════════════════════════════════════════
STT WS DISCONNECTED: session_id=6e386589-d3d2-4f16-a978-0bfdd55a81ea
  - Messages: 42
  - Binary frames: 6
  - JSON audio_chunks: 36
  - Total samples: 86400 (5.40s)
═══════════════════════════════════════════════════════════
```

---

## Problem Diagnosis Guide

### Issue: "No transcriptions returned"

1. Check if audio is received:
   ```bash
   grep "audio_chunk\|Binary Frame" logs/vox.log.*
   ```
   - If NO matches → Audio not reaching STT server

2. Check if transcription is triggered:
   ```bash
   grep "Audio sufficient\|SKIP" logs/vox.log.*
   ```
   - If seeing "SKIP - insufficient audio" → Buffer never reaches 1 second
   - If seeing "Audio sufficient" → Check next step

3. Check if Whisper returns results:
   ```bash
   grep "Transcription result:\|No text detected" logs/vox.log.*
   ```
   - If "No text detected" → Whisper heard silence
   - If "Transcription result: ''" → Empty transcription
   - If "RETURNING:" → Check if sent to client

4. Check if results sent to client:
   ```bash
   grep "Sent transcript\|Transcript #" logs/vox.log.*
   ```
   - If missing → Error sending to client (check logs for errors)

---

### Issue: "Audio quality problems"

Check audio levels:
```bash
grep "min=.*max=" logs/vox.log.* | head -5
```

Interpretation:
- `min=-0.5, max=0.45` ✅ Normal speech
- `min=-0.95, max=0.92` ✅ Loud speech
- `min=-0.001, max=0.001` ⚠️ Very quiet - might be silence
- `min=-0.998, max=0.999` ❌ Clipped/distorted audio

---

### Issue: "Transcription very slow"

Find transcription time:
```bash
# Find start
grep "starting transcription\.\.\." logs/vox.log.* | head -1

# Find end
grep "RETURNING:" logs/vox.log.* | head -1

# Calculate time difference from timestamps
```

Expected times:
- GPU: 100-500ms per 2-second chunk ✅
- CPU: 1-3 seconds per 2-second chunk ⚠️
- Very slow (> 10s): Model hung or CUDA memory issue ❌

---

### Issue: "Buffer growing indefinitely"

Monitor buffer size:
```bash
grep "Audio buffer" logs/vox.log.* | tail -20
```

Healthy pattern:
```
1.0s → 1.5s → 2.0s [TRANSCRIBE] → 0s → 0.5s → 1.0s
```

Problem pattern:
```
1.0s → 2.0s → 3.0s → 4.0s → 5.0s [TIMEOUT]
```

If buffer grows without transcribing → Check why "Audio sufficient" not triggered

---

## Documentation Files Created

| File | Purpose |
|------|---------|
| [DEBUG_LOGGING_GUIDE.md](DEBUG_LOGGING_GUIDE.md) | Complete logging reference |
| [STT_LOGGING_QUICK_REFERENCE.md](STT_LOGGING_QUICK_REFERENCE.md) | Quick lookup guide |
| [LOGGING_ENHANCEMENT_SUMMARY.md](LOGGING_ENHANCEMENT_SUMMARY.md) | Detailed changes |
| [LOGGING_VISUAL_GUIDE.md](LOGGING_VISUAL_GUIDE.md) | Visual flow diagrams |
| [IMPLEMENTATION_CHECKLIST.md](IMPLEMENTATION_CHECKLIST.md) | Implementation details |

---

## Next Steps

1. **Run the server** with the enhanced logging
2. **Make test calls** with speech
3. **Review logs** using the guides to identify where the issue occurs
4. **Share the logs** if you need further help - the detailed logging will show exactly what's happening

The logging now provides complete visibility into:
- Whether audio is being received ✓
- Whether transcription is triggered ✓
- What Whisper detects ✓
- Whether results are returned ✓
- Audio quality issues ✓
- Performance metrics ✓

---

## Quick Commands Cheat Sheet

```bash
# Monitor in real-time
tail -f logs/vox.log.* | grep -E "(whisper_stt|stt_router)"

# Transcription results
grep "RETURNING\|Transcript #" logs/vox.log.*

# Audio statistics
grep "min=.*max=\|Audio buffer" logs/vox.log.*

# Connection lifecycle
grep "CONNECTED\|DISCONNECTED" logs/vox.log.*

# Errors
grep "ERROR\|Exception" logs/vox.log.*

# Specific chunk tracking
grep "\[audio_chunk #5\]" logs/vox.log.*

# Session summary
grep "═══" logs/vox.log.*

# All DEBUG messages
grep "\[DEBUG\]" logs/vox.log.*

# Filter by time range
grep "2026-01-12 12:4[7-8]:" logs/vox.log.*
```

---

## Testing Checklist

- [ ] Server starts without errors
- [ ] Logger initialized with "whisper_stt" name
- [ ] First test call shows "STT WS CONNECTED"
- [ ] Audio frames/chunks received (verify message count > 0)
- [ ] Buffer accumulates (shows increasing sample counts)
- [ ] Transcription triggered (see "Audio sufficient...")
- [ ] Results returned (see "RETURNING:" or "Transcript #")
- [ ] Session ends cleanly (see "STT WS DISCONNECTED")
- [ ] Statistics show reasonable call duration

---

## Support Information

If transcription still doesn't work after checking logs:

1. **Share the logs** from a failed call
2. **Include the following information:**
   - Total samples received
   - Audio quality (min/max values)
   - Whether "Audio sufficient" was logged
   - Whether "RETURNING:" was logged
   - Any error messages

The detailed logging will now show exactly where in the pipeline the issue occurs!

---

**Implementation Status: ✅ COMPLETE**

All enhancements are in place and ready to diagnose STT issues.

