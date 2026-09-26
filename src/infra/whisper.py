from domain.errors import TranscriptionError
from domain.models import DecodedAudio, Transcript, TranscriptSegment, Word
from infra.audio import TARGET_SAMPLE_RATE


def _supported_languages() -> frozenset[str]:
    # faster-whisper keeps its language list private; wrap it once so settings can validate against it
    from faster_whisper.tokenizer import _LANGUAGE_CODES

    return frozenset(_LANGUAGE_CODES)


SUPPORTED_LANGUAGES = _supported_languages()


class FasterWhisperTranscriber:
    """Whisper via faster-whisper, local, CPU int8. Deterministic: the same file always gives the same transcript.

    - temperature=0.0 (greedy/beam only). Whisper's default temperature fallback was measured
      in Session 1 and rejected: seeding CTranslate2 did not make it reproducible, and on
      audio_02 it replaced a detectable repetition loop with an undetectable invented sentence.
    - condition_on_previous_text=False: each 30 s window is decoded without the previous
      window's text as a prompt. That feedback is what let a repetition loop run for 126
      words at the end of audio_02 (PROGRESS.md Decisions Log).
    - word_timestamps=True: segments without the prompt can run across a speaker change, so
      alignment works per word and cuts segments at speaker changes (application.alignment).
    - language is auto-detected unless forced by settings. Detection uses the first 30 s, so
      there is one language per file (PLAN.md §7B).
    """

    def __init__(self, model_name: str, language: str | None = None, device: str = "cpu",
                 compute_type: str = "int8") -> None:
        from faster_whisper import WhisperModel

        if language is not None and language not in SUPPORTED_LANGUAGES:
            raise TranscriptionError("unsupported forced language", stage="transcribe", language=language)
        self._language = language
        self._model = WhisperModel(model_name, device=device, compute_type=compute_type)

    def transcribe(self, audio: DecodedAudio) -> Transcript:
        if audio.sample_rate != TARGET_SAMPLE_RATE:
            raise TranscriptionError("expected 16 kHz audio", stage="transcribe", sample_rate=audio.sample_rate)
        try:
            segments, info = self._model.transcribe(audio.samples, language=self._language, beam_size=5,
                                                    temperature=0.0, condition_on_previous_text=False,
                                                    word_timestamps=True)
            return Transcript(
                segments=[TranscriptSegment(start=s.start, end=s.end, text=s.text,
                                            words=tuple(Word(w.start, w.end, w.word) for w in (s.words or ())))
                          for s in segments],
                language=info.language, language_probability=float(info.language_probability))
        except Exception as e:
            raise TranscriptionError("whisper failed", stage="transcribe", file=str(audio.path), error=type(e).__name__) from e
