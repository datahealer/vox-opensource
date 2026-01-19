# STT Debug Logging - Visual Flow Guide

## Complete Audio Pipeline with Logging Points

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         AUDIO RECEPTION LAYER                           │
└─────────────────────────────────────────────────────────────────────────┘

    ↓ Audio from Client

┌─────────────────────────────────────────────────────────────────────────┐
│ stt_router.py - WebSocket Connection                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  [WS Accept] ──→ LOG: "═══════════════════════════════════"             │
│                      "STT WS CONNECTED: session_id=..."                 │
│                      "═══════════════════════════════════"              │
│                                                                          │
│  [Receive Message] ──→ LOG: "[Message #N] Keys: [...]"                 │
│         ↓                                                                │
│      ┌──┴──────────────────────────────────────────────────┐           │
│      │                                                      │           │
│  BINARY FRAME              JSON MESSAGE                     │           │
│      │                          │                           │           │
│      ↓                          ↓                           │           │
│  LOG: "[Binary Frame #N]    LOG: "[JSON Message #N]"      │           │
│        Received: X bytes"        type=..., event=..."      │           │
│                                  │                         │           │
│  [Convert PCM16                  ├──→ event="init"         │           │
│   to float32]                    │    LOG: "[Init] ..."    │           │
│      ↓                           │                         │           │
│  LOG: "Audio buffer now:         ├──→ event="audio_chunk"  │           │
│        N samples (Xs)"           │    LOG: "[audio_chunk]"  │           │
│                                  │                         │           │
│                          [Decode base64]                    │           │
│                                  ↓                          │           │
│                          LOG: "[decode_pcm_base64]         │           │
│                                base64: X chars            │           │
│                                → Y bytes                  │           │
│                                → Z samples                │           │
│                                min=X, max=Y"              │           │
│                                  │                         │           │
│                          [Append to buffer]               │           │
│                                  ↓                         │           │
│                          LOG: "Audio buffer after:        │           │
│                                N samples (Xs)"             │           │
│                                  │                         │           │
│                                  └──────────────┬──────────┘           │
│                                                 │                       │
└─────────────────────────────────────────────────┼───────────────────────┘
                                                  ↓

┌─────────────────────────────────────────────────────────────────────────┐
│                      TRANSCRIPTION PROCESSING LAYER                     │
└─────────────────────────────────────────────────────────────────────────┘

    [Buffer Size Check]
           ↓
    [Is buffer ≥ 2 seconds?]
           ↓
       ┌───┴───┐
       │       │
      NO      YES
       │       │
       │       ↓
       │   LOG: "[transcribe_chunk #N] START"
       │        "audio_chunk: N samples"
       │        "min=X, max=Y"
       │        ↓
       │   LOG: "[transcribe_chunk #N] Audio sufficient"
       │        "starting transcription..."
       │        ↓
       │   [Call Whisper Model]
       │        ↓
       │   LOG: "[transcribe_chunk #N] Segment K:"
       │        "text='...'"
       │        (for each segment)
       │        ↓
       │   LOG: "[transcribe_chunk #N] Transcription result:"
       │        "'...' (N chars, K segments)"
       │        ↓
       │   [Check for new content]
       │        ↓
       │   ┌────┴─────────────┐
       │   │                  │
       │  EMPTY           CONTENT FOUND
       │   │                  │
       │   ↓                  ↓
       │  LOG: "No text    LOG: "[transcribe_chunk #N]"
       │       detected"       "RETURNING: {...}"
       │   │                  │
       └───┴──────────────────┴─ [Yield Result]
                   ↓
           stt_router.py:

           LOG: "[audio_chunk #N] Transcript #M: '...'"
           LOG: "[audio_chunk #N] Sent transcript to client"

           [Remove processed samples]
           ↓
           LOG: "[audio_chunk #N] Removing N samples"
           LOG: "[audio_chunk #N] Buffer after removal: M samples"

```

---

## State Tracking Diagram

```
Session State Machine with Logging
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌─────────────────────────────────┐
│  INITIALIZATION STATE           │
├─────────────────────────────────┤
│ LOG: "═══════════════════════"   │
│      "STT WS CONNECTED"          │
│      "═══════════════════════"   │
│                                  │
│ audio_buffer = empty             │
│ message_count = 0                │
│ transcribe_count = 0             │
│                                  │
│ Wait for init event              │
└──────────────┬──────────────────┘
               │ init event received
               ↓
┌─────────────────────────────────┐
│  READY STATE                    │
├─────────────────────────────────┤
│ LOG: "[Init] init_ack sent"      │
│                                  │
│ Ready to accept audio            │
│ transcribe_count = 0             │
│ full_transcript = ""             │
└──────────────┬──────────────────┘
               │ audio frames/chunks arrive
               ↓
┌─────────────────────────────────┐
│  BUFFERING STATE                │
├─────────────────────────────────┤
│ LOG: "[audio_chunk #N]"          │
│      "Audio buffer now: ... (Xs)"│
│                                  │
│ audio_buffer accumulates         │
│ message_count increases          │
│ Check if ready to transcribe     │
└──────────────┬──────────────────┘
               │ buffer ≥ min_samples?
               ↓
┌─────────────────────────────────┐
│  TRANSCRIPTION STATE            │
├─────────────────────────────────┤
│ LOG: "[transcribe_chunk #N]"     │
│      "START"                     │
│      "Audio sufficient..."       │
│      "Segment 1: text=..."       │
│      "RETURNING: {...}"          │
│                                  │
│ Model.transcribe() called        │
│ Result yielded to router         │
│ transcribe_count increases       │
│ full_transcript updated          │
└──────────────┬──────────────────┘
               │ result sent to client
               ↓
┌─────────────────────────────────┐
│  BUFFER CLEANUP STATE           │
├─────────────────────────────────┤
│ LOG: "[audio_chunk #N]"          │
│      "Removing N samples"        │
│      "Buffer after: M samples"   │
│                                  │
│ Processed samples removed        │
│ audio_buffer decreases           │
│ Return to BUFFERING if more data │
└──────────────┬──────────────────┘
               │ end_stream event?
               ↓
┌─────────────────────────────────┐
│  FINALIZATION STATE             │
├─────────────────────────────────┤
│ LOG: "[end_stream]"              │
│      "Processing remaining..."   │
│      "Done event sent"           │
│                                  │
│ Last audio chunk processed       │
│ Done signal sent to client       │
│ Close WebSocket                  │
└──────────────┬──────────────────┘
               │
               ↓
┌─────────────────────────────────┐
│  DISCONNECTED STATE             │
├─────────────────────────────────┤
│ LOG: "═══════════════════════"   │
│      "STT WS DISCONNECTED"       │
│      "Messages: N"               │
│      "Binary frames: N"          │
│      "JSON chunks: N"            │
│      "Total samples: N (Xs)"     │
│      "═══════════════════════"   │
│                                  │
│ Session complete                 │
│ Resources cleaned up             │
└─────────────────────────────────┘
```

---

## Buffer State Visualization

```
Healthy Buffer Flow:
════════════════════

Time 0:   Buffer: [                    ] (0 samples)
          LOG: "Audio buffer now: 0 samples"

Time 1:   Buffer: [###                 ] (160 samples)
          LOG: "[Binary Frame #1] Audio buffer now: 160 samples"

Time 2:   Buffer: [#########           ] (480 samples)
          LOG: "[audio_chunk #1] Audio buffer after: 480 samples"

...accumulation continues...

Time 10:  Buffer: [#################] (16000 samples / 1.00s)
          LOG: "[audio_chunk #8] Audio buffer after: 16000 samples"

          Ready to transcribe ✓

Time 11:  Buffer: [##################################] (32000 samples / 2.00s)
          LOG: "[audio_chunk #16] Audio buffer after: 32000 samples (2.00s)"

          Transcription triggered:
          LOG: "[transcribe_chunk #1] Audio sufficient, starting..."
          LOG: "[transcribe_chunk #1] Segment 1: text='hello'"
          LOG: "[transcribe_chunk #1] RETURNING: {...}"
          LOG: "[audio_chunk #16] Transcript #1: 'hello'"

Time 12:  Buffer: [                    ] (0 samples)
          LOG: "[audio_chunk #16] Removing 32000 samples"
          LOG: "[audio_chunk #16] Buffer after removal: 0 samples"

          Back to accumulation...


Problematic Buffer Flow:
═══════════════════════

Time 0:   Buffer: [                    ] (0 samples)

Time 10:  Buffer: [#########           ] (5000 samples)
          LOG: "Audio buffer now: 5000 samples"

Time 20:  Buffer: [##################] (10000 samples)
          LOG: "Audio buffer now: 10000 samples"

Time 30:  Buffer: [##########################] (15000 samples)
          LOG: "Audio buffer now: 15000 samples"

          ⚠️ Problem: Buffer accumulates but never processes!

          LOG: "[transcribe_chunk #1] SKIP - insufficient audio"
          LOG: "15000 < 16000 (min_samples)"

          OR

          LOG: "[transcribe_chunk #1] No text detected in segments"

          → Buffer keeps growing, no results yielded
          → Client timeout after 5 seconds
```

---

## Message Processing Flow Diagram

```
WebSocket Message Processing
═════════════════════════════

┌──────────────────────────────┐
│  Receive WebSocket Message   │
│  message_count++             │
│  LOG: "[Message #N]"         │
└──────────────┬───────────────┘
               │
        ┌──────┴──────┐
        │             │
    BINARY         TEXT
    Frame          JSON
        │             │
        ↓             ↓
┌──────────────────────────────┐
│ Log binary frame            │ Extract JSON
│ Convert PCM16→float32        │ LOG: "[JSON Message]"
│ Append to buffer             │        type=..., event=...
│ LOG: "Received: N bytes"     │        │
│ LOG: "Buffer now: M samples" │        ├─→ event=="init"
│                              │        │   LOG: "init received"
│                              │        │   Send init_ack
│                              │        │
│                              │        ├─→ event=="audio_chunk"
│                              │        │   Decode base64
│                              │        │   Append to buffer
│                              │        │   Start transcription
│                              │        │   Yield results
│                              │        │
│                              │        ├─→ event=="end_stream"
│                              │        │   Process remaining
│                              │        │   Send done
│                              │        │
│                              │        └─→ event=="cancel"
│                              │            Send cancel_ack
│                              │            Break loop
└──────────────┬───────────────┘
               │
        ┌──────┴──────┐
        │             │
    Continue      Close
    Loop          Connection
        │             │
        ↓             ↓
 Wait for        LOG: "DISCONNECTED
 next            Summary"
 message         Return
```

---

## Logging Coverage Map

```
File: stt_services/faster_whisper_service.py
═════════════════════════════════════════════

Line Range    Component            Logging Points
───────────   ───────────          ───────────────
1-10          Imports              ✓ Logger setup
              Constants            ✓ Config values logged

11-23         __init__             ✓ Model init
              Configuration        ✓ Device, sizes

24-41         decode_pcm_base64    ✓ Input/output sizes
                                   ✓ Min/max values
                                   ✓ Error handling

42-110        transcribe_chunk     ✓ Audio check
                                   ✓ Segment details
                                   ✓ Result text
                                   ✓ Confidence
                                   ✓ Error context

111-141       transcribe_stream    ✓ Buffer status
                                   ✓ Chunk tracking
                                   ✓ Result yields
                                   ✓ Completion

142-154       process_remaining    ✓ Final processing
                                   ✓ Result delivery

155-160       reset()              ✓ State reset


File: routes/stt_router.py
═════════════════════════

Line Range    Component            Logging Points
───────────   ───────────          ───────────────
1-30          Initialization       ✓ Connection banner
              Session setup        ✓ Counters zeroed

31-47         Message receiving    ✓ Message count
                                   ✓ Message keys
                                   ✓ Error handling

48-62         Binary frames        ✓ Frame number
                                   ✓ Byte count
                                   ✓ Buffer status

63-110        JSON audio chunks    ✓ Chunk number
                                   ✓ Decode logging
                                   ✓ Transcription start
                                   ✓ Result transmission
                                   ✓ Buffer removal

111-140       end_stream event     ✓ Signal received
                                   ✓ Final processing
                                   ✓ Done transmission

141-150       cancel event         ✓ Cancel received
                                   ✓ Ack sent

151-175       Disconnection        ✓ Disconnect banner
                                   ✓ Statistics
                                   ✓ Exception handling
```

---

## Log Line Format Reference

```
All log lines follow this pattern:

[TIMESTAMP] [LEVEL] [LOGGER_NAME] MESSAGE

Examples:

[DEBUG] [whisper_stt] [transcribe_chunk #1] START - audio_chunk: 16000 samples
[INFO]  [whisper_stt] [transcribe_chunk #1] Transcription result: 'hello' (5 chars)
[ERROR] [whisper_stt] [decode_pcm_base64] Error decoding audio: Invalid base64

[DEBUG] [stt_router] [Message #42] Keys: ['text']
[INFO]  [stt_router] [audio_chunk #5] Audio buffer after append: 32000 samples (2.00s)
[INFO]  [stt_router] [end_stream] Done event sent
[INFO]  [stt_router] ═══════════════════════════════════════════════════════════
```

---

## Error Backtrace Format

When an error occurs, full context is logged:

```
[ERROR] [whisper_stt] [transcribe_chunk #3] ERROR: ValueError: Invalid audio format
Traceback (most recent call last):
  File "stt_services/faster_whisper_service.py", line XX, in transcribe_chunk
    result = self.model.transcribe(audio_chunk, ...)
  File "faster_whisper.py", line YY, in transcribe
    ...
ValueError: Invalid audio format

[Context] Chunk #3, Audio: 16000 samples, min=-0.5, max=0.4
```

---

## Performance Metric Extraction

From logs, calculate:

```
Transcription Latency:
  Start: grep "starting transcription..." log
  End:   grep "RETURNING:" log
  Time:  End_timestamp - Start_timestamp

Buffer Accumulation:
  Per frame = buffer_size / frame_count
  Rate = samples_per_second

Processing Efficiency:
  Total audio = grep "Total samples:" disconnected_log
  Processing time = total_time - call_duration
  Efficiency = call_duration / total_time

Model Performance:
  Samples per transcription = average chunks × chunk_size
  Time per sample = latency / samples
```

---

