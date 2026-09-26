from pathlib import Path

from domain.errors import AudioDecodeError
from domain.models import DecodedAudio

# Both Whisper and pyannote operate on 16 kHz mono; decoding once at that rate means neither
# model resamples, and only one FFmpeg build (torchcodec's) ever touches the file.
TARGET_SAMPLE_RATE = 16_000


class TorchcodecDecoder:
    def decode(self, path: Path) -> DecodedAudio:
        from torchcodec.decoders import AudioDecoder

        try:
            samples = AudioDecoder(str(path), sample_rate=TARGET_SAMPLE_RATE, num_channels=1).get_all_samples()
        except Exception as e:
            raise AudioDecodeError("could not decode audio", stage="decode", file=str(path), error=type(e).__name__) from e
        mono = samples.data[0].numpy()
        if mono.size == 0:
            raise AudioDecodeError("audio has no samples", stage="decode", file=str(path))
        return DecodedAudio(path=path, samples=mono, sample_rate=samples.sample_rate)
