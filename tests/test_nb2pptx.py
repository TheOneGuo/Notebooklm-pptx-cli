from pathlib import Path
import importlib.util

import pytest


def load_module(module_name: str, relative_path: str):
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


nb2pptx = load_module("nb2pptx", "scripts/nb2pptx.py")


def test_save_final_pptx_files_copies_raw_notebooklm_exports(tmp_path):
    raw_files = {}
    for key in ["landscape_part1", "landscape_part2", "portrait_part1", "portrait_part2"]:
        src = tmp_path / f"{key}.pptx"
        src.write_bytes(f"raw-{key}".encode("utf-8"))
        raw_files[key] = src

    output_dir = tmp_path / "output"
    output_dir.mkdir()

    saved = nb2pptx.save_final_pptx_files(raw_files, output_dir, "测试报告")

    assert saved["landscape_part1"] == output_dir / "测试报告_横版_前半.pptx"
    assert saved["landscape_part2"] == output_dir / "测试报告_横版_后半.pptx"
    assert saved["portrait_part1"] == output_dir / "测试报告_竖版_前半.pptx"
    assert saved["portrait_part2"] == output_dir / "测试报告_竖版_后半.pptx"

    for key, path in saved.items():
        assert path.exists()
        assert path.read_bytes() == raw_files[key].read_bytes()


def test_copy_images_with_expected_count_trims_extra_pages(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    extracted = []
    for idx in range(1, 7):
        path = src_dir / f"P{idx}.png"
        path.write_bytes(f"img-{idx}".encode("utf-8"))
        extracted.append(path)

    output_dir = tmp_path / "output"
    output_dir.mkdir()

    copied, warnings = nb2pptx.copy_images_with_expected_count(
        extracted,
        output_dir,
        start_page=4,
        expected_count=3,
        deck_label="竖版后半",
    )

    assert [path.name for path in copied] == ["P4.png", "P5.png", "P6.png"]
    assert [path.read_bytes() for path in copied] == [b"img-1", b"img-2", b"img-3"]
    assert warnings == ["竖版后半 图片数 6 > 预期 3，仅保留前 3 页"]


def test_copy_images_with_expected_count_raises_when_under_generated(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    extracted = []
    for idx in range(1, 3):
        path = src_dir / f"P{idx}.png"
        path.write_bytes(f"img-{idx}".encode("utf-8"))
        extracted.append(path)

    output_dir = tmp_path / "output"
    output_dir.mkdir()

    with pytest.raises(RuntimeError, match="竖版后半 图片数 2 < 预期 3"):
        nb2pptx.copy_images_with_expected_count(
            extracted,
            output_dir,
            start_page=4,
            expected_count=3,
            deck_label="竖版后半",
        )
