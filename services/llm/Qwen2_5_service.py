import os
import torch
import threading
from transformers import AutoModelForCausalLM, AutoTokenizer, TextIteratorStreamer
from core.logger import setup_logger
from models.llm.llm_model import GenerateResponse
from services.llm.locks import generation_lock
from dotenv import load_dotenv

load_dotenv()
logger = setup_logger("vox.service.llm.qwen")


class QwenService:
    """
    Singleton-style service for Qwen LLM.
    ONE model per process.
    """

    def __init__(self):
        self.model = None
        self.tokenizer = None
        self.MODEL_ID = "Qwen/Qwen2.5-1.5B-Instruct"

        self.default_config = {
            "max_new_tokens": 512,
            "temperature": 0.7,
            "top_p": 0.9,
        }

    # ---------- Load once ----------
    def load(self):
        if self.model is not None:
            logger.info("Qwen model already loaded")
            return

        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info("Loading Qwen model on %s...", device)

        self.tokenizer = AutoTokenizer.from_pretrained(self.MODEL_ID)
        self.model = AutoModelForCausalLM.from_pretrained(
            self.MODEL_ID,
            torch_dtype=torch.bfloat16,
            device_map="auto" if device == "cuda" else None,
        )
        self.model.eval()

        logger.info("✅ Qwen model loaded successfully")

    # ---------- Generate response ----------
    def generate_response(
        self,
        prompt: str,
        max_new_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> GenerateResponse:

        if self.model is None or self.tokenizer is None:
            raise RuntimeError("Model not loaded. Call load() first.")

        cfg = {
            "max_new_tokens": max_new_tokens or self.default_config["max_new_tokens"],
            "temperature": temperature if temperature is not None else self.default_config["temperature"],
            "top_p": top_p if top_p is not None else self.default_config["top_p"],
        }

        logger.info(
            "Generating response | tokens=%s temp=%s top_p=%s",
            cfg["max_new_tokens"],
            cfg["temperature"],
            cfg["top_p"],
        )

        # Apply chat template for multi-turn context if needed
        messages = [
            {"role": "system", "content": "You are Qwen, a helpful assistant."},
            {"role": "user", "content": prompt},
        ]
        text_prompt = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )

        model_inputs = self.tokenizer([text_prompt], return_tensors="pt").to(self.model.device)

        with torch.no_grad():
            with generation_lock:
                generated_ids = self.model.generate(
                    **model_inputs,
                    max_new_tokens=cfg["max_new_tokens"],
                    temperature=cfg["temperature"],
                    do_sample=True,
                    top_p=cfg["top_p"],
                )

        # Strip the input tokens from output
        generated_ids = [
            output_ids[len(input_ids):]
            for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)
        ]

        text = self.tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]

        logger.info("Generation completed")
        return GenerateResponse(text=text)

    # ---------- Streaming generation ----------
    def generate_stream(self, session, streamer: TextIteratorStreamer, generation_kwargs: dict):
        from services.llm.locks import generation_lock

        with generation_lock:
            if session.cancel_event.is_set():
                return

            self.model.generate(
                **generation_kwargs,
                streamer=streamer,
            )

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
