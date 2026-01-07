import os
import torch
from transformers import AutoProcessor, Llama4ForConditionalGeneration
from core.logger import setup_logger
from models.llm.llm_model import GenerateResponse
from services.llm.locks import generation_lock

from dotenv import load_dotenv
load_dotenv()
logger = setup_logger("vox.service.llm.maverick")


class LammaMaverick:
    """
    Singleton-style LLM service.
    ONE model per process.
    """

    def __init__(self):
        self.model = None
        self.processor = None

        self.MODEL_ID = "meta-llama/Llama-4-Maverick-17B-128E-Instruct"

        self.default_config = {
            "max_new_tokens": 512,
            "temperature": 0.7,
            "top_p": 0.9,
        }

    # ---------- Load once ----------
    def load(self):
        if self.model is not None:
            logger.info("Llama-4 Maverick already loaded")
            return
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA required for Llama-4 Maverick")

        logger.info("GPU memory: %.2f GB",
            torch.cuda.memory_allocated() / 1e9
        )

        logger.info("Loading Llama-4 Maverick model...")
        self.processor = AutoProcessor.from_pretrained(
            self.MODEL_ID,
            token=os.getenv("HF_TOKEN"),
        )

        self.model = Llama4ForConditionalGeneration.from_pretrained(
            self.MODEL_ID,
            torch_dtype=torch.bfloat16,
            device_map="auto",
            attn_implementation="flex_attention",
        )

        self.model.eval()

        logger.info("✅ Llama-4 Maverick loaded successfully")

    # ---------- Generate ----------
    def generate_response(
    self,
    prompt: str,
    max_new_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
) -> GenerateResponse:

        if self.model is None or self.processor is None:
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

        inputs = self.processor(prompt, return_tensors="pt")
        inputs = {k: v.to(self.model.device) for k, v in inputs.items()}

        with torch.no_grad():
            with generation_lock:
                output_ids = self.model.generate(
                    **inputs,
                    max_new_tokens=cfg["max_new_tokens"],
                    temperature=cfg["temperature"],
                    top_p=cfg["top_p"],
                    do_sample=cfg["temperature"] > 0,
                )

        text = self.processor.decode(
            output_ids[0],
            skip_special_tokens=True,
        )

        logger.info("Generation completed")

        return GenerateResponse(text=text)
    
    def generate_stream(self, session, streamer, generation_kwargs):
        from services.llm.locks import generation_lock

        with generation_lock:
            if session.cancel_event.is_set():
                return

            self.model.generate(
                **generation_kwargs,
                streamer=streamer,
            )

            # free KV cache
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

