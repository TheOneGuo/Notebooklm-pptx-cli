from pathlib import Path
import importlib.util


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
