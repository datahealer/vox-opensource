import asyncio
import numpy as np
from TTS.api import TTS
import numpy as np
import torch

from TTS.tts.configs.xtts_config import XttsConfig
from TTS.tts.models.xtts import XttsAudioConfig, XttsArgs
from TTS.config.shared_configs import BaseDatasetConfig

# 🔐 Allow XTTS checkpoint globals (PyTorch 2.6+)
torch.serialization.add_safe_globals([
    XttsConfig,
    XttsAudioConfig,
    XttsArgs,
    BaseDatasetConfig,
])



SAMPLE_RATE = 24000
CHUNK_MS = 100


class XTTSService():
    def __init__(self):
        self.tts = TTS(
            "tts_models/multilingual/multi-dataset/xtts_v2",
            gpu=True
        )

    async def stream(
        self,
        text: str,
        voice: str,
        language:str,
        speed: float,
        cancel_event,
    ):
        wav = self.tts.tts(
            text=text,
            speaker=voice,
            language=language,
            speaker_wav="voices/default.wav",
            speed=speed,
        )

        samples_per_chunk = int(SAMPLE_RATE * CHUNK_MS / 1000)

        for i in range(0, len(wav), samples_per_chunk):
            if cancel_event.is_set():
                return

            

            chunk = np.array(wav[i:i + samples_per_chunk])  # convert list to NumPy array
            pcm16 = (chunk * 32767).astype(np.int16).tobytes()

            yield pcm16
            await asyncio.sleep(CHUNK_MS / 1000)
