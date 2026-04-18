from __future__ import annotations

import gc
import logging
import os
import platform

import torch

from indextts.infer_v2 import IndexTTS2

from api.database.engine import create_voice_session_factory
from api.services import voices as voice_service

logger = logging.getLogger("indextts2-api")


def clear_cuda_cache() -> None:
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
        gc.collect()


def get_cuda_memory_info():
    if torch.cuda.is_available():
        allocated = torch.cuda.memory_allocated() / 1024**3
        reserved = torch.cuda.memory_reserved() / 1024**3
        total = torch.cuda.get_device_properties(0).total_memory / 1024**3
        free = total - reserved
        return {
            "allocated_gb": round(allocated, 2),
            "reserved_gb": round(reserved, 2),
            "total_gb": round(total, 2),
            "free_gb": round(free, 2),
        }
    return None


class IndexTTS2Model:
    def __init__(
        self,
        model_dir: str = "checkpoints",
        device=None,
        use_fp16: bool = False,
        use_deepspeed: bool = False,
        use_cuda_kernel: bool = True,
    ):
        if device is not None:
            self.device = device
        elif platform.system() == "Darwin" and torch.backends.mps.is_available():
            self.device = "mps"
            logger.info(f"Using MPS device: {self.device}")
        elif torch.cuda.is_available():
            self.device = "cuda"
            logger.info(
                f"Using CUDA device: {self.device} (CUDA_VISIBLE_DEVICES={os.environ.get('CUDA_VISIBLE_DEVICES', 'not set')})"
            )
        else:
            self.device = "cpu"
            logger.info("GPU acceleration not available, using CPU")

        self.model_dir = model_dir
        logger.info(f"Initializing IndexTTS2 model from {model_dir}")
        self.tts_model = IndexTTS2(
            model_dir=model_dir,
            cfg_path=os.path.join(model_dir, "config.yaml"),
            use_fp16=use_fp16,
            use_deepspeed=use_deepspeed,
            use_cuda_kernel=use_cuda_kernel,
        )
        logger.info("IndexTTS2 model initialized")
        self.sampling_rate = 24000
        logger.info(f"Model sample rate: {self.sampling_rate}")

        self.prompt_dir = "assets/speakers"
        if not os.path.exists(self.prompt_dir):
            os.makedirs(self.prompt_dir, exist_ok=True)
            logger.info(f"Created prompt directory: {self.prompt_dir}")
        self.voice_session_factory = create_voice_session_factory(self.prompt_dir)
        voice_service.sync_files_to_voice_db(self.voice_session_factory, self.prompt_dir)

    def generate_speech(
        self,
        text,
        prompt_speech_path=None,
        speaker=None,
        temperature=0.8,
        top_k=30,
        top_p=0.8,
        seed=421,
        max_text_tokens_per_segment=120,
        max_mel_tokens=1500,
        num_beams=3,
        length_penalty=0.0,
        repetition_penalty=10.0,
        do_sample=True,
        emo_audio_prompt=None,
        emo_alpha=1.0,
        emo_vector=None,
        use_emo_text=False,
        emo_text=None,
        use_random=False,
        interval_silence=200,
        emo_control_mode=0,
    ):
        logger.info(f"Generating speech for text: {text[:50]}...")
        torch.manual_seed(seed)

        try:
            if speaker and not prompt_speech_path:
                db_prompt_path = voice_service.resolve_voice_prompt_path(
                    self.voice_session_factory, self.prompt_dir, speaker
                )
                if db_prompt_path:
                    prompt_speech_path = db_prompt_path
                else:
                    prompt_speech_path = self.find_prompt_by_speaker(speaker)
                    voice_service.upsert_voice(
                        self.voice_session_factory,
                        self.prompt_dir,
                        voice_id=speaker,
                        file_name=os.path.basename(prompt_speech_path),
                        name=speaker,
                    )

            if not prompt_speech_path:
                raise ValueError("必须提供prompt_speech_path或speaker参数")

            if prompt_speech_path:
                if not os.path.isabs(prompt_speech_path):
                    filename = os.path.basename(prompt_speech_path)
                    prompt_speech_path = os.path.join(self.prompt_dir, filename)
                if not os.path.exists(prompt_speech_path):
                    logger.warning(f"Prompt audio file not found: {prompt_speech_path}")
                    raise ValueError(f"提示音频文件不存在: {prompt_speech_path}")
                logger.info(f"Prompt audio: {prompt_speech_path}")

            if emo_control_mode == 1 and emo_audio_prompt:
                if not os.path.isabs(emo_audio_prompt):
                    filename = os.path.basename(emo_audio_prompt)
                    emo_audio_prompt = os.path.join(self.prompt_dir, filename)
                if not os.path.exists(emo_audio_prompt):
                    logger.warning(f"Emotion audio file not found: {emo_audio_prompt}")
                    emo_audio_prompt = None
                    emo_alpha = 1.0
            elif emo_control_mode == 2 and emo_vector:
                if len(emo_vector) != 8:
                    raise ValueError("情感向量必须包含8个值: [喜,怒,哀,惧,厌恶,低落,惊喜,平静]")
                if sum(emo_vector) > 1.5:
                    raise ValueError("情感向量之和不能超过1.5")
                emo_audio_prompt = None
                emo_alpha = 1.0
            elif emo_control_mode == 3:
                use_emo_text = True
                emo_audio_prompt = None
                emo_alpha = 1.0
                emo_vector = None
            else:
                emo_audio_prompt = None
                emo_alpha = 1.0
                emo_vector = None
                use_emo_text = False

            generation_kwargs = {
                "do_sample": do_sample,
                "top_p": top_p,
                "top_k": top_k if top_k > 0 else None,
                "temperature": temperature,
                "length_penalty": length_penalty,
                "num_beams": num_beams,
                "repetition_penalty": repetition_penalty,
                "max_mel_tokens": max_mel_tokens,
            }

            result = self.tts_model.infer(
                spk_audio_prompt=prompt_speech_path,
                text=text,
                output_path=None,
                emo_audio_prompt=emo_audio_prompt,
                emo_alpha=emo_alpha,
                emo_vector=emo_vector,
                use_emo_text=use_emo_text,
                emo_text=emo_text,
                use_random=use_random,
                interval_silence=interval_silence,
                verbose=False,
                max_text_tokens_per_segment=max_text_tokens_per_segment,
                **generation_kwargs,
            )

            if result is None:
                raise ValueError("音频生成失败")
            if isinstance(result, tuple) and len(result) == 2:
                sample_rate, wav_np = result
                wav_data = (
                    torch.as_tensor(wav_np, dtype=torch.float32).squeeze() / 32768.0
                ).cpu().numpy()
                if speaker:
                    voice_service.record_voice_usage(
                        self.voice_session_factory,
                        self.prompt_dir,
                        speaker,
                        len(wav_data) / max(sample_rate, 1),
                    )
                logger.info(f"Generated audio of length: {len(wav_data)/sample_rate:.2f} seconds")
                return wav_data, sample_rate
            raise ValueError("音频生成失败：意外的推理返回值")

        except Exception as e:
            logger.error(f"Error generating speech: {e}", exc_info=True)
            raise ValueError(f"Failed to generate speech: {str(e)}")

    def find_prompt_by_speaker(self, speaker_name):
        if not os.path.exists(self.prompt_dir) or not os.listdir(self.prompt_dir):
            raise FileNotFoundError(f"提示音频目录不存在或为空: {self.prompt_dir}")

        for ext in [".wav", ".mp3"]:
            exact_match = os.path.join(self.prompt_dir, f"{speaker_name}{ext}")
            if os.path.exists(exact_match):
                return exact_match

        partial_matches = []
        for file in os.listdir(self.prompt_dir):
            if file.endswith((".wav", ".mp3")) and speaker_name.lower() in file.lower():
                partial_matches.append(file)

        if partial_matches:
            matched_file = partial_matches[0]
            prompt_path = os.path.join(self.prompt_dir, matched_file)
            logger.warning(f"未找到精确匹配'{speaker_name}'的音频，使用部分匹配: {matched_file}")
            return prompt_path

        audio_files = [f for f in os.listdir(self.prompt_dir) if f.endswith((".wav", ".mp3"))]
        if audio_files:
            audio_files.sort()
            prompt_path = os.path.join(self.prompt_dir, audio_files[0])
            logger.warning(f"未找到与'{speaker_name}'相关的音频，使用默认音频: {audio_files[0]}")
            return prompt_path

        raise FileNotFoundError(f"未找到任何可用的提示音频文件，请检查{self.prompt_dir}目录")

    def generate_speech_segment(self, text_segment, **kwargs):
        logger.debug(f"Generating segment: {text_segment[:30]}...")
        try:
            wav_data, sample_rate = self.generate_speech(text=text_segment, **kwargs)
            return {
                "text": text_segment,
                "audio": wav_data.tolist(),
                "sample_rate": sample_rate,
            }
        except Exception as e:
            logger.error(f"Error generating segment: {e}", exc_info=True)
            raise


logger.info("Initializing IndexTTS2 model...")
model_dir = "checkpoints"
if not os.path.exists(model_dir):
    logger.error(f"Model directory {model_dir} does not exist. Please download the model first.")
    raise FileNotFoundError(f"Model directory {model_dir} does not exist")

required_files = [
    "bpe.model",
    "gpt.pth",
    "config.yaml",
    "s2mel.pth",
    "wav2vec2bert_stats.pt",
]
for file in required_files:
    file_path = os.path.join(model_dir, file)
    if not os.path.exists(file_path):
        logger.error(f"Required file {file_path} does not exist. Please download it.")
        raise FileNotFoundError(f"Required file {file_path} does not exist")

model = IndexTTS2Model(
    model_dir=model_dir,
    use_fp16=False,
    use_deepspeed=False,
    use_cuda_kernel=False,
)
logger.info("Model initialization complete")
