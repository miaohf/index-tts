import io
import json
import logging

import soundfile as sf
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from api.inference import model
from api.schemas import EnhancedTTSRequest, StreamTTSRequest, TextToSpeechRequest
from api.text_segment import split_text

logger = logging.getLogger("indextts2-api")

router = APIRouter(tags=["tts"])


@router.post("/tts")
async def generate_speech_v1(request: Request):
    try:
        body = await request.json()
        logger.info(f"Received /tts request: {body}")
        try:
            req = TextToSpeechRequest(**body)
        except Exception as e:
            logger.error(f"Request parsing error: {e}")
            raise HTTPException(status_code=422, detail=f"Invalid request format: {str(e)}")

        if not req.prompt_speech_path and not req.speaker:
            raise HTTPException(status_code=400, detail="必须提供prompt_speech_path或speaker参数")

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
                emo_control_mode=0,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"Speech generation error: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Error generating speech: {str(e)}")

        buffer = io.BytesIO()
        sf.write(buffer, wav_data, sample_rate, format="wav")
        buffer.seek(0)
        return Response(content=buffer.read(), media_type="audio/wav")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in /tts endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tts_v2")
async def generate_speech_v2(request: Request):
    try:
        body = await request.json()
        logger.info(f"Received /tts_v2 request: {body}")
        try:
            req = EnhancedTTSRequest(**body)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Invalid request format: {str(e)}")

        if not req.prompt_speech_path and not req.speaker:
            raise HTTPException(status_code=400, detail="必须提供prompt_speech_path或speaker参数")

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
                emo_control_mode=req.emo_control_mode,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"Speech generation error: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Error generating speech: {str(e)}")

        buffer = io.BytesIO()
        sf.write(buffer, wav_data, sample_rate, format="wav")
        buffer.seek(0)
        return Response(content=buffer.read(), media_type="audio/wav")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in /tts_v2 endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tts_stream")
async def stream_tts(request: Request):
    try:
        body = await request.json()
        logger.info(f"Received /tts_stream request: {body}")
        try:
            req = StreamTTSRequest(**body)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Invalid request format: {str(e)}")

        if not req.prompt_speech_path and not req.speaker:
            raise HTTPException(status_code=400, detail="必须提供prompt_speech_path或speaker参数")

        segments = split_text(req.text, req.max_segment_length)
        logger.info(f"Text split into {len(segments)} segments for streaming")

        async def generate_stream():
            for i, segment in enumerate(segments):
                segment_seed = req.seed + i
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
                        emo_control_mode=req.emo_control_mode,
                    )
                    audio_data["segment_index"] = i
                    audio_data["total_segments"] = len(segments)
                    yield json.dumps(audio_data) + "\n"
                except Exception as e:
                    logger.error(f"Error generating segment {i}: {e}", exc_info=True)
                    yield json.dumps(
                        {
                            "error": str(e),
                            "segment_index": i,
                            "total_segments": len(segments),
                            "text": segment,
                        }
                    ) + "\n"

        return StreamingResponse(generate_stream(), media_type="application/x-ndjson")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in /tts_stream endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
