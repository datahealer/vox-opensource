import asyncio
import os
import torch
import torchaudio
from TTS.api import TTS
from TTS.tts.configs.xtts_config import XttsConfig
from TTS.tts.models.xtts import Xtts
from core.logger import setup_logger

logger = setup_logger("xtts_streaming")

SAMPLE_RATE = 24000


class XTTSStreamingService:
    """
    Streaming TTS service using XTTS v2's inference_stream() for true real-time generation.
    Unlike the batch service, this generates audio incrementally, reducing latency to first chunk.
    """

    def __init__(self, model_path=None, checkpoint_dir=None, voice_reference="voices/default.wav"):
        """
        Initialize XTTS streaming service.

        Args:
            model_path: Path to XTTS config.json (auto-downloads if None)
            checkpoint_dir: Path to model checkpoint directory (auto-downloads if None)
            voice_reference: Path to reference voice WAV file for cloning
        """
        logger.info("Initializing XTTS Streaming Service...")

        # Use auto-download if paths not specified
        if model_path is None and checkpoint_dir is None:
            logger.info("Loading XTTS v2 model (auto-download via TTS API)...")
            # Use TTS API to handle download and initialization
            # This ensures model is downloaded and properly set up
            try:
                tts_api = TTS("tts_models/multilingual/multi-dataset/xtts_v2", gpu=torch.cuda.is_available())
            except Exception as e:
                logger.error(f"Failed to initialize TTS API: {e}")
                logger.info("Attempting manual download and initialization...")
                # Fallback: try to download explicitly
                from TTS.utils.manage import ModelManager
                manager = ModelManager()
                model_path_actual, config_path, model_item = manager.download_model("tts_models/multilingual/multi-dataset/xtts_v2")
                logger.info(f"Model downloaded to: {model_path_actual}")

                # Now initialize with downloaded paths
                self.config = XttsConfig()
                self.config.load_json(config_path)
                self.model = Xtts.init_from_config(self.config)
                self.model.load_checkpoint(self.config, checkpoint_dir=model_path_actual, use_deepspeed=False)
            else:
                # Extract the actual model from the TTS API wrapper
                self.model = tts_api.synthesizer.tts_model
                self.config = tts_api.synthesizer.tts_config

            logger.info("✅ XTTS model loaded")
        else:
            logger.info(f"Loading XTTS v2 model from {checkpoint_dir}...")
            self.config = XttsConfig()
            self.config.load_json(model_path)
            self.model = Xtts.init_from_config(self.config)
            self.model.load_checkpoint(self.config, checkpoint_dir=checkpoint_dir, use_deepspeed=False)

        # Move model to GPU if available
        if torch.cuda.is_available():
            self.model.cuda()
            logger.info("✅ XTTS model loaded on GPU")
        else:
            logger.warning("⚠️ GPU not available, running on CPU (will be slow)")

        # Pre-compute voice embeddings for default voice
        self.voice_reference = voice_reference
        if os.path.exists(voice_reference):
            logger.info(f"Pre-computing voice embeddings from {voice_reference}...")
            self.gpt_cond_latent, self.speaker_embedding = self.model.get_conditioning_latents(
                audio_path=[voice_reference]
            )
            logger.info("✅ Default voice embeddings ready")
        else:
            logger.warning(f"⚠️ Voice reference not found: {voice_reference}")
            self.gpt_cond_latent = None
            self.speaker_embedding = None

        # Warmup GPU
        logger.info("Warming up XTTS model...")
        try:
            warmup_chunks = self.model.inference_stream(
                "Warmup text",
                "en",
                self.gpt_cond_latent,
                self.speaker_embedding,
                enable_text_splitting=True
            )
            _ = list(warmup_chunks)  # Consume generator
            logger.info("✅ XTTS Streaming Service ready")
        except Exception as e:
            logger.warning(f"Warmup failed (may be slow on first request): {e}")

    async def stream(
        self,
        text: str,
        voice: str,
        language: str,
        speed: float,
        cancel_event: asyncio.Event,
    ):
        """
        Stream audio using XTTS inference_stream for real-time generation.

        Args:
            text: Text to synthesize
            voice: Voice identifier (currently uses default voice reference)
            language: Language code (en, es, fr, de, it, pt, pl, tr, ru, nl, cs, ar, zh-cn, ja, hu, ko)
            speed: Speech speed multiplier (0.5-2.0, default 1.0)
            cancel_event: Event to signal cancellation

        Yields:
            bytes: PCM16 audio chunks at 24kHz sample rate
        """
        if not text or not text.strip():
            logger.warning("Empty text received, skipping synthesis")
            return

        logger.info(f"Streaming synthesis: text_len={len(text)}, lang={language}, speed={speed}")

        # Use pre-computed embeddings (voice parameter currently ignored)
        gpt_cond_latent = self.gpt_cond_latent
        speaker_embedding = self.speaker_embedding

        if gpt_cond_latent is None or speaker_embedding is None:
            logger.error("Voice embeddings not available, cannot synthesize")
            return

        try:
            # Get streaming chunks from XTTS
            chunks = self.model.inference_stream(
                text,
                language,
                gpt_cond_latent,
                speaker_embedding,
                enable_text_splitting=True,
                speed=speed,
            )

            chunk_count = 0
            for chunk in chunks:
                # Check for cancellation
                if cancel_event.is_set():
                    logger.info(f"Synthesis cancelled after {chunk_count} chunks")
                    break

                # Convert torch tensor to PCM16 bytes
                # chunk shape: [1, samples] or [samples]
                if chunk.dim() == 2:
                    chunk = chunk.squeeze(0)

                # Ensure on CPU for numpy conversion
                audio_np = chunk.cpu().numpy()

                # Convert float32 [-1, 1] to int16 PCM
                pcm16 = (audio_np * 32767).astype('int16').tobytes()

                chunk_count += 1
                yield pcm16

                # Small yield to allow event loop processing
                await asyncio.sleep(0)

            logger.info(f"Streaming complete: {chunk_count} chunks generated")

        except Exception as e:
            logger.error(f"Streaming synthesis error: {e}", exc_info=True)
            raise
