from domain.errors import TranscriptionError
from domain.models import DecodedAudio, TranscriptSegment
from infra.audio import TARGET_SAMPLE_RATE


class FasterWhisperTranscriber:
    """Whisper via faster-whisper, local, CPU int8. Deterministic: the same file always gives the same transcript.

    - temperature=0.0 (greedy/beam only). Whisper's default temperature fallback was measured
      in Session 1 and rejected: seeding CTranslate2 did not make it reproducible, and on
      audio_02 it replaced a detectable repetition loop with an undetectable invented sentence.
    - condition_on_previous_text=False: each 30 s window is decoded without the previous
      window's text as a prompt. That feedback is what let a repetition loop run for 126
      words at the end of audio_02 (PROGRESS.md Decisions Log).
    - language="en" is a dataset fact (all conversations are English); it skips detection.
    """

    def __init__(self, model_name: str, device: str = "cpu", compute_type: str = "int8") -> None:
        from faster_whisper import WhisperModel

        self._model = WhisperModel(model_name, device=device, compute_type=compute_type)

    def transcribe(self, audio: DecodedAudio) -> list[TranscriptSegment]:
        if audio.sample_rate != TARGET_SAMPLE_RATE:
            raise TranscriptionError("expected 16 kHz audio", stage="transcribe", sample_rate=audio.sample_rate)
        try:
            segments, _info = self._model.transcribe(audio.samples, language="en", beam_size=5, temperature=0.0,
                                                     condition_on_previous_text=False)
            return [TranscriptSegment(start=s.start, end=s.end, text=s.text) for s in segments]
        except Exception as e:
            raise TranscriptionError("whisper failed", stage="transcribe", file=str(audio.path), error=type(e).__name__) from e
