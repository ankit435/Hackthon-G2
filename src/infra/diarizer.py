from domain.errors import DiarizationError
from domain.models import DecodedAudio, SpeakerTurn


class PyannoteDiarizer:
    """pyannote/speaker-diarization-3.1 (gated). The audio is passed in memory, so pyannote never decodes files."""

    def __init__(self, model_name: str, hf_token: str | None) -> None:
        if not hf_token:
            raise DiarizationError("HF_TOKEN is required for the gated pyannote model (SETUP.md step 4)", stage="diarize")
        from pyannote.audio import Pipeline

        try:
            self._pipeline = Pipeline.from_pretrained(model_name, token=hf_token)
        except Exception as e:
            raise DiarizationError("could not load diarization pipeline; check gated access on both pyannote repos",
                                   stage="diarize", model=model_name, error=type(e).__name__) from e
        if self._pipeline is None:
            raise DiarizationError("pipeline load returned None (gated access?)", stage="diarize", model=model_name)

    def diarize(self, audio: DecodedAudio, num_speakers: int) -> list[SpeakerTurn]:
        import torch

        try:
            output = self._pipeline({"waveform": torch.from_numpy(audio.samples).unsqueeze(0),
                                     "sample_rate": audio.sample_rate}, num_speakers=num_speakers)
        except Exception as e:
            raise DiarizationError("diarization failed", stage="diarize", file=str(audio.path), error=type(e).__name__) from e
        # pyannote.audio 4 wraps the result; 3.x returned the Annotation directly.
        annotation = getattr(output, "speaker_diarization", output)
        return [SpeakerTurn(start=seg.start, end=seg.end, speaker=str(label))
                for seg, _track, label in annotation.itertracks(yield_label=True)]
