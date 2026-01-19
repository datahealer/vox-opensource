import numpy as np
import base64
from faster_whisper import WhisperModel
from core.logger import setup_logger

logger = setup_logger("whisper_stt")

SAMPLE_RATE = 16000
CHUNK_MS = 500  # 0.5 seconds for faster response (was 2000)
MIN_AUDIO_LENGTH = 0.3  # Minimum 0.3 seconds before transcribing (was 1.0)

class WhisperSTTService:
    def __init__(self, model_size="large", device="cuda"):
        logger.info(f"Initializing WhisperSTTService: model_size={model_size}, device={device}")
        self.model = WhisperModel(model_size, device=device, compute_type="float16")
        self.chunk_samples = int(SAMPLE_RATE * CHUNK_MS / 1000)
        self.min_samples = int(SAMPLE_RATE * MIN_AUDIO_LENGTH)
        self.full_transcript = ""  # Complete transcript so far
        self.transcribe_count = 0  # Count transcriptions
        logger.info(f"Whisper model initialized: chunk_samples={self.chunk_samples}, min_samples={self.min_samples}")
        logger.debug(f"SAMPLE_RATE={SAMPLE_RATE}, CHUNK_MS={CHUNK_MS}, MIN_AUDIO_LENGTH={MIN_AUDIO_LENGTH}")

    @staticmethod
    def decode_pcm_base64(b64_audio: str) -> np.ndarray:
        """Decode base64 PCM16 audio to float32 numpy array"""
        try:
            pcm_bytes = base64.b64decode(b64_audio)
            logger.debug(f"[decode_pcm_base64] base64 input: {len(b64_audio)} chars → {len(pcm_bytes)} bytes")

            pcm16 = np.frombuffer(pcm_bytes, dtype=np.int16)
            logger.debug(f"[decode_pcm_base64] PCM16 samples: {len(pcm16)}")

            float32_audio = pcm16.astype(np.float32) / 32768.0
            logger.debug(f"[decode_pcm_base64] Converted to float32: {len(float32_audio)} samples, "
                        f"min={float32_audio.min():.6f}, max={float32_audio.max():.6f}")

            return float32_audio
        except Exception as e:
            logger.error(f"[decode_pcm_base64] Error decoding audio: {e}")
            raise

    def transcribe_chunk(self, audio_chunk: np.ndarray):
        """
        Transcribe a single audio chunk and return new text.
        Returns the new text that wasn't in the previous transcript.
        """
        self.transcribe_count += 1
        logger.debug(f"[transcribe_chunk #{self.transcribe_count}] START - audio_chunk: "
                    f"{len(audio_chunk)} samples, min={audio_chunk.min():.6f}, max={audio_chunk.max():.6f}")

        if len(audio_chunk) < self.min_samples:
            logger.debug(f"[transcribe_chunk #{self.transcribe_count}] SKIP - insufficient audio: "
                        f"{len(audio_chunk)} < {self.min_samples} (min_samples)")
            return None

        logger.debug(f"[transcribe_chunk #{self.transcribe_count}] Audio sufficient, starting transcription...")
        try:
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
            segment_count = 0
            for seg in segments:
                segment_count += 1
                logger.debug(f"[transcribe_chunk #{self.transcribe_count}] Segment {segment_count}: "
                            f"text='{seg.text}', confidence={seg.confidence if hasattr(seg, 'confidence') else 'N/A'}")
                segment_text += seg.text.strip() + " "

            segment_text = segment_text.strip()
            logger.info(f"[transcribe_chunk #{self.transcribe_count}] Transcription result: "
                       f"'{segment_text}' ({len(segment_text)} chars, {segment_count} segments)")

            if not segment_text:
                logger.debug(f"[transcribe_chunk #{self.transcribe_count}] No text detected in segments")
                return None

            # Check if this is actually new content
            if segment_text == self.full_transcript:
                logger.debug(f"[transcribe_chunk #{self.transcribe_count}] Text matches full_transcript (no new content)")
                return None

            # Find the new portion
            if self.full_transcript and segment_text.startswith(self.full_transcript):
                # Extract only the new part
                new_text = segment_text[len(self.full_transcript):].strip()
                logger.debug(f"[transcribe_chunk #{self.transcribe_count}] Incremental update: "
                            f"new_text='{new_text}' (full_transcript: '{self.full_transcript}')")
            else:
                # Completely new text (or corrected text)
                new_text = segment_text
                logger.debug(f"[transcribe_chunk #{self.transcribe_count}] New transcript: "
                            f"'{new_text}' (was: '{self.full_transcript}')")

            if new_text:
                self.full_transcript = segment_text
                confidence = getattr(info, "language_probability", 0.9)
                result = {
                    "text": new_text,
                    "is_final": True,
                    "confidence": confidence
                }
                logger.info(f"[transcribe_chunk #{self.transcribe_count}] RETURNING: {result}")
                return result
            else:
                logger.debug(f"[transcribe_chunk #{self.transcribe_count}] No new text after extraction")
                return None

        except Exception as e:
            logger.error(f"[transcribe_chunk #{self.transcribe_count}] ERROR: {type(e).__name__}: {e}", exc_info=True)
            return None

    async def transcribe_stream(self, audio_buffer: np.ndarray):
        """
        Async generator: yields new transcription segments from audio_buffer.
        Processes the buffer and yields results.
        """
        logger.debug(f"[transcribe_stream] START - buffer: {len(audio_buffer)} samples")

        # Only transcribe if we have enough audio
        if len(audio_buffer) < self.min_samples:
            logger.debug(f"[transcribe_stream] Buffer too small: {len(audio_buffer)} < {self.min_samples}")
            return

        logger.info(f"[transcribe_stream] Processing buffer with {len(audio_buffer)} samples "
                   f"({len(audio_buffer) / SAMPLE_RATE:.2f}s)")

        chunk_num = 0
        # Process available complete chunks
        while len(audio_buffer) >= self.chunk_samples:
            chunk_num += 1
            logger.debug(f"[transcribe_stream] Processing chunk #{chunk_num}: "
                        f"extracting {self.chunk_samples} samples from buffer of {len(audio_buffer)}")

            segment = audio_buffer[:self.chunk_samples]

            # Transcribe the segment
            result = self.transcribe_chunk(segment)

            if result:
                logger.info(f"[transcribe_stream] Yielding result from chunk #{chunk_num}: '{result['text']}'")
                yield result
            else:
                logger.debug(f"[transcribe_stream] No result from chunk #{chunk_num}")

            # Move buffer forward
            audio_buffer = audio_buffer[self.chunk_samples:]
            logger.debug(f"[transcribe_stream] Buffer after chunk #{chunk_num}: {len(audio_buffer)} samples remaining")

        logger.info(f"[transcribe_stream] DONE - processed {chunk_num} chunks, "
                   f"{len(audio_buffer)} samples remaining in buffer")

    def process_remaining(self, audio_buffer: np.ndarray):
        """
        Process any remaining audio at the end of stream.
        Returns the result or None.
        """
        logger.debug(f"[process_remaining] START - buffer: {len(audio_buffer)} samples "
                    f"({len(audio_buffer) / SAMPLE_RATE:.2f}s)")

        if len(audio_buffer) >= self.min_samples:
            logger.info(f"[process_remaining] Buffer sufficient, processing remaining audio")
            result = self.transcribe_chunk(audio_buffer)
            if result:
                logger.info(f"[process_remaining] Result: '{result['text']}'")
            else:
                logger.debug(f"[process_remaining] No result from remaining audio")
            return result
        else:
            logger.debug(f"[process_remaining] Buffer too small: {len(audio_buffer)} < {self.min_samples}")
            return None

    def reset(self):
        """Reset transcript state for new session"""
        logger.info(f"[reset] Resetting session state (full_transcript was: '{self.full_transcript}')")
        self.full_transcript = ""
        self.transcribe_count = 0
    async def transcribe_complete_utterance(self, audio_buffer: np.ndarray):
        """
        ✅ NEW: Transcribe a complete utterance.

        This method processes the ENTIRE audio buffer as one unit,
        which is appropriate for the new protocol where Server 1
        sends complete utterances with is_final=true marker.

        Args:
            audio_buffer: Complete utterance audio (float32, 16kHz)

        Returns:
            dict with keys: text, is_final, confidence
            or None if no speech detected
        """
        logger.info(f"[transcribe_complete] Processing complete utterance: "
                   f"{len(audio_buffer)} samples ({len(audio_buffer) / SAMPLE_RATE:.2f}s)")

        # Check minimum length
        if len(audio_buffer) < self.min_samples:
            logger.debug(f"[transcribe_complete] Audio too short: "
                        f"{len(audio_buffer)} < {self.min_samples} samples")
            return None

        try:
            # Transcribe the entire buffer
            logger.info(f"[transcribe_complete] Starting Whisper recognition...")
            segments, info = self.model.transcribe(
                audio_buffer,
                beam_size=5,
                language="en",
                condition_on_previous_text=True,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500)
            )

            # Combine all segments into single transcript
            segment_texts = []
            for segment in segments:
                text = segment.text.strip()
                if text:
                    segment_texts.append(text)
                logger.debug(f"[transcribe_complete] Segment: '{text}'")

            complete_text = " ".join(segment_texts).strip()

            if not complete_text:
                logger.debug(f"[transcribe_complete] No text detected in segments")
                return None

            # Get language confidence
            confidence = getattr(info, "language_probability", 0.9)

            result = {
                "text": complete_text,
                "is_final": True,
                "confidence": confidence
            }

            logger.info(f"[transcribe_complete] SUCCESS: '{complete_text}' "
                       f"(confidence: {confidence:.2%})")
            return result

        except Exception as e:
            logger.error(f"[transcribe_complete] ERROR: {type(e).__name__}: {e}",
                        exc_info=True)
            return None
