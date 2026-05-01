from pathlib import Path
import importlib.util
import math
import wave
import struct


def load_module(module_name: str, relative_path: str):
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


md2voiceover = load_module("md2voiceover", "scripts/md2voiceover.py")


def write_mono_wav(path: Path, seconds: float = 1.0, sample_rate: int = 16000):
    frames = int(seconds * sample_rate)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        for i in range(frames):
            sample = int(32767 * math.sin(2 * math.pi * 440 * (i / sample_rate)))
            wav_file.writeframes(struct.pack("<h", sample))


def test_speed_up_audio_outputs_stereo_wav(tmp_path):
    input_wav = tmp_path / "input.wav"
    output_wav = tmp_path / "output.wav"
    write_mono_wav(input_wav)

    assert md2voiceover.speed_up_audio(input_wav, output_wav, speed=1.5) is True
    assert output_wav.exists()

    with wave.open(str(input_wav), "rb") as original:
        original_duration = original.getnframes() / original.getframerate()

    with wave.open(str(output_wav), "rb") as processed:
        processed_duration = processed.getnframes() / processed.getframerate()
        assert processed.getnchannels() == 2
        assert processed_duration < original_duration
