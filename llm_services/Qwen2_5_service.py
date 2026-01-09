import os
import torch
import threading
from typing import Generator
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    TextIteratorStreamer,
)
from dotenv import load_dotenv
from core.logger import setup_logger
from sessions.session import LLMSession
from utils.locks import generation_lock

load_dotenv()
logger = setup_logger("vox.service.llm.qwen")


class QwenService:
    MODEL_ID = "Qwen/Qwen2.5-1.5B-Instruct"

    def __init__(self):
        self.model = None
        self.tokenizer = None
        self.defaults = {
            "max_new_tokens": 512,
            "temperature": 0.7,
            "top_p": 0.9,
        }

    # ---------- LOAD ----------
    def load(self):
        if self.model:
            return

        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info("Loading Qwen on %s...", device)

        self.tokenizer = AutoTokenizer.from_pretrained(self.MODEL_ID)

        self.model = AutoModelForCausalLM.from_pretrained(
            self.MODEL_ID,
            torch_dtype=torch.bfloat16 if device == "cuda" else torch.float32,
            device_map="auto" if device == "cuda" else None,
        ).eval()

        logger.info("✅ Qwen loaded")

    # ---------- STREAM ----------
    def generate_stream(
    self,
    session: LLMSession,
    messages: list,
    **kwargs,
    ):
        self._ensure_loaded()
        cfg = self._merge_cfg(kwargs)

        streamer = TextIteratorStreamer(
            self.tokenizer,
            skip_prompt=True,
            skip_special_tokens=True,
        )

        inputs = self._prepare_inputs_from_messages(messages)

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

        threading.Thread(target=_run, daemon=True).start()

        for token in streamer:
            if session.cancel_event.is_set():
                break
            yield token


    # ---------- NON-STREAM ----------
    def generate(self, prompt: str, **kwargs) -> str:
        self._ensure_loaded()
        cfg = self._merge_cfg(kwargs)

        inputs = self._prepare_inputs(prompt)

        with torch.no_grad(), generation_lock:
            output_ids = self.model.generate(
                **inputs,
                max_new_tokens=cfg["max_new_tokens"],
                temperature=cfg["temperature"],
                top_p=cfg["top_p"],
                do_sample=cfg["temperature"] > 0,
            )

        # strip prompt tokens
        output_ids = output_ids[:, inputs["input_ids"].shape[1]:]
        return self.tokenizer.decode(output_ids[0], skip_special_tokens=True)


    # ---------- HELPERS ----------
    def _prepare_inputs(self, prompt: str):
        messages = [
            {"role": "system", "content": "You are Qwen, a helpful assistant."},
            {"role": "user", "content": prompt},
        ]

        text = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )

        inputs = self.tokenizer(text, return_tensors="pt")
        return {k: v.to(self.model.device) for k, v in inputs.items()}
    
    def _prepare_inputs_from_messages(self, messages):
        text = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        inputs = self.tokenizer(text, return_tensors="pt")
        return {k: v.to(self.model.device) for k, v in inputs.items()}

    def _merge_cfg(self, kwargs):
        return {
            "max_new_tokens": kwargs.get("max_new_tokens", self.defaults["max_new_tokens"]),
            "temperature": kwargs.get("temperature", self.defaults["temperature"]),
            "top_p": kwargs.get("top_p", self.defaults["top_p"]),
        }

    def _ensure_loaded(self):
        if not self.model or not self.tokenizer:
            raise RuntimeError("Model not loaded")

