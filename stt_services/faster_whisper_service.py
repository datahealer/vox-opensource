import numpy as np
import base64
from faster_whisper import WhisperModel

SAMPLE_RATE = 16000
CHUNK_MS = 2000  # 2 seconds for better accuracy
MIN_AUDIO_LENGTH = 1.0  # Minimum 1 second before transcribing

class WhisperSTTService:
    def __init__(self, model_size="large", device="cuda"):
        self.model = WhisperModel(model_size, device=device, compute_type="float16")
        self.chunk_samples = int(SAMPLE_RATE * CHUNK_MS / 1000)
        self.min_samples = int(SAMPLE_RATE * MIN_AUDIO_LENGTH)
        self.full_transcript = ""  # Complete transcript so far
        
    @staticmethod
    def decode_pcm_base64(b64_audio: str) -> np.ndarray:
        """Decode base64 PCM16 audio to float32 numpy array"""
        pcm_bytes = base64.b64decode(b64_audio)
        pcm16 = np.frombuffer(pcm_bytes, dtype=np.int16)
        return pcm16.astype(np.float32) / 32768.0

    def transcribe_chunk(self, audio_chunk: np.ndarray):
        """
        Transcribe a single audio chunk and return new text.
        Returns the new text that wasn't in the previous transcript.
        """
        if len(audio_chunk) < self.min_samples:
            return None
            
        # Transcribe segment
        segments, info = self.model.transcribe(
            audio_chunk, 
            beam_size=5,
            language="en",  # Specify if known, or remove for auto-detect
            condition_on_previous_text=True,
            vad_filter=True,  # Filter silence
            vad_parameters=dict(min_silence_duration_ms=500)
        )

        # Collect all text from segments
        segment_text = ""
        for seg in segments:
            segment_text += seg.text.strip() + " "
        
        segment_text = segment_text.strip()
        
        if not segment_text:
            return None
        
        # Check if this is actually new content
        if segment_text == self.full_transcript:
            return None
            
        # Find the new portion
        if self.full_transcript and segment_text.startswith(self.full_transcript):
            # Extract only the new part
            new_text = segment_text[len(self.full_transcript):].strip()
        else:
            # Completely new text (or corrected text)
            new_text = segment_text
        
        if new_text:
            self.full_transcript = segment_text
            confidence = getattr(info, "language_probability", 0.9)
            return {
                "text": new_text,
                "is_final": True,
                "confidence": confidence
            }
        
        return None

    async def transcribe_stream(self, audio_buffer: np.ndarray):
        """
        Async generator: yields new transcription segments from audio_buffer.
        Processes the buffer and yields results.
        """
        # Only transcribe if we have enough audio
        if len(audio_buffer) < self.min_samples:
            return
            
        # Process available complete chunks
        while len(audio_buffer) >= self.chunk_samples:
            segment = audio_buffer[:self.chunk_samples]
            
            # Transcribe the segment
            result = self.transcribe_chunk(segment)
            
            if result:
                yield result
            
            # Move buffer forward
            audio_buffer = audio_buffer[self.chunk_samples:]
        
        # Note: We don't return the remaining buffer here
        # The WebSocket handler will manage the buffer

    def process_remaining(self, audio_buffer: np.ndarray):
        """
        Process any remaining audio at the end of stream.
        Returns the result or None.
        """
        if len(audio_buffer) >= self.min_samples:
            return self.transcribe_chunk(audio_buffer)
        return None

    def reset(self):
        """Reset transcript state for new session"""
        self.full_transcript = ""