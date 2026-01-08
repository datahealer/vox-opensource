import os
import torch
import threading
from typing import Generator
from transformers import (
    AutoProcessor,
    Llama4ForConditionalGeneration,
    TextIteratorStreamer,
)
from dotenv import load_dotenv
from core.logger import setup_logger
from sessions.session import LLMSession
from utils.locks import generation_lock

load_dotenv()
logger = setup_logger("vox.service.llm.maverick")

class LammaMaverick():
    MODEL_ID = "meta-llama/Llama-4-Maverick-17B-128E-Instruct"

    def __init__(self):
        self.model = None
        self.processor = None
        self.defaults = {
            "max_new_tokens": 512,
            "temperature": 0.7,
            "top_p": 0.9,
        }

    # ---------- LOAD ----------
    def load(self):
        if self.model:
            return

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA required")

        logger.info("Loading Llama-4 Maverick...")

        self.processor = AutoProcessor.from_pretrained(
            self.MODEL_ID,
            token=os.getenv("HF_TOKEN"),
        )

        self.model = Llama4ForConditionalGeneration.from_pretrained(
            self.MODEL_ID,
            torch_dtype=torch.bfloat16,
            device_map="auto",
            attn_implementation="flex_attention",
        ).eval()

        logger.info("✅ Model loaded")

    # ---------- STREAM ----------
    def generate_stream(
        self,
        session: LLMSession,
        prompt: str,
        **kwargs,
    ) -> Generator[str, None, None]:

        self._ensure_loaded()
        cfg = self._merge_cfg(kwargs)

        streamer = TextIteratorStreamer(
            self.processor,
            skip_prompt=True,
            skip_special_tokens=True,
        )

        inputs = self._prepare_inputs(prompt)

        generation_kwargs = dict(
            **inputs,
            streamer=streamer,
            max_new_tokens=cfg["max_new_tokens"],
            temperature=cfg["temperature"],
            top_p=cfg["top_p"],
            do_sample=True,
        )

        def _run():
            with generation_lock:
                if session.cancel_event.is_set():
                    return
                self.model.generate(**generation_kwargs)
                torch.cuda.empty_cache()

        threading.Thread(target=_run, daemon=True).start()

        for token in streamer:
            if session.cancel_event.is_set():
                break
            yield token

    # ---------- NON STREAM ----------
    def generate(self, prompt: str, **kwargs) -> str:
        self._ensure_loaded()
        cfg = self._merge_cfg(kwargs)

        inputs = self._prepare_inputs(prompt)

        with torch.no_grad(), generation_lock:
            output = self.model.generate(
                **inputs,
                max_new_tokens=cfg["max_new_tokens"],
                temperature=cfg["temperature"],
                top_p=cfg["top_p"],
                do_sample=cfg["temperature"] > 0,
            )

        return self.processor.decode(output[0], skip_special_tokens=True)

    # ---------- HELPERS ----------
    def _prepare_inputs(self, prompt):
        inputs = self.processor(prompt, return_tensors="pt")
        return {k: v.to(self.model.device) for k, v in inputs.items()}

    def _merge_cfg(self, kwargs):
        return {
            "max_new_tokens": kwargs.get("max_new_tokens", self.defaults["max_new_tokens"]),
            "temperature": kwargs.get("temperature", self.defaults["temperature"]),
            "top_p": kwargs.get("top_p", self.defaults["top_p"]),
        }

    def _ensure_loaded(self):
        if not self.model or not self.processor:
            raise RuntimeError("Model not loaded")
