from pathlib import Path
import importlib.util

from PIL import Image
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


def write_png(path: Path, size: tuple[int, int]):
    Image.new("RGB", size, "white").save(path)


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


def test_validate_portrait_images_detects_landscape_pages(tmp_path):
    images_dir = tmp_path / "images_portrait"
    images_dir.mkdir()
    write_png(images_dir / "P1.png", (768, 1376))
    write_png(images_dir / "P2.png", (768, 1376))
    write_png(images_dir / "P3.png", (1376, 768))

    with pytest.raises(RuntimeError, match="竖版页面方向校验失败") as excinfo:
        nb2pptx.validate_portrait_images(images_dir, expected_pages=3, deck_label="竖版前半")

    message = str(excinfo.value)
    assert "P3" in message
    assert "1376x768" in message


def test_resolve_artifact_id_prefers_task_id_over_visible_order():
    submission = {"task_id": "artifact-p2", "artifact_id": "artifact-p2"}
    artifacts = [
        {"id": "artifact-p1", "status": 3},
        {"id": "artifact-p2", "status": 1},
    ]

    artifact_id = nb2pptx.resolve_artifact_id_from_submission(
        submission,
        artifacts,
        task_name="PPT 2（横版后半）",
    )

    assert artifact_id == "artifact-p2"


def test_collect_pending_rerenders_builds_zero_based_slide_requests(tmp_path):
    images_dir = tmp_path / "images_portrait"
    images_dir.mkdir()
    write_png(images_dir / "P1.png", (768, 1376))
    write_png(images_dir / "P2.png", (1376, 768))
    write_png(images_dir / "P3.png", (1376, 768))

    deck_plan = {
        "task_id": "P3",
        "deck_label": "PPT 3（竖版前半）",
        "orientation": "portrait",
        "page_start": 1,
        "page_end": 3,
        "artifact_id": "artifact-p3",
        "instructions": "PROMPT",
    }

    rerenders = nb2pptx.collect_pending_portrait_rerenders(deck_plan, images_dir, expected_pages=3)

    assert rerenders == [
        {
            "task_id": "P3",
            "deck_label": "PPT 3（竖版前半）",
            "artifact_id": "artifact-p3",
            "page_number": 2,
            "slide_index": 1,
        },
        {
            "task_id": "P3",
            "deck_label": "PPT 3（竖版前半）",
            "artifact_id": "artifact-p3",
            "page_number": 3,
            "slide_index": 2,
        },
    ]


def test_rerender_portrait_slides_revises_each_bad_page_and_refreshes_images(tmp_path, monkeypatch):
    images_dir = tmp_path / "images_portrait"
    images_dir.mkdir()
    deck_pptx_path = tmp_path / "deck.pptx"
    deck_pptx_path.write_bytes(b"old")
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()

    deck_plan = {
        "task_id": "P3",
        "deck_label": "PPT 3（竖版前半）",
        "artifact_id": "artifact-p3",
        "page_start": 1,
        "page_end": 3,
    }
    rerenders = [
        {"deck_label": "PPT 3（竖版前半）", "page_number": 2, "slide_index": 1},
        {"deck_label": "PPT 3（竖版前半）", "page_number": 3, "slide_index": 2},
    ]

    revised_calls = []
    download_calls = []
    extract_calls = []
    copy_calls = []

    class FakeNotebook:
        def revise_slide(self, artifact_id, slide_index, prompt, notebook_id, wait=True):
            revised_calls.append({
                "artifact_id": artifact_id,
                "slide_index": slide_index,
                "prompt": prompt,
                "notebook_id": notebook_id,
                "wait": wait,
            })
            return {"status": "completed", "artifact_id": f"artifact-r{slide_index}"}

        def download_slides(self, output_path, artifact_id, notebook_id, fmt="pptx"):
            download_calls.append({
                "output_path": output_path,
                "artifact_id": artifact_id,
                "notebook_id": notebook_id,
                "fmt": fmt,
            })
            output_path.write_bytes(b"new")
            return output_path

    def fake_extract(pptx_path, extract_dir):
        extract_calls.append((pptx_path, extract_dir))
        extract_dir.mkdir(parents=True, exist_ok=True)
        return [extract_dir / "P1.png", extract_dir / "P2.png", extract_dir / "P3.png"]

    def fake_copy(extracted, output_dir, start_page, expected_count, deck_label):
        copy_calls.append({
            "extracted": extracted,
            "output_dir": output_dir,
            "start_page": start_page,
            "expected_count": expected_count,
            "deck_label": deck_label,
        })
        return ([], [])

    monkeypatch.setattr(nb2pptx, "extract_images_from_pptx", fake_extract)
    monkeypatch.setattr(nb2pptx, "copy_images_with_expected_count", fake_copy)

    result_path = nb2pptx.rerender_portrait_slides(
        FakeNotebook(),
        notebook_id="nb-1",
        deck_plan=deck_plan,
        rerenders=rerenders,
        deck_pptx_path=deck_pptx_path,
        images_dir=images_dir,
        temp_dir=temp_dir,
    )

    assert result_path == deck_pptx_path
    assert [call["slide_index"] for call in revised_calls] == [1, 2]
    assert all(call["notebook_id"] == "nb-1" for call in revised_calls)
    assert "第2页" in revised_calls[0]["prompt"]
    assert "第3页" in revised_calls[1]["prompt"]
    assert download_calls[-1]["artifact_id"] == "artifact-r2"
    assert deck_plan["artifact_id"] == "artifact-r2"
    assert extract_calls[0][0] == deck_pptx_path
    assert copy_calls[0]["start_page"] == 1
    assert copy_calls[0]["expected_count"] == 3
    assert copy_calls[0]["deck_label"] == "PPT 3（竖版前半）"


def test_main_uses_wait_config_and_syncs_rerendered_portrait_pptx(tmp_path, monkeypatch):
    md_file = tmp_path / "input.md"
    md_file.write_text("# 报告\n\n内容", encoding="utf-8")
    logo_path = tmp_path / "logo.png"
    write_png(logo_path, (120, 40))
    output_dir = tmp_path / "out"

    wait_calls = []
    rerender_calls = []
    validation_calls = []
    generate_counter = {"value": 0}

    class FakeNotebook:
        def __init__(self, cli_path):
            self.cli_path = cli_path

        def create_notebook(self, title):
            return "nb-1"

        def add_source_file(self, md_path, notebook_id):
            return "source-a", md_path.stem

        def rename_source(self, source_id, notebook_id, new_name):
            return None

        def run(self, args, timeout=30, check=True):
            if args[:1] == ["ask"] and "--save-as-note" not in args:
                return {"output": "测试报告"}
            if args[:1] == ["ask"] and "--save-as-note" in args:
                return {"output": "ok"}
            if args[:2] == ["notes", "list"]:
                return {"notes": [{"title": "4页PPT大纲", "id": "note-1"}]}
            if args[:2] == ["artifact", "list"]:
                return {
                    "artifacts": [
                        {"id": "artifact-p1", "status": 3},
                        {"id": "artifact-p2", "status": 3},
                        {"id": "artifact-p3", "status": 3},
                        {"id": "artifact-p4", "status": 3},
                    ]
                }
            raise AssertionError(f"unexpected run args: {args}")

        def rename_notebook(self, notebook_id, title):
            return None

        def get_note_content(self, note_id, notebook_id):
            return "大纲内容" * 30

        def add_source_text(self, note_content, notebook_id, note_title):
            return "source-b"

        def generate_slides(self, source_id, notebook_id, instructions, fmt="detailed_deck", wait=False):
            generate_counter["value"] += 1
            artifact_id = f"artifact-p{generate_counter['value']}"
            return {"task_id": artifact_id, "artifact_id": artifact_id}

        def wait_for_artifact(self, task_id, notebook_id, initial_interval=2.0, max_interval=10.0, timeout=300.0):
            wait_calls.append(
                {
                    "task_id": task_id,
                    "notebook_id": notebook_id,
                    "initial_interval": initial_interval,
                    "max_interval": max_interval,
                    "timeout": timeout,
                }
            )
            return {"status": "completed", "task_id": task_id}

        def download_slides(self, output_path, artifact_id, notebook_id, fmt="pptx"):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(artifact_id.encode("utf-8"))
            return output_path

        def delete_notebook(self, notebook_id):
            return None

    def fake_extract(pptx_path, extract_dir):
        extract_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for idx in range(1, 3):
            path = extract_dir / f"P{idx}.png"
            write_png(path, (768, 1376))
            paths.append(path)
        return paths

    validation_failures = {"PPT 3（竖版前半）": 1}

    def fake_validate(images_dir, expected_pages, deck_label, page_numbers=None):
        validation_calls.append(
            {
                "deck_label": deck_label,
                "expected_pages": expected_pages,
                "page_numbers": page_numbers,
            }
        )
        if validation_failures.get(deck_label, 0):
            validation_failures[deck_label] -= 1
            raise RuntimeError(f"竖版页面方向校验失败：{deck_label} 存在横版页 -> P2(1376x768)")
        return []

    def fake_collect(deck_plan, images_dir, expected_pages):
        if deck_plan["task_id"] == "P3":
            return [{"deck_label": deck_plan["task_name"], "page_number": 2, "slide_index": 1}]
        return []

    def fake_rerender(nb, notebook_id, deck_plan, rerenders, deck_pptx_path, images_dir, temp_dir):
        rerender_calls.append(
            {
                "task_id": deck_plan["task_id"],
                "artifact_id": deck_plan["artifact_id"],
                "rerenders": rerenders,
            }
        )
        deck_plan["artifact_id"] = "artifact-rerendered"
        deck_pptx_path.write_bytes(b"rerendered")
        return deck_pptx_path

    monkeypatch.setattr(nb2pptx, "find_notebooklm_cli", lambda: Path("/fake/notebooklm"))
    monkeypatch.setattr(nb2pptx, "NotebookLM", FakeNotebook)
    monkeypatch.setattr(nb2pptx, "extract_images_from_pptx", fake_extract)
    monkeypatch.setattr(nb2pptx, "validate_portrait_images", fake_validate)
    monkeypatch.setattr(nb2pptx, "collect_pending_portrait_rerenders", fake_collect)
    monkeypatch.setattr(nb2pptx, "rerender_portrait_slides", fake_rerender)
    monkeypatch.setattr(nb2pptx, "cover_logo_on_images", lambda *args, **kwargs: 4)
    monkeypatch.setattr(nb2pptx, "draw_disclaimer", lambda *args, **kwargs: 4)

    result = nb2pptx.main(
        md_file=md_file,
        title="测试报告",
        pages=4,
        output_dir=output_dir,
        logo_path=logo_path,
        keep_temp=True,
        wait_config={"initial_interval": 9, "max_interval": 7, "timeout": 99},
    )

    assert [call["initial_interval"] for call in wait_calls] == [9, 9, 9, 9]
    assert [call["max_interval"] for call in wait_calls] == [7, 7, 7, 7]
    assert [call["timeout"] for call in wait_calls] == [99, 99, 99, 99]
    assert rerender_calls == [
        {
            "task_id": "P3",
            "artifact_id": "artifact-p3",
            "rerenders": [{"deck_label": "PPT 3（竖版前半）", "page_number": 2, "slide_index": 1}],
        }
    ]
    assert any(call["deck_label"] == "PPT 3（竖版前半）" for call in validation_calls)
    assert (output_dir / "测试报告_竖版_前半.pptx").read_bytes() == b"rerendered"
    assert result["pptx_files"]["portrait_part1"].endswith("测试报告_竖版_前半.pptx")
