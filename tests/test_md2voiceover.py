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


def test_normalize_video_plan_accepts_chinese_hook_key():
    plan = {
        "report_title": "测试报告",
        "videos": [
            {"title": "V1", "pages": "1-2", "theme": "主题1", "钩子": "钩子1"},
            {"title": "V2", "pages": "3-4", "theme": "主题2", "hook": "钩子2"},
            {"title": "V3", "pages": "5-6", "theme": "主题3"},
        ],
    }

    normalized = md2voiceover.normalize_video_plan(plan, page_count=6)

    assert normalized["report_title"] == "测试报告"
    assert [video["hook"] for video in normalized["videos"]] == ["钩子1", "钩子2", "主题3"]
    assert [video["pages"] for video in normalized["videos"]] == ["1-2", "3-4", "5-6"]


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


def test_generate_all_scripts_accepts_chinese_hook_key(tmp_path, monkeypatch):
    md_path = tmp_path / "report.md"
    md_path.write_text("# 测试报告\n\n第一部分\n\n第二部分\n\n第三部分")

    images_dir = tmp_path / "images_landscape"
    images_dir.mkdir()
    for i in range(1, 4):
        (images_dir / f"P{i}.png").write_bytes(b"png")

    output_dir = tmp_path / "voiceover"

    class FakeGenerator:
        def analyze_md_for_videos(self, md_content, page_count):
            assert page_count == 3
            return {
                "report_title": "测试报告",
                "videos": [
                    {"title": "视频1", "pages": "1-1", "theme": "主题1", "钩子": "钩子1"},
                    {"title": "视频2", "pages": "2-2", "theme": "主题2", "钩子": "钩子2"},
                    {"title": "视频3", "pages": "3-3", "theme": "主题3", "钩子": "钩子3"},
                ],
            }

        def generate_page_script(self, md_content, page_text, page_num, total_pages, video_info, prev_ending=""):
            return f"[PAGE:{page_num}]\\n口播{page_num}"

        def generate_video_opening(self, video_title, video_theme, hook_idea, video_num, prev_video_ending=""):
            return f"开场{video_num}:{hook_idea}"

        def generate_video_ending(self, video_title, video_theme, video_num, is_last=False, next_video_title=""):
            return f"结尾{video_num}"

        def generate_combined_intro(self, report_title, video_titles):
            return "合集开场"

    monkeypatch.setattr(md2voiceover, "MiMoScriptGenerator", FakeGenerator)

    scripts = md2voiceover.generate_all_scripts(md_path, images_dir, output_dir)

    assert scripts["V1-开场.txt"] == "开场1:钩子1"
    assert scripts["V2-开场.txt"] == "开场2:钩子2"
    assert scripts["V3-开场.txt"] == "开场3:钩子3"
    assert (output_dir / "合集-开场.txt").read_text() == "合集开场"
    assert len(list(output_dir.glob("*.txt"))) == 11
