import os

# 在导入torch之前设置GPU，确保使用指定的GPU
# 如果未设置CUDA_VISIBLE_DEVICES，默认使用GPU 0
if "CUDA_VISIBLE_DEVICES" not in os.environ:
    os.environ["CUDA_VISIBLE_DEVICES"] = "0"
    print(f"[INFO] CUDA_VISIBLE_DEVICES not set, defaulting to GPU 0")
else:
    print(f"[INFO] Using CUDA_VISIBLE_DEVICES={os.environ['CUDA_VISIBLE_DEVICES']}")

import io
import time
import json
import torch
import torchaudio
import logging
import soundfile as sf
import re
import gc
import asyncio
from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from typing import List, Generator, Optional, Union
import platform
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager
import threading

from indextts.infer_v2 import IndexTTS2

# 配置日志
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("indextts2-api")

# 创建FastAPI应用
_API_DESCRIPTION = """
## IndexTTS 2.0 API 使用说明

### 服务启动
```bash
python api_server.py
# 或指定端口: uvicorn api_server:app --host 0.0.0.0 --port 8002
```
默认地址: http://localhost:8002  
交互式文档: http://localhost:8002/docs

### 端点概览
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | / | 服务信息与端点列表 |
| GET | /speakers | 获取可用说话人列表 |
| POST | /tts | 基础 TTS（兼容 1.0） |
| POST | /tts_v2 | 增强 TTS（情感控制等） |
| POST | /tts_stream | 流式 TTS |
| POST | /upload_audio | 上传参考音频 |

### 通用说明
- **音色指定**：`prompt_speech_path`（文件名或路径）与 `speaker`（名称）二选一必填；未写路径时从 `assets/speakers/` 下按名称查找。
- **响应**：/tts、/tts_v2 返回 `audio/wav` 二进制；/tts_stream 返回 `application/x-ndjson` 流（每行一个 JSON）。
"""
app = FastAPI(title="IndexTTS 2.0 API", version="2.0.0", description=_API_DESCRIPTION)

# 推理锁 - 防止并发推理导致显存溢出
inference_lock = asyncio.Lock()

def clear_cuda_cache():
    """清理CUDA显存缓存"""
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
        gc.collect()
        logger.debug("CUDA cache cleared")

def get_cuda_memory_info():
    """获取CUDA显存信息"""
    if torch.cuda.is_available():
        allocated = torch.cuda.memory_allocated() / 1024**3
        reserved = torch.cuda.memory_reserved() / 1024**3
        total = torch.cuda.get_device_properties(0).total_memory / 1024**3
        free = total - reserved
        return {
            "allocated_gb": round(allocated, 2),
            "reserved_gb": round(reserved, 2),
            "total_gb": round(total, 2),
            "free_gb": round(free, 2)
        }
    return None

@contextmanager
def cuda_memory_manager():
    """CUDA显存管理上下文管理器"""
    try:
        # 推理前清理
        clear_cuda_cache()
        mem_before = get_cuda_memory_info()
        if mem_before:
            logger.info(f"CUDA memory before inference: {mem_before}")
        yield
    finally:
        # 推理后清理
        clear_cuda_cache()
        mem_after = get_cuda_memory_info()
        if mem_after:
            logger.info(f"CUDA memory after cleanup: {mem_after}")

# 定义请求模型 - 基础TTS请求（兼容1.0版本）
class TextToSpeechRequest(BaseModel):
    text: str
    prompt_speech_path: Optional[str] = None
    speaker: Optional[str] = None
    temperature: float = 0.8
    top_k: int = 30
    top_p: float = 0.8
    seed: int = 421
    max_text_tokens_per_sentence: int = 120
    sentences_bucket_max_size: int = 4
    max_mel_tokens: int = 1500
    num_beams: int = 3
    length_penalty: float = 0.0
    repetition_penalty: float = 10.0

# 定义请求模型 - 增强版TTS请求（2.0新功能）
class EnhancedTTSRequest(BaseModel):
    text: str
    prompt_speech_path: Optional[str] = None
    speaker: Optional[str] = None
    
    # 基础生成参数
    temperature: float = 0.8
    top_k: int = 30
    top_p: float = 0.8
    seed: int = 421
    max_text_tokens_per_segment: int = 120
    max_mel_tokens: int = 1500
    num_beams: int = 3
    length_penalty: float = 0.0
    repetition_penalty: float = 10.0
    do_sample: bool = True
    
    # 情感控制参数
    emo_audio_prompt: Optional[str] = None  # 情感参考音频
    emo_alpha: float = 1.0  # 情感权重
    emo_vector: Optional[List[float]] = None  # 情感向量 [喜,怒,哀,惧,厌恶,低落,惊喜,平静]
    use_emo_text: bool = False  # 是否使用文本情感分析
    emo_text: Optional[str] = None  # 情感描述文本
    use_random: bool = False  # 是否使用随机采样
    interval_silence: int = 200  # 间隔静音
    
    # 情感控制模式：0=与音色相同, 1=使用情感参考音频, 2=使用情感向量, 3=使用情感文本
    emo_control_mode: int = 0

# 流式处理请求模型
class StreamTTSRequest(BaseModel):
    text: str
    prompt_speech_path: Optional[str] = None
    speaker: Optional[str] = None
    
    # 基础生成参数
    temperature: float = 0.8
    top_k: int = 30
    top_p: float = 0.8
    seed: int = 421
    max_text_tokens_per_segment: int = 120
    max_mel_tokens: int = 1500
    num_beams: int = 3
    length_penalty: float = 0.0
    repetition_penalty: float = 10.0
    do_sample: bool = True
    
    # 情感控制参数
    emo_audio_prompt: Optional[str] = None
    emo_alpha: float = 1.0
    emo_vector: Optional[List[float]] = None
    use_emo_text: bool = False
    emo_text: Optional[str] = None
    use_random: bool = False
    interval_silence: int = 200
    emo_control_mode: int = 0
    
    # 流式参数
    max_segment_length: int = 100  # 最大分段长度

# 初始化模型（全局变量，避免重复加载）
class IndexTTS2Model:
    def __init__(self, model_dir='checkpoints', device=None, use_fp16=False, use_deepspeed=False, use_cuda_kernel=True):
        # 确定设备
        if device is not None:
            self.device = device
        elif platform.system() == "Darwin" and torch.backends.mps.is_available():
            # macOS with MPS support (Apple Silicon)
            self.device = "mps"
            logger.info(f"Using MPS device: {self.device}")
        elif torch.cuda.is_available():
            # System with CUDA support
            # 使用"cuda"而非"cuda:0"，配合CUDA_VISIBLE_DEVICES自动选择正确的GPU
            self.device = "cuda"
            logger.info(f"Using CUDA device: {self.device} (CUDA_VISIBLE_DEVICES={os.environ.get('CUDA_VISIBLE_DEVICES', 'not set')})")
        else:
            # Fall back to CPU
            self.device = "cpu"
            logger.info("GPU acceleration not available, using CPU")
        
        self.model_dir = model_dir
        
        # 初始化IndexTTS2模型 - 使用与webui.py完全相同的参数顺序和方式
        logger.info(f"Initializing IndexTTS2 model from {model_dir}")
        self.tts_model = IndexTTS2(
            model_dir=model_dir,
            cfg_path=os.path.join(model_dir, "config.yaml"),
            use_fp16=use_fp16,
            use_deepspeed=use_deepspeed,
            use_cuda_kernel=use_cuda_kernel
            # 注意：不传递device参数，让IndexTTS2自动检测，与webui.py一致
        )
        logger.info("IndexTTS2 model initialized")
        
        # 获取采样率
        self.sampling_rate = 24000  # IndexTTS固定采样率
        logger.info(f"Model sample rate: {self.sampling_rate}")
        
        # 确保输出目录存在
        os.makedirs("outputs", exist_ok=True)
        
        # 音频提示文件目录
        self.prompt_dir = "assets/speakers"
        if not os.path.exists(self.prompt_dir):
            os.makedirs(self.prompt_dir, exist_ok=True)
            logger.info(f"Created prompt directory: {self.prompt_dir}")
        
    def generate_speech(self, text, prompt_speech_path=None, speaker=None,
                       temperature=0.8, top_k=30, top_p=0.8, seed=421,
                       max_text_tokens_per_segment=120, max_mel_tokens=1500, 
                       num_beams=3, length_penalty=0.0, repetition_penalty=10.0,
                       do_sample=True, emo_audio_prompt=None, emo_alpha=1.0,
                       emo_vector=None, use_emo_text=False, emo_text=None,
                       use_random=False, interval_silence=200, emo_control_mode=0):
        """生成语音 - 2.0版本支持情感控制"""
        logger.info(f"Generating speech for text: {text[:50]}...")
        
        # 设置随机种子
        torch.manual_seed(seed)
        
        try:
            # 处理speaker参数(优先使用prompt_speech_path)
            if speaker and not prompt_speech_path:
                prompt_speech_path = self.find_prompt_by_speaker(speaker)
                logger.info(f"Using speaker audio prompt: {prompt_speech_path}")
            
            # 验证参数
            if not prompt_speech_path:
                raise ValueError("必须提供prompt_speech_path或speaker参数")
            
            # 处理音频提示路径
            if prompt_speech_path:
                # 统一处理路径
                if not os.path.isabs(prompt_speech_path):
                    # 提取纯文件名（移除可能的路径前缀）
                    filename = os.path.basename(prompt_speech_path)
                    prompt_speech_path = os.path.join(self.prompt_dir, filename)
                
                # 检查文件是否存在
                if not os.path.exists(prompt_speech_path):
                    logger.warning(f"Prompt audio file not found: {prompt_speech_path}")
                    raise ValueError(f"提示音频文件不存在: {prompt_speech_path}")
            
            # 处理情感控制模式
            if emo_control_mode == 1 and emo_audio_prompt:
                # 使用情感参考音频
                if not os.path.isabs(emo_audio_prompt):
                    filename = os.path.basename(emo_audio_prompt)
                    emo_audio_prompt = os.path.join(self.prompt_dir, filename)
                
                if not os.path.exists(emo_audio_prompt):
                    logger.warning(f"Emotion audio file not found: {emo_audio_prompt}")
                    emo_audio_prompt = None
                    emo_alpha = 1.0
            elif emo_control_mode == 2 and emo_vector:
                # 使用情感向量控制
                if len(emo_vector) != 8:
                    raise ValueError("情感向量必须包含8个值: [喜,怒,哀,惧,厌恶,低落,惊喜,平静]")
                if sum(emo_vector) > 1.5:
                    raise ValueError("情感向量之和不能超过1.5")
                emo_audio_prompt = None
                emo_alpha = 1.0
            elif emo_control_mode == 3:
                # 使用情感文本控制
                use_emo_text = True
                emo_audio_prompt = None
                emo_alpha = 1.0
                emo_vector = None
            else:
                # 模式0：与音色参考音频相同
                emo_audio_prompt = None
                emo_alpha = 1.0
                emo_vector = None
                use_emo_text = False
            
            # 生成临时输出文件
            output_path = os.path.join("outputs", f"temp_{int(time.time() * 1000)}.wav")
            
            # 准备生成参数
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
            
            # 调用IndexTTS2的infer方法
            result_path = self.tts_model.infer(
                spk_audio_prompt=prompt_speech_path,
                text=text,
                output_path=output_path,
                emo_audio_prompt=emo_audio_prompt,
                emo_alpha=emo_alpha,
                emo_vector=emo_vector,
                use_emo_text=use_emo_text,
                emo_text=emo_text,
                use_random=use_random,
                interval_silence=interval_silence,
                verbose=False,
                max_text_tokens_per_segment=max_text_tokens_per_segment,
                **generation_kwargs
            )
            
            # 读取生成的音频文件
            if os.path.exists(result_path):
                wav_data, sample_rate = torchaudio.load(result_path)
                # 清理临时文件
                os.remove(result_path)
                
                # 转换为numpy格式
                wav_data = wav_data.squeeze().numpy()
                
                logger.info(f"Generated audio of length: {len(wav_data)/sample_rate:.2f} seconds")
                return wav_data, sample_rate
            else:
                raise ValueError("音频生成失败，未找到输出文件")
        
        except Exception as e:
            logger.error(f"Error generating speech: {e}", exc_info=True)
            raise ValueError(f"Failed to generate speech: {str(e)}")
    
    def find_prompt_by_speaker(self, speaker_name):
        """查找音频提示文件"""
        if not os.path.exists(self.prompt_dir) or not os.listdir(self.prompt_dir):
            raise FileNotFoundError(f"提示音频目录不存在或为空: {self.prompt_dir}")
        
        # 按优先级搜索：精确匹配 > 部分匹配 > 任意音频文件
        # 1. 精确匹配
        for ext in ['.wav', '.mp3']:
            exact_match = os.path.join(self.prompt_dir, f"{speaker_name}{ext}")
            if os.path.exists(exact_match):
                logger.info(f"找到精确匹配的提示音频: {exact_match}")
                return exact_match
        
        # 2. 部分匹配 - 查找文件名包含speaker_name的文件
        partial_matches = []
        for file in os.listdir(self.prompt_dir):
            if file.endswith(('.wav', '.mp3')) and speaker_name.lower() in file.lower():
                partial_matches.append(file)
        
        if partial_matches:
            # 使用第一个匹配项
            matched_file = partial_matches[0]
            prompt_path = os.path.join(self.prompt_dir, matched_file)
            logger.warning(f"未找到精确匹配'{speaker_name}'的音频，使用部分匹配: {matched_file}")
            return prompt_path
        
        # 3. 任意音频文件
        audio_files = [f for f in os.listdir(self.prompt_dir) if f.endswith(('.wav', '.mp3'))]
        if audio_files:
            # 按字母顺序排序，保证结果一致性
            audio_files.sort()
            prompt_path = os.path.join(self.prompt_dir, audio_files[0])
            logger.warning(f"未找到与'{speaker_name}'相关的音频，使用默认音频: {audio_files[0]}")
            return prompt_path
        
        # 如果没有找到任何音频文件
        raise FileNotFoundError(f"未找到任何可用的提示音频文件，请检查{self.prompt_dir}目录")
    
    def generate_speech_segment(self, text_segment, **kwargs):
        """为流式API生成单个段落的音频"""
        logger.debug(f"Generating segment: {text_segment[:30]}...")
        
        try:
            # 生成语音
            wav_data, sample_rate = self.generate_speech(
                text=text_segment,
                **kwargs
            )
            
            # 创建包含音频数据和采样率的字典
            audio_data = {
                "text": text_segment,
                "audio": wav_data.tolist(),
                "sample_rate": sample_rate
            }
            
            return audio_data
        except Exception as e:
            logger.error(f"Error generating segment: {e}", exc_info=True)
            raise

# 初始化模型 - 与webui.py保持一致
logger.info("Initializing IndexTTS2 model...")

# 注意：IndexTTS 2.0 在首次运行时会自动下载以下Hugging Face模型：
# - facebook/w2v-bert-2.0 (用于语音特征提取)
# - amphion/MaskGCT (用于语义编码)  
# - pyannote/speaker-diarization (用于说话人识别)
# - microsoft/unispeech-sat-base-plus (用于声学特征)
# 这些是2.0版本新增的情感控制和高级功能所必需的，与1.0版本不同
# 下载完成后会缓存到~/.cache/huggingface/目录，后续不会重复下载

# 检查必需文件是否存在（与webui.py一致）
model_dir = "checkpoints"
if not os.path.exists(model_dir):
    logger.error(f"Model directory {model_dir} does not exist. Please download the model first.")
    raise FileNotFoundError(f"Model directory {model_dir} does not exist")

required_files = [
    "bpe.model",
    "gpt.pth", 
    "config.yaml",
    "s2mel.pth",
    "wav2vec2bert_stats.pt"
]

for file in required_files:
    file_path = os.path.join(model_dir, file)
    if not os.path.exists(file_path):
        logger.error(f"Required file {file_path} does not exist. Please download it.")
        raise FileNotFoundError(f"Required file {file_path} does not exist")

# 使用与webui.py相同的参数初始化模型
model = IndexTTS2Model(
    model_dir=model_dir,
    use_fp16=False,  # 默认关闭fp16，与webui.py默认值一致
    use_deepspeed=False,  # 默认关闭deepspeed
    use_cuda_kernel=False  # 默认关闭cuda_kernel，避免编译问题
)
logger.info("Model initialization complete")

# 文本分段函数
def split_text(text: str, max_length: int = 100) -> List[str]:
    # 如果文本长度小于max_length，直接返回
    if len(text) <= max_length:
        return [text]
    
    # 定义分隔符优先级（从高到低）
    separators = ['. ', '! ', '? ', '; ', ', ', ' ', '。', '！', '？', '；', '，']
    
    segments = []
    while len(text) > max_length:
        # 尝试在max_length位置附近找到合适的分割点
        segment_end = -1
        
        # 按优先级尝试不同的分隔符
        for sep in separators:
            # 在允许范围内寻找最后一个分隔符
            pos = text[:max_length].rfind(sep)
            if pos > 0:  # 找到了分隔符
                segment_end = pos + len(sep)
                break
        
        # 如果没找到任何分隔符，就在词边界处分割
        if segment_end == -1:
            # 寻找最后一个空格
            pos = text[:max_length].rfind(' ')
            if pos > 0:
                segment_end = pos + 1
            else:
                # 实在没有合适位置，就在max_length处强制分割
                segment_end = max_length
        
        # 添加分段并更新剩余文本
        segments.append(text[:segment_end].strip())
        text = text[segment_end:].strip()
    
    # 添加最后一段
    if text:
        segments.append(text)
    
    return segments

# API端点

@app.get("/")
async def root():
    """API根端点"""
    return {
        "message": "IndexTTS 2.0 API Server",
        "version": "2.0.0",
        "endpoints": [
            "/tts - 基础文本转语音（兼容1.0版本）",
            "/tts_v2 - 增强版文本转语音（2.0新功能）",
            "/tts_stream - 流式文本转语音",
            "/upload_audio - 上传音频文件",
            "/speakers - 获取可用说话人列表"
        ]
    }

@app.get("/speakers")
async def get_speakers():
    """获取可用说话人列表"""
    try:
        if not os.path.exists(model.prompt_dir):
            return {"speakers": [], "message": "提示音频目录不存在"}
        
        audio_files = [f for f in os.listdir(model.prompt_dir) if f.endswith(('.wav', '.mp3'))]
        speakers = [os.path.splitext(f)[0] for f in audio_files]
        
        return {
            "speakers": speakers,
            "count": len(speakers),
            "directory": model.prompt_dir
        }
    except Exception as e:
        logger.error(f"Error getting speakers: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/tts")
async def generate_speech_v1(request: Request):
    """基础文本转语音API - 兼容1.0版本"""
    try:
        # 记录请求内容
        body = await request.json()
        logger.info(f"Received /tts request: {body}")
        
        # 解析请求
        try:
            req = TextToSpeechRequest(**body)
            logger.debug(f"Parsed request: {req}")
        except Exception as e:
            logger.error(f"Request parsing error: {e}")
            raise HTTPException(status_code=422, detail=f"Invalid request format: {str(e)}")
        
        # 验证请求参数
        if not req.prompt_speech_path and not req.speaker:
            error_message = "必须提供prompt_speech_path或speaker参数"
            logger.error(f"Parameter validation error: {error_message}")
            raise HTTPException(status_code=400, detail=error_message)
        
        # 生成语音
        try:
            wav_data, sample_rate = model.generate_speech(
                text=req.text,
                prompt_speech_path=req.prompt_speech_path,
                speaker=req.speaker,
                temperature=req.temperature,
                top_k=req.top_k,
                top_p=req.top_p,
                seed=req.seed,
                max_text_tokens_per_segment=req.max_text_tokens_per_sentence,
                max_mel_tokens=req.max_mel_tokens,
                num_beams=req.num_beams,
                length_penalty=req.length_penalty,
                repetition_penalty=req.repetition_penalty,
                emo_control_mode=0  # 兼容模式，使用基础功能
            )
        except ValueError as e:
            logger.error(f"Speech generation error: {e}")
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"Speech generation error: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Error generating speech: {str(e)}")
        
        # 将音频数据写入内存缓冲区
        buffer = io.BytesIO()
        sf.write(buffer, wav_data, sample_rate, format="wav")
        buffer.seek(0)
        
        # 返回音频数据
        logger.info("Successfully generated speech, returning response")
        return Response(
            content=buffer.read(),
            media_type="audio/wav"
        )
    
    except HTTPException:
        # 重新抛出HTTP异常
        raise
    except Exception as e:
        # 打印详细错误信息
        logger.error(f"Unexpected error in /tts endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/tts_v2")
async def generate_speech_v2(request: Request):
    """增强版文本转语音API - 2.0新功能"""
    try:
        # 记录请求内容
        body = await request.json()
        logger.info(f"Received /tts_v2 request: {body}")
        
        # 解析请求
        try:
            req = EnhancedTTSRequest(**body)
            logger.debug(f"Parsed enhanced request: {req}")
        except Exception as e:
            logger.error(f"Request parsing error: {e}")
            raise HTTPException(status_code=422, detail=f"Invalid request format: {str(e)}")
        
        # 验证请求参数
        if not req.prompt_speech_path and not req.speaker:
            error_message = "必须提供prompt_speech_path或speaker参数"
            logger.error(f"Parameter validation error: {error_message}")
            raise HTTPException(status_code=400, detail=error_message)
        
        # 生成语音
        try:
            wav_data, sample_rate = model.generate_speech(
                text=req.text,
                prompt_speech_path=req.prompt_speech_path,
                speaker=req.speaker,
                temperature=req.temperature,
                top_k=req.top_k,
                top_p=req.top_p,
                seed=req.seed,
                max_text_tokens_per_segment=req.max_text_tokens_per_segment,
                max_mel_tokens=req.max_mel_tokens,
                num_beams=req.num_beams,
                length_penalty=req.length_penalty,
                repetition_penalty=req.repetition_penalty,
                do_sample=req.do_sample,
                emo_audio_prompt=req.emo_audio_prompt,
                emo_alpha=req.emo_alpha,
                emo_vector=req.emo_vector,
                use_emo_text=req.use_emo_text,
                emo_text=req.emo_text,
                use_random=req.use_random,
                interval_silence=req.interval_silence,
                emo_control_mode=req.emo_control_mode
            )
        except ValueError as e:
            logger.error(f"Speech generation error: {e}")
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"Speech generation error: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Error generating speech: {str(e)}")
        
        # 将音频数据写入内存缓冲区
        buffer = io.BytesIO()
        sf.write(buffer, wav_data, sample_rate, format="wav")
        buffer.seek(0)
        
        # 返回音频数据
        logger.info("Successfully generated enhanced speech, returning response")
        return Response(
            content=buffer.read(),
            media_type="audio/wav"
        )
    
    except HTTPException:
        # 重新抛出HTTP异常
        raise
    except Exception as e:
        # 打印详细错误信息
        logger.error(f"Unexpected error in /tts_v2 endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/tts_stream")
async def stream_tts(request: Request):
    """流式文本转语音API"""
    try:
        # 记录请求内容
        body = await request.json()
        logger.info(f"Received /tts_stream request: {body}")
        
        # 解析请求
        try:
            req = StreamTTSRequest(**body)
            logger.debug(f"Parsed stream request: {req}")
        except Exception as e:
            logger.error(f"Stream request parsing error: {e}")
            raise HTTPException(status_code=422, detail=f"Invalid request format: {str(e)}")
        
        # 验证请求参数
        if not req.prompt_speech_path and not req.speaker:
            error_message = "必须提供prompt_speech_path或speaker参数"
            logger.error(f"Parameter validation error: {error_message}")
            raise HTTPException(status_code=400, detail=error_message)
        
        # 分割文本
        segments = split_text(req.text, req.max_segment_length)
        logger.info(f"Text split into {len(segments)} segments for streaming")
        
        async def generate_stream():
            for i, segment in enumerate(segments):
                logger.debug(f"Generating segment {i+1}/{len(segments)}")
                # 生成此段的音频
                segment_seed = req.seed + i  # 为每段使用不同的种子以增加变化
                
                try:
                    audio_data = model.generate_speech_segment(
                        text_segment=segment,
                        prompt_speech_path=req.prompt_speech_path,
                        speaker=req.speaker,
                        temperature=req.temperature,
                        top_k=req.top_k,
                        top_p=req.top_p,
                        seed=segment_seed,
                        max_text_tokens_per_segment=req.max_text_tokens_per_segment,
                        max_mel_tokens=req.max_mel_tokens,
                        num_beams=req.num_beams,
                        length_penalty=req.length_penalty,
                        repetition_penalty=req.repetition_penalty,
                        do_sample=req.do_sample,
                        emo_audio_prompt=req.emo_audio_prompt,
                        emo_alpha=req.emo_alpha,
                        emo_vector=req.emo_vector,
                        use_emo_text=req.use_emo_text,
                        emo_text=req.emo_text,
                        use_random=req.use_random,
                        interval_silence=req.interval_silence,
                        emo_control_mode=req.emo_control_mode
                    )
                    
                    # 添加段落索引信息
                    audio_data["segment_index"] = i
                    audio_data["total_segments"] = len(segments)
                    
                    # 将字典转换为JSON并发送
                    yield json.dumps(audio_data) + "\n"
                except Exception as e:
                    logger.error(f"Error generating segment {i}: {e}", exc_info=True)
                    error_data = {
                        "error": str(e),
                        "segment_index": i,
                        "total_segments": len(segments),
                        "text": segment
                    }
                    yield json.dumps(error_data) + "\n"
        
        # 使用StreamingResponse返回流式响应
        logger.info("Starting streaming response")
        return StreamingResponse(
            generate_stream(),
            media_type="application/x-ndjson"  # 使用换行分隔的JSON格式
        )
    
    except HTTPException:
        # 重新抛出HTTP异常
        raise
    except Exception as e:
        # 打印详细错误信息
        logger.error(f"Unexpected error in /tts_stream endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/upload_audio")
async def upload_audio(file: UploadFile = File(...)):
    """
    上传音频文件到 assets 目录
    
    参数:
        file: 上传的音频文件（支持 wav 和 mp3 格式）
        
    返回:
        上传结果信息
    """
    try:
        # 检查文件扩展名
        if not file.filename.lower().endswith(('.wav', '.mp3')):
            raise HTTPException(status_code=400, detail="只支持 WAV 和 MP3 格式的音频文件")
        
        # 确保 assets 目录存在
        os.makedirs(model.prompt_dir, exist_ok=True)
        
        # 构建保存路径
        save_path = os.path.join(model.prompt_dir, file.filename)
        
        # 保存文件
        content = await file.read()
        with open(save_path, "wb") as f:
            f.write(content)
        
        logger.info(f"成功保存音频文件: {save_path}")
        
        return {
            "status": "success",
            "message": "音频文件上传成功",
            "file_path": save_path,
            "speaker_name": os.path.splitext(file.filename)[0]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"上传音频文件失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"上传音频文件失败: {str(e)}")

# 如果直接运行此文件
if __name__ == "__main__":
    import uvicorn
    logger.info("Starting IndexTTS 2.0 API server")
    uvicorn.run(app, host="0.0.0.0", port=8002)


# =============================================================================
# API 使用说明（详细）
# =============================================================================
#
# 一、服务启动
#     python api_server.py
#     默认: http://localhost:8002 ，交互式文档: http://localhost:8002/docs
#
# 二、GET /
#     返回服务信息及端点列表，无请求体。
#
# 三、GET /speakers
#     获取可用说话人列表（来自 assets/speakers 下的 .wav/.mp3 文件名）。
#     响应 JSON: { "speakers": ["name1", ...], "count": N, "directory": "..." }
#
# 四、POST /tts（基础 TTS，兼容 1.0）
#     请求体 JSON 必填: text, 以及 prompt_speech_path 或 speaker 二选一。
#     可选: temperature, top_k, top_p, seed, max_text_tokens_per_sentence,
#          sentences_bucket_max_size, max_mel_tokens, num_beams, length_penalty, repetition_penalty.
#     响应: audio/wav 二进制。
#
#     示例:
#     curl -X POST "http://localhost:8002/tts" \\
#          -H "Content-Type: application/json" \\
#          -d '{"text": "你好，这是IndexTTS 2.0的测试。", "speaker": "Scarlett"}' \\
#          --output output.wav
#
# 五、POST /tts_v2（增强 TTS，支持情感控制）
#     必填: text, 以及 prompt_speech_path 或 speaker 二选一。
#     情感控制: emo_control_mode 取值
#       0 = 与音色参考相同（默认）
#       1 = 使用情感参考音频 emo_audio_prompt，可调 emo_alpha
#       2 = 使用情感向量 emo_vector，8 维 [喜,怒,哀,惧,厌恶,低落,惊喜,平静]，和≤1.5
#       3 = 使用情感文本 use_emo_text=true, emo_text="恐惧" 等
#     其它可选: temperature, top_k, top_p, seed, do_sample, max_text_tokens_per_segment,
#       max_mel_tokens, num_beams, length_penalty, repetition_penalty,
#       use_random, interval_silence 等。
#     响应: audio/wav 二进制。
#
#     示例（情感向量-平静）:
#     curl -X POST "http://localhost:8002/tts_v2" \\
#          -H "Content-Type: application/json" \\
#          -d '{"text": "哇塞！这个效果太棒了！", "speaker": "voice_10", "emo_control_mode": 2, "emo_vector": [0,0,0,0,0,0,0.45,0]}' \\
#          --output output_enhanced.wav
#
#     示例（情感文本）:
#     curl -X POST "http://localhost:8002/tts_v2" \\
#          -H "Content-Type: application/json" \\
#          -d '{"text": "快躲起来！他要来了！", "speaker": "voice_12", "emo_control_mode": 3, "use_emo_text": true, "emo_text": "恐惧"}' \\
#          --output output_fear.wav
#
# 六、POST /tts_stream（流式 TTS）
#     请求体同 /tts_v2，额外可选: max_segment_length（默认 100，按句/逗号等分段）。
#     响应: application/x-ndjson，每行一个 JSON，含 text, audio(采样点列表), sample_rate, segment_index, total_segments；
#      若某段失败则该行含 "error" 字段。
#
#     示例:
#     curl -X POST "http://localhost:8002/tts_stream" \\
#          -H "Content-Type: application/json" \\
#          -d '{"text": "这是一段较长的文本，会被分成多个段落进行流式生成。", "speaker": "voice_01", "max_segment_length": 50}'
#
# 七、POST /upload_audio
#     表单上传: file（WAV 或 MP3）。文件保存到 assets/speakers/，文件名（不含扩展名）可作为 speaker 使用。
#     响应 JSON: { "status": "success", "message": "...", "file_path": "...", "speaker_name": "..." }
#
#     示例:
#     curl -X POST "http://localhost:8002/upload_audio" -F "file=@/path/to/your/audio.wav"
#
# 八、错误码
#     400: 参数错误（如未提供音色、情感向量格式错误等）
#     422: 请求体格式错误（JSON 校验失败）
#     500: 服务端推理或内部错误

