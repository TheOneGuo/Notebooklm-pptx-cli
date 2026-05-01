#!/usr/bin/env python3
"""
NotebookLM MD → PPTX 完整流水线

一键完成：MD文件 → NotebookLM笔记本 → 横版PPT+竖版PPT同时生成 → 图片提取 → Logo遮盖

用法:
    python nb2pptx.py <md_file> [选项]

示例:
    python nb2pptx.py report.md
    python nb2pptx.py report.md --title "我的报告" --pages 40
    python nb2pptx.py report.md --output-dir ~/Desktop/output

流程:
    1. 创建 NotebookLM 笔记本
    2. 上传 MD 文件作为来源
    3. 从来源提取关键信息并重命名笔记本
    4. 生成 PPT 大纲笔记
    5. 笔记转为来源
    6. 并行生成 4 个 PPT（横版PPT1/PPT2 + 竖版PPT3/PPT4）
    7. 下载原始 PPTX 文件
    8. 保存原始 PPTX + 提取图片（images_landscape/ + images_portrait/）
    9. 遮盖 NotebookLM Logo + 绘制免责声明（仅作用于图片）
    10. 清理临时文件
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ═══════════════════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════════════════

# NotebookLM CLI 路径（自动检测）
def find_notebooklm_cli() -> Path:
    """查找 notebooklm CLI 路径"""
    candidates = [
        Path(__file__).parent / ".venv" / "bin" / "notebooklm",
        Path.home() / ".qclaw" / "workspace-agent-ef704e53" / ".venv" / "bin" / "notebooklm",
        Path.home() / ".local" / "bin" / "notebooklm",
        Path("/usr/local/bin/notebooklm"),
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError("未找到 notebooklm CLI，请确保已安装")

# 默认配置
DEFAULT_LOGO_PATH = Path.home() / "Documents" / "前瞻客" / "logo和表情" / "前瞻客logo底图.png"
DEFAULT_OUTPUT_DIR = Path.home() / "Documents" / "A股研报"
DEFAULT_WAIT_CONFIG = {
    "initial_interval": 540,  # 9分钟静默等待
    "max_interval": 60,        # 后续每分钟轮询
    "timeout": 900,            # 15分钟总超时
}

# ═══════════════════════════════════════════════════════════════════════
# CLI 执行工具
# ═══════════════════════════════════════════════════════════════════════

class NotebookLM:
    """NotebookLM CLI 封装"""
    
    def __init__(self, cli_path: Path):
        self.cli = str(cli_path)
    
    def run(self, args: List[str], timeout: int = 30, check: bool = True) -> Dict:
        """执行 CLI 命令，返回 JSON 结果"""
        cmd = [self.cli] + args
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True, 
            timeout=timeout
        )
        
        if check and result.returncode != 0:
            raise RuntimeError(f"命令失败: {' '.join(cmd)}\n{result.stderr}")
        
        # 尝试解析 JSON
        output = result.stdout.strip()
        if output:
            try:
                return json.loads(output)
            except json.JSONDecodeError:
                return {"output": output}
        return {}
    
    # ─── Notebook 操作 ───────────────────────────────────────────────
    
    def create_notebook(self, title: str) -> str:
        """创建笔记本，返回 notebook ID"""
        result = self.run(["notebook", "create", title, "--json"])
        return result.get("id")
    
    def rename_notebook(self, notebook_id: str, new_title: str) -> None:
        """重命名笔记本"""
        self.run(["notebook", "rename", notebook_id, new_title])
    
    def delete_notebook(self, notebook_id: str) -> None:
        """删除笔记本"""
        self.run(["notebook", "delete", notebook_id])
    
    # ─── Source 操作 ─────────────────────────────────────────────────
    
    def add_source_file(self, file_path: Path, notebook_id: str) -> Tuple[str, str]:
        """上传文件作为来源，返回 (source_id, source_title)"""
        result = self.run([
            "source", "add-file", str(file_path), 
            "-n", notebook_id, 
            "--wait", "--json"
        ])
        return result.get("id", ""), result.get("title", file_path.name)
    
    def add_source_text(self, content: str, notebook_id: str, title: str) -> str:
        """添加文本作为来源，返回 source ID"""
        # source add-text 命令格式: TITLE CONTENT [OPTIONS]
        # 注意：content 可能很长，需要小心处理
        result = self.run([
            "source", "add-text", title, content,
            "-n", notebook_id,
            "--wait", "--json"
        ], timeout=120)
        return result.get("id")
    
    def rename_source(self, source_id: str, notebook_id: str, new_title: str) -> None:
        """重命名来源"""
        self.run([
            "source", "rename", source_id, new_title,
            "-n", notebook_id
        ])
    
    # ─── Ask 操作 ────────────────────────────────────────────────────
    
    def ask_and_save(self, question: str, notebook_id: str, note_title: str, source_id: str = None) -> str:
        """提问并保存为笔记，返回 note_id"""
        cmd = [
            "ask", question,
            "-n", notebook_id,
            "--save-as-note",
            "--note-title", note_title,
        ]
        if source_id:
            cmd.extend(["--source", source_id])
        
        # ask --save-as-note 不返回 JSON，使用原始输出
        result = subprocess.run(
            [self.cli] + cmd,
            capture_output=True,
            text=True,
            timeout=180
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"ask 命令失败: {result.stderr}")
        
        # 通过 notes list 找到刚创建的笔记
        notes_result = self.run(["notes", "list", "-n", notebook_id], timeout=30)
        for note in notes_result.get("notes", []):
            if note.get("title") == note_title:
                return note.get("id")
        
        return ""
    
    def get_note_content(self, note_id: str, notebook_id: str) -> str:
        """获取笔记内容"""
        result = self.run(["notes", "get", note_id, "-n", notebook_id, "--json"], timeout=30)
        return result.get("content", "")
    
    # ─── PPT 生成 ────────────────────────────────────────────────────
    
    def generate_slides(
        self,
        source_id: str,
        notebook_id: str,
        instructions: str,
        fmt: str = "detailed_deck",
        wait: bool = False,
    ) -> Dict:
        """提交 PPT 生成任务，返回 NotebookLM CLI 的 JSON 响应。"""
        args = [
            "generate", "slide-deck",
            "--source", source_id,
            "--instructions", instructions,
            "--format", fmt,
            "--wait" if wait else "--no-wait",
            "-n", notebook_id,
            "--json",
        ]
        timeout = 30 if not wait else 900
        return self.run(args, timeout=timeout)

    def wait_for_artifact(
        self,
        task_id: str,
        notebook_id: str,
        initial_interval: float = 2.0,
        max_interval: float = 10.0,
        timeout: float = 300.0,
    ) -> Dict:
        """等待 artifact 任务完成。"""
        return self.run([
            "artifact", "wait", task_id,
            "-n", notebook_id,
            "--initial-interval", str(initial_interval),
            "--max-interval", str(max_interval),
            "--timeout", str(timeout),
            "--json",
        ], timeout=int(timeout) + 30)

    def revise_slide(
        self,
        artifact_id: str,
        slide_index: int,
        prompt: str,
        notebook_id: str,
        wait: bool = True,
    ) -> Dict:
        """请求 NotebookLM 单独重做某一页。"""
        return self.run([
            "generate", "revise-slide",
            artifact_id,
            str(slide_index),
            prompt,
            "-n", notebook_id,
            "--wait" if wait else "--no-wait",
            "--json",
        ], timeout=900 if wait else 30)

    def download_slides(
        self,
        output_path: Path,
        artifact_id: str,
        notebook_id: str,
        fmt: str = "pptx"
    ) -> Path:
        """下载 PPT，返回实际文件路径"""
        result = self.run([
            "download", "slide-deck", str(output_path),
            "--artifact-id", artifact_id,
            "--format", fmt,
            "-n", notebook_id,
            "--json"
        ], timeout=60)

        real_path = Path(result.get("output_path", output_path))
        return real_path

# ═══════════════════════════════════════════════════════════════════════
# PPT 合并工具
# ═══════════════════════════════════════════════════════════════════════

def extract_images_from_pptx(pptx_path: Path, output_dir: Path) -> List[Path]:
    """从 PPTX 提取所有图片（按页顺序）"""
    import zipfile
    import re
    import xml.etree.ElementTree as ET

    output_dir.mkdir(parents=True, exist_ok=True)
    
    NS = {
        'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
        'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
        'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    }
    
    images = []
    
    with zipfile.ZipFile(pptx_path, 'r') as zf:
        # 获取所有 slide 文件
        slide_files = sorted(
            [f for f in zf.namelist() if re.match(r'ppt/slides/slide\d+\.xml$', f)],
            key=lambda x: int(re.search(r'slide(\d+)', x).group(1))
        )
        
        for slide_file in slide_files:
            slide_num = int(re.search(r'slide(\d+)', slide_file).group(1))
            slide_content = zf.read(slide_file)
            
            # 解析 .rels 文件
            rels_file = f"ppt/slides/_rels/slide{slide_num}.xml.rels"
            if rels_file not in zf.namelist():
                continue
            
            rels_content = zf.read(rels_file)
            root = ET.fromstring(rels_content)
            
            # 找到图片映射
            rid_to_target = {}
            ns_rel = {'r': 'http://schemas.openxmlformats.org/package/2006/relationships'}
            for rel in root.findall('.//r:Relationship', ns_rel):
                rid = rel.get('Id')
                target = rel.get('Target')
                if rid and target and 'image' in rel.get('Type', ''):
                    rid_to_target[rid] = target
            
            # 从 slide 中找主图
            slide_root = ET.fromstring(slide_content)
            main_rid = None
            max_size = 0
            
            for pic in slide_root.findall('.//p:pic', NS):
                blip = pic.find('.//a:blip', NS)
                if blip is None:
                    continue
                
                rid = blip.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed')
                if not rid:
                    rid = blip.get('embed')
                if not rid:
                    continue
                
                # 计算图片尺寸
                xfrm = pic.find('.//a:xfrm', NS)
                if xfrm is not None:
                    ext = xfrm.find('a:ext', NS)
                    if ext is not None:
                        try:
                            cx = int(ext.get('cx', '0'))
                            cy = int(ext.get('cy', '0'))
                            size = cx * cy
                            if size > max_size:
                                max_size = size
                                main_rid = rid
                        except (ValueError, TypeError):
                            pass
            
            if not main_rid:
                continue
            
            # 提取图片
            image_path = rid_to_target.get(main_rid)
            if not image_path:
                continue
            
            image_path = image_path.replace('../', '')
            full_path = f"ppt/{image_path}" if not image_path.startswith('ppt/') else image_path
            
            if full_path not in zf.namelist():
                continue
            
            image_data = zf.read(full_path)
            output_path = output_dir / f"P{slide_num}.png"
            
            with open(output_path, 'wb') as f:
                f.write(image_data)
            
            images.append(output_path)
    
    return images

def save_final_pptx_files(raw_pptx_paths: Dict[str, Path], output_dir: Path, notebook_title: str) -> Dict[str, Path]:
    """保存 NotebookLM 原始导出的 PPTX 文件到最终输出目录。"""
    name_map = {
        "landscape_part1": f"{notebook_title}_横版_前半.pptx",
        "landscape_part2": f"{notebook_title}_横版_后半.pptx",
        "portrait_part1": f"{notebook_title}_竖版_前半.pptx",
        "portrait_part2": f"{notebook_title}_竖版_后半.pptx",
    }

    saved_paths = {}
    for key, src in raw_pptx_paths.items():
        if key not in name_map:
            raise KeyError(f"未知的 PPTX 类型: {key}")
        dst = output_dir / name_map[key]
        shutil.copy2(src, dst)
        saved_paths[key] = dst

    return saved_paths


def copy_images_with_expected_count(
    extracted_images: List[Path],
    output_dir: Path,
    start_page: int,
    expected_count: int,
    deck_label: str,
) -> Tuple[List[Path], List[str]]:
    """按预期页数复制图片；若生成过多则仅保留前 expected_count 页并给出警告。"""
    actual_count = len(extracted_images)
    if actual_count < expected_count:
        raise RuntimeError(f"{deck_label} 图片数 {actual_count} < 预期 {expected_count}，丢页中止")

    warnings = []
    if actual_count > expected_count:
        warnings.append(f"{deck_label} 图片数 {actual_count} > 预期 {expected_count}，仅保留前 {expected_count} 页")

    output_paths = []
    for idx, src in enumerate(extracted_images[:expected_count], start=start_page):
        dst = output_dir / f"P{idx}.png"
        shutil.copy2(src, dst)
        output_paths.append(dst)

    return output_paths, warnings


def resolve_artifact_id_from_submission(submission: Dict, artifacts: List[Dict], task_name: str) -> str:
    """优先用 task_id / artifact_id 绑定任务，避免按可见顺序错配。"""
    candidate_ids = [submission.get("artifact_id"), submission.get("task_id")]
    artifact_map = {a.get("id"): a for a in artifacts if a.get("id")}

    for candidate_id in candidate_ids:
        if candidate_id and candidate_id in artifact_map:
            return candidate_id

    visible_artifact = submission.get("visible_artifact") or {}
    visible_id = visible_artifact.get("id")
    if visible_id and visible_id in artifact_map:
        return visible_id

    for candidate_id in candidate_ids:
        if candidate_id:
            return candidate_id

    raise RuntimeError(f"{task_name} 未返回 task_id/artifact_id，无法稳定绑定生成结果")



def validate_portrait_images(
    images_dir: Path,
    expected_pages: int,
    deck_label: str,
    page_numbers: Optional[List[int]] = None,
) -> List[Dict[str, int]]:
    """校验竖版图片是否全部为高大于宽。返回异常页列表。"""
    from PIL import Image

    if page_numbers is None:
        image_paths = sorted(images_dir.glob("P*.png"), key=lambda x: int(x.stem[1:]))
    else:
        image_paths = [images_dir / f"P{page_number}.png" for page_number in page_numbers]

    if len(image_paths) != expected_pages:
        raise RuntimeError(f"{deck_label} 竖版图片数 {len(image_paths)} ≠ 预期 {expected_pages}")

    missing = [path.name for path in image_paths if not path.exists()]
    if missing:
        raise RuntimeError(f"{deck_label} 缺少竖版图片: {', '.join(missing)}")

    problems: List[Dict[str, int]] = []
    for path in image_paths:
        with Image.open(path) as img:
            width, height = img.size
        if height <= width:
            page_number = int(path.stem[1:])
            problems.append({
                "page_number": page_number,
                "width": width,
                "height": height,
            })

    if problems:
        details = ", ".join(
            f"P{item['page_number']}({item['width']}x{item['height']})" for item in problems
        )
        raise RuntimeError(f"竖版页面方向校验失败：{deck_label} 存在横版页 -> {details}")

    return problems



def collect_pending_portrait_rerenders(deck_plan: Dict, images_dir: Path, expected_pages: int) -> List[Dict]:
    """收集需要单页重做的竖版页。"""
    from PIL import Image

    page_numbers = list(range(deck_plan["page_start"], deck_plan["page_end"] + 1))
    if len(page_numbers) != expected_pages:
        raise RuntimeError(
            f"{deck_plan['deck_label']} 页段长度 {len(page_numbers)} ≠ 预期 {expected_pages}"
        )

    image_paths = [images_dir / f"P{page_number}.png" for page_number in page_numbers]
    missing = [path.name for path in image_paths if not path.exists()]
    if missing:
        raise RuntimeError(f"{deck_plan['deck_label']} 缺少竖版图片: {', '.join(missing)}")

    rerenders = []
    for path in image_paths:
        with Image.open(path) as img:
            width, height = img.size
        if height > width:
            continue

        page_number = int(path.stem[1:])
        slide_index = page_number - deck_plan["page_start"]
        rerenders.append({
            "task_id": deck_plan["task_id"],
            "deck_label": deck_plan["deck_label"],
            "artifact_id": deck_plan["artifact_id"],
            "page_number": page_number,
            "slide_index": slide_index,
        })

    return rerenders



def rerender_portrait_slides(
    nb: NotebookLM,
    notebook_id: str,
    deck_plan: Dict,
    rerenders: List[Dict],
    deck_pptx_path: Path,
    images_dir: Path,
    temp_dir: Path,
) -> Path:
    """要求 NotebookLM 对异常竖版页逐页重出，并重新下载整份 deck。"""
    if not rerenders:
        return deck_pptx_path

    for item in rerenders:
        prompt = (
            f"请仅重做第{item['page_number']}页，严格改为竖版 9:16 纵向布局。"
            "页面高度必须明显大于宽度，严禁横版。"
            "请保持该页内容主题、页码顺序、中文文本、黑金/暗黑机械风格与原 deck 其它页面一致。"
        )
        print(
            f"      ↻ 请求 NotebookLM 重做 {item['deck_label']} 的 P{item['page_number']} "
            f"(slide_index={item['slide_index']})..."
        )
        result = nb.revise_slide(
            artifact_id=deck_plan["artifact_id"],
            slide_index=item["slide_index"],
            prompt=prompt,
            notebook_id=notebook_id,
            wait=True,
        )
        status = result.get("status")
        if status not in {"completed", "pending", "processing", None}:
            raise RuntimeError(
                f"{item['deck_label']} 第{item['page_number']}页重做失败: {result}"
            )
        revised_artifact_id = result.get("artifact_id") or result.get("task_id") or deck_plan["artifact_id"]
        deck_plan["artifact_id"] = revised_artifact_id

    refreshed_pptx = nb.download_slides(
        temp_dir / f"{deck_plan['task_id']}_rerendered.pptx",
        deck_plan["artifact_id"],
        notebook_id,
    )

    if deck_pptx_path.exists():
        shutil.copy2(refreshed_pptx, deck_pptx_path)

    refreshed_extract_dir = temp_dir / f"images_{deck_plan['task_id']}_rerendered"
    if refreshed_extract_dir.exists():
        shutil.rmtree(refreshed_extract_dir)
    extracted = extract_images_from_pptx(deck_pptx_path, refreshed_extract_dir)
    copy_images_with_expected_count(
        extracted,
        images_dir,
        start_page=deck_plan["page_start"],
        expected_count=deck_plan["page_end"] - deck_plan["page_start"] + 1,
        deck_label=deck_plan["deck_label"],
    )
    return deck_pptx_path

# ═══════════════════════════════════════════════════════════════════════
# Logo 遮盖工具
# ═══════════════════════════════════════════════════════════════════════

def cover_logo_on_images(
    image_dir: Path, 
    logo_path: Path,
    logo_height: int = 24,
    margin: int = 0
) -> int:
    """
    用前瞻客 logo 遮盖 NotebookLM logo
    
    参数：
        image_dir: 图片目录
        logo_path: 前瞻客 logo 底图路径
        logo_height: logo 显示高度（px），默认 24
        margin: 距边缘边距（px），默认 0
    
    返回：
        成功处理的图片数量
    """
    try:
        from PIL import Image
    except ImportError:
        print("❌ 需要安装 Pillow: pip install Pillow")
        sys.exit(1)
    
    if not logo_path.exists():
        print(f"❌ Logo 文件不存在: {logo_path}")
        return 0
    
    # 加载并缩放 logo
    logo = Image.open(str(logo_path)).convert("RGBA")
    scale = logo_height / logo.height
    new_w = int(logo.width * scale)
    new_h = logo_height
    logo_resized = logo.resize((new_w, new_h), Image.Resampling.LANCZOS)
    
    # 处理所有图片
    images = sorted(image_dir.glob("P*.png"))
    if not images:
        print(f"⚠️ 未找到图片: {image_dir}/P*.png")
        return 0
    
    print(f"🎨 正在遮盖 {len(images)} 张图片的 NotebookLM logo...")
    success = 0
    
    for img_path in images:
        try:
            img = Image.open(str(img_path)).convert("RGBA")
            img_w, img_h = img.size
            
            # 右下角对齐
            pos_x = img_w - new_w - margin
            pos_y = img_h - new_h - margin
            
            # 粘贴 logo
            img.paste(logo_resized, (pos_x, pos_y), logo_resized)
            
            # 保存（转为 RGB 去掉 alpha 通道）
            img.convert("RGB").save(str(img_path), optimize=True)
            success += 1
            
        except Exception as e:
            print(f"   ✗ {img_path.name}: {e}")
    
    print(f"✅ Logo 遮盖完成: {success}/{len(images)}")
    return success

# ═══════════════════════════════════════════════════════════════════════
# 免责声明绘制工具
# ═══════════════════════════════════════════════════════════════════════

def draw_disclaimer(
    image_dir: Path,
    orientation: str = "landscape",
    font_size: int = 11,
    text_color: tuple = (170, 170, 170),
    bg_color: tuple = (30, 30, 30, 180),
    margin: int = 8
) -> int:
    """
    在图片底部绘制标准股市免责声明

    参数：
        image_dir: 图片目录
        orientation: "landscape" (横版) 或 "portrait" (竖版)
        font_size: 字号，默认 11
        text_color: 文字颜色 RGB，默认 #AAAAAA 暗灰
        bg_color: 背景颜色 RGBA，默认半透明深色
        margin: 距底部边距（px），默认 8

    返回：
        成功处理的图片数量
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("❌ 需要安装 Pillow: pip install Pillow")
        return 0

    disclaimer_lines = [
        "市场有风险，决策需独立；",
        "股市有风险，入市需谨慎。"
    ]

    # 查找中文字体
    font = None
    font_paths = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    for fp in font_paths:
        if Path(fp).exists():
            try:
                font = ImageFont.truetype(fp, font_size)
                break
            except Exception:
                continue
    if font is None:
        font = ImageFont.load_default()
        print("   ⚠️ 未找到中文字体，使用默认字体（免责声明可能显示异常）")

    images = sorted(image_dir.glob("P*.png"))
    if not images:
        print(f"⚠️ 未找到图片: {image_dir}/P*.png")
        return 0

    print(f"📝 正在绘制免责声明（{len(images)} 张图片）...")
    success = 0

    for img_path in images:
        try:
            img = Image.open(str(img_path)).convert("RGBA")
            img_w, img_h = img.size
            draw = ImageDraw.Draw(img)

            # 计算文字区域
            line_heights = []
            line_widths = []
            for line in disclaimer_lines:
                bbox = draw.textbbox((0, 0), line, font=font)
                line_widths.append(bbox[2] - bbox[0])
                line_heights.append(bbox[3] - bbox[1])

            text_w = max(line_widths)
            text_h = sum(line_heights) + 4  # 行间距
            line_spacing = 4

            if orientation == "landscape":
                # 横版：右下角对齐
                text_x = img_w - text_w - margin - 10
                text_y = img_h - text_h - margin - 4
            else:
                # 竖版：底部居中
                text_x = (img_w - text_w) // 2
                text_y = img_h - text_h - margin - 4

            # 绘制半透明背景
            pad = 6
            bg_x1 = text_x - pad
            bg_y1 = text_y - pad
            bg_x2 = text_x + text_w + pad
            bg_y2 = text_y + text_h + pad

            # 创建背景遮罩
            bg_overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
            bg_draw = ImageDraw.Draw(bg_overlay)
            bg_draw.rectangle([bg_x1, bg_y1, bg_x2, bg_y2], fill=bg_color)
            img = Image.alpha_composite(img, bg_overlay)
            draw = ImageDraw.Draw(img)

            # 绘制文字
            y_offset = text_y
            for i, line in enumerate(disclaimer_lines):
                if orientation == "landscape":
                    draw.text((text_x, y_offset), line, fill=text_color, font=font)
                else:
                    # 竖版居中
                    line_w = line_widths[i]
                    lx = text_x + (text_w - line_w) // 2
                    draw.text((lx, y_offset), line, fill=text_color, font=font)
                y_offset += line_heights[i] + line_spacing

            img.convert("RGB").save(str(img_path), optimize=True)
            success += 1

        except Exception as e:
            print(f"   ✗ {img_path.name}: {e}")

    print(f"✅ 免责声明绘制完成: {success}/{len(images)}")
    return success


# ═══════════════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════════════

def build_ppt_prompt(orientation: str, page_start: int, page_end: int, is_first_half: bool, total_pages: int) -> str:
    """构建 PPT 生成提示词。"""
    if orientation == "landscape":
        layout_rule = "横版（16:9）。页面宽度大于高度，适合PC端展示和宽屏投影。"
        label = "横版"
    else:
        layout_rule = (
            "必须严格使用竖版（9:16）纵向布局。页面高度明显大于宽度（高宽比约为1.77:1），"
            "适合手机端短视频展示。所有内容必须纵向排列：大标题在页面上方，正文和图表垂直向下展开，"
            "左右留白对称，充分利用竖向空间。严禁使用横版布局。"
        )
        label = "竖版"

    content_verb = "先制作" if is_first_half else "制作"
    style_ref = "来源b的大纲" if is_first_half else "来源b里的大纲"
    consistency = "" if is_first_half else f"，要求和前{page_start - 1}页保持完全一致的风格和语言"

    return f'''[LANGUAGE: CHINESE ONLY - 禁止使用任何英文]

根据来源a的分析内容，按照{style_ref}制作PPT。这份PPT总共包含{total_pages}页。

【强制语言要求】
- 所有页面必须100%使用中文
- 标题、正文、图表标签、页脚、按钮文字必须全部是中文
- 严禁出现任何英文单词或字母
- 如果必须使用专有名词，请用中文翻译

【版式要求】{layout_rule}

【风格要求】采用高端商务黑金/暗黑机械风格。背景使用深邃黑与暗灰色渐变，营造沉浸式暗室感。主体图表（如结构图、流程图）必须呈现 3D 拟物化的哑光红铜/古铜金属材质，避免亮金色。图表边缘需带有亮金色流光特效。整体画面需传达出极度沉稳、权威、严谨与精密的质感。

【免责声明】所有页面底部必须显示以下文字（分两行）：
市场有风险，决策需独立；
股市有风险，入市需谨慎。

【内容要求】要求插图丰富，确保每个中文字不要出错，字体清晰。研报中提到的所有公司名称、股票代码、核心数据必须在PPT中明确体现，不得遗漏。{content_verb}来源b要求的第{page_start}-{page_end}页{consistency}。

【PPT标识】这是{label}PPT，包含第{page_start}-{page_end}页。'''


def check_dependencies() -> List[str]:
    """检查运行依赖，返回缺失项列表"""
    missing = []
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        missing.append("Pillow (pip install Pillow)")
    return missing


def main(
    md_file: Path,
    title: Optional[str] = None,
    pages: int = 30,
    output_dir: Optional[Path] = None,
    logo_path: Optional[Path] = None,
    keep_temp: bool = False,
    wait_config: Optional[Dict] = None,
):
    """
    完整流水线：MD → NotebookLM → PPTX → 图片 → Logo 遮盖
    """
    # ─── 前置检查 ────────────────────────────────────────────────────
    missing = check_dependencies()
    if missing:
        print("❌ 缺少运行依赖:")
        for m in missing:
            print(f"   - {m}")
        sys.exit(1)

    if md_file.stat().st_size == 0:
        print(f"❌ 输入文件为空: {md_file}")
        sys.exit(1)

    # 参数处理
    title = title or md_file.stem
    logo_path = logo_path or DEFAULT_LOGO_PATH
    wait_config = wait_config or DEFAULT_WAIT_CONFIG
    initial_interval = float(wait_config.get("initial_interval", DEFAULT_WAIT_CONFIG["initial_interval"]))
    max_interval = float(wait_config.get("max_interval", DEFAULT_WAIT_CONFIG["max_interval"]))
    timeout = float(wait_config.get("timeout", DEFAULT_WAIT_CONFIG["timeout"]))

    if not logo_path.exists():
        print(f"⚠️ Logo 文件不存在: {logo_path}，将跳过 Logo 遮盖")
        logo_path = None

    print("="*60)
    print(f"📄 输入文件: {md_file} ({md_file.stat().st_size} bytes)")
    print(f"📝 初始标题: {title}")
    print(f"📊 目标页数: {pages}")
    print(f"🎨 Logo: {logo_path or '(跳过)'}")
    print(f"📁 输出目录: {output_dir or '默认'}")
    print("="*60)

    # 初始化
    cli_path = find_notebooklm_cli()
    nb = NotebookLM(cli_path)
    
    notebook_id = None
    temp_dir = None
    notebook_title = title  # 初始化为 title，后续会被步骤3重命名
    run_id = time.strftime("%Y%m%d_%H%M%S")
    run_start = time.time()
    step_times = []  # [(step_name, elapsed_sec)]

    def step_timer(step_name: str):
        """记录上一步耗时并开始新步骤"""
        elapsed = time.time() - run_start
        if step_times:
            prev_name, prev_start = step_times[-1]
            step_elapsed = elapsed - prev_start
            step_times[-1] = (prev_name, step_elapsed)
        step_times.append((step_name, elapsed))
        return elapsed
    
    try:
        # ─── Step 1: 创建笔记本 ───────────────────────────────────────
        step_timer("1.创建笔记本")
        print("\n[1/10] 创建 NotebookLM 笔记本...")
        notebook_id = nb.create_notebook(title)
        if not notebook_id:
            raise RuntimeError("创建笔记本失败：返回空 ID")
        print(f"   ✅ 笔记本 ID: {notebook_id}")

        # ─── Step 2: 上传 MD 作为来源并重命名为 a ────────────────────
        step_timer("2.上传来源")
        print("\n[2/10] 上传 MD 文件作为来源...")
        source_a_id, source_a_title = nb.add_source_file(md_file, notebook_id)
        if not source_a_id:
            raise RuntimeError("上传来源失败：返回空 source ID")
        print(f"   ✅ 来源上传成功: {source_a_title} ({source_a_id})")
        
        # 重命名为 a
        print("   → 重命名为 'a'...")
        nb.rename_source(source_a_id, notebook_id, "a")
        print(f"   ✅ 来源 A: a ({source_a_id})")
        
        # ─── Step 3: 从来源提取关键信息并重命名笔记本 ──────────────────
        step_timer("3.提取主题")
        print("\n[3/10] 从来源提取关键信息并重命名笔记本...")
        extract_prompt = '请从来源 a 中提取报告的核心主题，用一句话概括（不超过20字），仅返回主题名称，不要任何其他内容。不要添加"answer:"前缀。'
        result = nb.run([
            "ask", extract_prompt,
            "-n", notebook_id,
            "--source", source_a_id
        ], timeout=60)
        
        # 从结果中提取标题
        output_text = result.get("output", "").strip()
        if not output_text:
            output_text = str(result).strip()
        
        # 清理输出：去除 "answer:" 或 "answer：" 前缀，以及多余内容
        output_text = output_text.replace("answer:", "").replace("answer：", "").strip()
        
        notebook_title = output_text.split('\n')[0][:20] if output_text else title
        
        # 重命名笔记本
        nb.rename_notebook(notebook_id, notebook_title)
        print(f"   ✅ 笔记本重命名为: {notebook_title}")
        
        # ─── Step 4: 自动生成 PPT 大纲（带风格要求）────────────────────
        step_timer("4.生成大纲")
        print("\n[4/10] 自动生成 PPT 大纲（带风格要求）...")
        
        # 构建提示词（包含详细的风格要求，强制中文）
        prompt = f'''你现在是一位资深的商业咨询顾问，根据来源a的研报内容，精确提炼核心内容生成一份{pages}页的PPT大纲。

【语言要求】所有内容必须使用中文，包括标题、要点、章节名称等。严禁出现英文。

【内容要求】完全按照研报的内容进行设计，每页都要求突出核心重点，主要内容不缺失。研报中提到的所有公司名称、股票代码、核心数据必须在大纲中明确体现，不得遗漏。每页包含：1) 明确的页面标题 2) 3-5个核心要点 3) 逻辑连贯，适合演示。

【风格要求】PPT设计风格采用高端商务黑金/暗黑机械风格。背景使用深邃黑与暗灰色渐变，营造沉浸式暗室感。主体图表必须呈现 3D 拟物化的哑光红铜/古铜金属材质。图表边缘需带有亮金色流光特效。整体画面需传达出极度沉稳、权威、严谨与精密的质感。

【免责声明】所有页面底部必须显示以下文字（分两行）：
市场有风险，决策需独立；
股市有风险，入市需谨慎。'''
        
        note_title = f"{pages}页PPT大纲"
        
        # 使用 ask --save-as-note 生成大纲并保存
        # 注意：生成大纲可能需要 3-5 分钟，设置 300s 超时
        result = nb.run([
            "ask", prompt,
            "-n", notebook_id,
            "--source", source_a_id,
            "--save-as-note",
            "--note-title", note_title
        ], timeout=300)  # 5 分钟超时
        
        print(f"   ✅ 大纲笔记已生成")
        
        # 查找笔记 ID
        notes_result = nb.run(["notes", "list", "-n", notebook_id, "--json"], timeout=30)
        note_id = None
        for note in notes_result.get("notes", []):
            if note.get("title") == note_title:
                note_id = note.get("id")
                break
        
        if not note_id:
            raise RuntimeError(f"未找到笔记：{note_title}")
        
        print(f"   ✅ 笔记 ID: {note_id}")
        
        # ─── Step 5: 笔记转为来源 ───────────────────────────────────
        step_timer("5.笔记转来源")
        print("\n[5/10] 将大纲笔记转为来源 B...")
        # 获取笔记内容
        note_content = nb.get_note_content(note_id, notebook_id)
        if not note_content or len(note_content.strip()) < 50:
            raise RuntimeError(f"笔记内容为空或过短（{len(note_content)} 字符），无法生成 PPT")
        print(f"   📝 笔记内容: {len(note_content)} 字符")

        # 添加为来源
        source_b_id = nb.add_source_text(note_content, notebook_id, note_title)
        if not source_b_id:
            raise RuntimeError("添加来源 B 失败：返回空 source ID")
        # 重命名为 b
        nb.rename_source(source_b_id, notebook_id, "b")
        print(f"   ✅ 来源 B: {source_b_id}")
        
        # ─── Step 6: 并行生成 PPT（横版 PPT1/PPT2 + 竖版 PPT3/PPT4）──────────────────────
        step_timer("6.并行生成PPT")
        print("\n[6/10] 并行生成 PPT（横版+竖版）...")
        pages_per_deck = pages // 2
        
        # 获取生成前的 artifacts 列表（用于排除已存在的）
        artifacts_result = nb.run(["artifact", "list", "-n", notebook_id, "--json"], timeout=30)
        initial_artifacts = artifacts_result.get("artifacts", [])
        initial_artifact_ids = {a.get("id") for a in initial_artifacts}
        print(f"   → 已有 {len(initial_artifacts)} 个 artifacts")
        
        # ═══════════════════════════════════════════════════════════════════
        # PPT 提示词（公共模板 + 4 个任务）
        # ═══════════════════════════════════════════════════════════════════

        task_plans = [
            {
                "task_id": "P1",
                "task_name": "PPT 1（横版前半）",
                "orientation": "landscape",
                "deck_label": "横版前半",
                "page_start": 1,
                "page_end": pages_per_deck,
                "output_temp_name": "ppt_h1.pptx",
                "is_first_half": True,
            },
            {
                "task_id": "P2",
                "task_name": "PPT 2（横版后半）",
                "orientation": "landscape",
                "deck_label": "横版后半",
                "page_start": pages_per_deck + 1,
                "page_end": pages,
                "output_temp_name": "ppt_h2.pptx",
                "is_first_half": False,
            },
            {
                "task_id": "P3",
                "task_name": "PPT 3（竖版前半）",
                "orientation": "portrait",
                "deck_label": "竖版前半",
                "page_start": 1,
                "page_end": pages_per_deck,
                "output_temp_name": "ppt_v1.pptx",
                "is_first_half": True,
            },
            {
                "task_id": "P4",
                "task_name": "PPT 4（竖版后半）",
                "orientation": "portrait",
                "deck_label": "竖版后半",
                "page_start": pages_per_deck + 1,
                "page_end": pages,
                "output_temp_name": "ppt_v2.pptx",
                "is_first_half": False,
            },
        ]

        for plan in task_plans:
            plan["instructions"] = build_ppt_prompt(
                plan["orientation"],
                plan["page_start"],
                plan["page_end"],
                is_first_half=plan["is_first_half"],
                total_pages=pages,
            )

        # ═══════════════════════════════════════════════════════════════════
        # 提交 4 个生成任务，并用 task_id/artifact_id 稳定绑定
        # ═══════════════════════════════════════════════════════════════════

        def submit_and_track(plan: Dict) -> Dict:
            print(f"\n   → 提交 {plan['task_id']} {plan['task_name']} 生成任务...")
            submission = nb.generate_slides(
                source_id=source_b_id,
                notebook_id=notebook_id,
                instructions=plan["instructions"],
                fmt="detailed_deck",
                wait=False,
            )
            print(f"   ↳ 提交结果: task_id={submission.get('task_id')} artifact_id={submission.get('artifact_id')}")
            plan["submission"] = submission
            return submission

        for plan in task_plans:
            submit_and_track(plan)

        print("\n   ⏳ 等待 PPT 生成完成...")
        for plan in task_plans:
            submission = plan["submission"]
            task_id = submission.get("task_id") or submission.get("artifact_id")
            if task_id:
                wait_result = nb.wait_for_artifact(
                    task_id,
                    notebook_id,
                    initial_interval=initial_interval,
                    max_interval=max_interval,
                    timeout=timeout,
                )
                status = wait_result.get("status")
                if status == "failed":
                    raise RuntimeError(f"{plan['task_name']} 生成失败: {wait_result.get('error') or wait_result}")
                if wait_result.get("task_id"):
                    plan["artifact_id"] = wait_result.get("task_id")
            else:
                print(f"   ⚠️ {plan['task_name']} 未返回 task_id，将在 artifact list 中按可见 artifact 兜底确认")

        result = nb.run(["artifact", "list", "-n", notebook_id, "--json"], timeout=30)
        artifacts = result.get("artifacts", [])
        for plan in task_plans:
            plan["artifact_id"] = resolve_artifact_id_from_submission(
                plan["submission"],
                artifacts,
                task_name=plan["task_name"],
            )
            print(f"   ✅ {plan['task_id']} 绑定 artifact: {plan['artifact_id']}")

        print("\n   ✅ 任务与 artifact 绑定结果：")
        for plan in task_plans:
            print(
                f"      - {plan['task_id']}: {plan['task_name']} -> {plan['artifact_id']} "
                f"(页段 {plan['page_start']}-{plan['page_end']})"
            )

        # ─── Step 7: 下载 PPT ─────────────────────────────────────
        step_timer("7.下载PPT")
        print("\n[7/10] 下载 PPT...")

        # 创建临时目录
        temp_dir = Path(tempfile.mkdtemp(prefix="nb2pptx_"))
        print(f"   📂 临时目录: {temp_dir}")

        downloaded_pptx = {}
        for plan in task_plans:
            path = nb.download_slides(
                temp_dir / plan["output_temp_name"],
                plan["artifact_id"],
                notebook_id,
            )
            downloaded_pptx[plan["task_id"]] = path
            plan["pptx_path"] = path
            print(f"   ✅ {plan['task_id']} {plan['task_name']}: {path.name}")

        pptx_h1 = downloaded_pptx["P1"]
        pptx_h2 = downloaded_pptx["P2"]
        pptx_v1 = downloaded_pptx["P3"]
        pptx_v2 = downloaded_pptx["P4"]

        # ─── Step 8: 保存原始 PPTX + 提取图片───────────────────────────
        step_timer("8.保存PPT+图片")
        print("\n[8/10] 保存原始 PPTX 并提取图片...")
        
        # 创建输出目录（尊重 --output-dir 参数）
        final_output_dir = output_dir if output_dir else DEFAULT_OUTPUT_DIR / notebook_title
        final_output_dir.mkdir(parents=True, exist_ok=True)
        print(f"   📁 输出目录: {final_output_dir}")

        final_pptx_files = save_final_pptx_files(
            {
                "landscape_part1": pptx_h1,
                "landscape_part2": pptx_h2,
                "portrait_part1": pptx_v1,
                "portrait_part2": pptx_v2,
            },
            final_output_dir,
            notebook_title,
        )
        print("   📦 已保存原始 PPTX 文件：")
        for key in ["landscape_part1", "landscape_part2", "portrait_part1", "portrait_part2"]:
            print(f"      - {final_pptx_files[key].name}")
        
        # ── 横版处理 ────────────────────────────────────────────────
        print("\n   📐 处理横版 PPT（16:9）...")
        images_dir_h = final_output_dir / "images_landscape"
        images_dir_h.mkdir(exist_ok=True)
        landscape_warnings = []
        
        print("      → 提取 PPT 1（横版前半）图片...")
        images_h1 = extract_images_from_pptx(pptx_h1, temp_dir / "images_h1")
        print(f"      ✅ 提取 {len(images_h1)} 张")
        copied_h1, warnings_h1 = copy_images_with_expected_count(
            images_h1,
            images_dir_h,
            start_page=1,
            expected_count=pages_per_deck,
            deck_label="横版前半",
        )
        landscape_warnings.extend(warnings_h1)
        
        print("      → 提取 PPT 2（横版后半）图片...")
        temp_dir_h2 = temp_dir / "images_h2"
        temp_dir_h2.mkdir(exist_ok=True)
        images_h2 = extract_images_from_pptx(pptx_h2, temp_dir_h2)
        print(f"      ✅ 提取 {len(images_h2)} 张")
        copied_h2, warnings_h2 = copy_images_with_expected_count(
            images_h2,
            images_dir_h,
            start_page=pages_per_deck + 1,
            expected_count=pages - pages_per_deck,
            deck_label="横版后半",
        )
        landscape_warnings.extend(warnings_h2)
        for warning in warnings_h1 + warnings_h2:
            print(f"      ⚠️ {warning}")
        
        # 横版页数校验
        all_images_h = sorted(images_dir_h.glob("P*.png"), key=lambda x: int(x.stem[1:]))
        if len(all_images_h) != pages:
            raise RuntimeError(f"横版图片数 {len(all_images_h)} ≠ 预期 {pages}，丢页中止")
        if logo_path:
            print("      → 遮盖横版 NotebookLM Logo...")
            cover_h = cover_logo_on_images(images_dir_h, logo_path)
            if cover_h != len(all_images_h):
                print(f"   ⚠️ 横版部分图片遮盖失败: {cover_h}/{len(all_images_h)}")
        else:
            print("      ⏭️ 跳过 Logo 遮盖（Logo 文件不存在）")
        print("      → 绘制横版免责声明...")
        draw_disclaimer(images_dir_h, orientation="landscape")
        
        # ── 竖版处理 ────────────────────────────────────────────────
        print("\n   📱 处理竖版 PPT（9:16）...")
        images_dir_v = final_output_dir / "images_portrait"
        images_dir_v.mkdir(exist_ok=True)
        portrait_warnings = []
        
        print("      → 提取 PPT 3（竖版前半）图片...")
        images_v1 = extract_images_from_pptx(pptx_v1, temp_dir / "images_v1")
        print(f"      ✅ 提取 {len(images_v1)} 张")
        copied_v1, warnings_v1 = copy_images_with_expected_count(
            images_v1,
            images_dir_v,
            start_page=1,
            expected_count=pages_per_deck,
            deck_label="竖版前半",
        )
        portrait_warnings.extend(warnings_v1)
        
        print("      → 提取 PPT 4（竖版后半）图片...")
        temp_dir_v2 = temp_dir / "images_v2"
        temp_dir_v2.mkdir(exist_ok=True)
        images_v2 = extract_images_from_pptx(pptx_v2, temp_dir_v2)
        print(f"      ✅ 提取 {len(images_v2)} 张")
        copied_v2, warnings_v2 = copy_images_with_expected_count(
            images_v2,
            images_dir_v,
            start_page=pages_per_deck + 1,
            expected_count=pages - pages_per_deck,
            deck_label="竖版后半",
        )
        portrait_warnings.extend(warnings_v2)
        for warning in warnings_v1 + warnings_v2:
            print(f"      ⚠️ {warning}")
        
        # 竖版逐份校验，并在发现横版页时单页重做后刷新对应原始 PPTX
        portrait_deck_plans = [
            {**task_plans[2], "pptx_output_key": "portrait_part1", "expected_pages": pages_per_deck},
            {**task_plans[3], "pptx_output_key": "portrait_part2", "expected_pages": pages - pages_per_deck},
        ]
        for deck_plan in portrait_deck_plans:
            page_numbers = list(range(deck_plan["page_start"], deck_plan["page_end"] + 1))
            try:
                validate_portrait_images(
                    images_dir_v,
                    expected_pages=deck_plan["expected_pages"],
                    deck_label=deck_plan["task_name"],
                    page_numbers=page_numbers,
                )
            except RuntimeError as exc:
                print(f"      ⚠️ {exc}")
                rerenders = collect_pending_portrait_rerenders(
                    deck_plan,
                    images_dir_v,
                    expected_pages=deck_plan["expected_pages"],
                )
                if not rerenders:
                    raise
                deck_path = rerender_portrait_slides(
                    nb,
                    notebook_id,
                    deck_plan,
                    rerenders,
                    deck_pptx_path=final_pptx_files[deck_plan["pptx_output_key"]],
                    images_dir=images_dir_v,
                    temp_dir=temp_dir,
                )
                final_pptx_files[deck_plan["pptx_output_key"]] = deck_path
                validate_portrait_images(
                    images_dir_v,
                    expected_pages=deck_plan["expected_pages"],
                    deck_label=deck_plan["task_name"],
                    page_numbers=page_numbers,
                )

        # 竖版页数校验
        all_images_v = sorted(images_dir_v.glob("P*.png"), key=lambda x: int(x.stem[1:]))
        if len(all_images_v) != pages:
            raise RuntimeError(f"竖版图片数 {len(all_images_v)} ≠ 预期 {pages}，丢页中止")
        if logo_path:
            print("      → 遮盖竖版 NotebookLM Logo...")
            cover_v = cover_logo_on_images(images_dir_v, logo_path)
            if cover_v != len(all_images_v):
                print(f"   ⚠️ 竖版部分图片遮盖失败: {cover_v}/{len(all_images_v)}")
        else:
            print("      ⏭️ 跳过 Logo 遮盖（Logo 文件不存在）")
        print("      → 绘制竖版免责声明...")
        draw_disclaimer(images_dir_v, orientation="portrait")
        
        # ─── Step 9: Logo 遮盖（已在 Step 8 中完成）────────────────────
        print("\n[9/10] Logo 遮盖与免责声明绘制已完成（仅作用于图片）")
        
        # ─── Step 10: 清理 ──────────────────────────────────────────
        print("\n[10/10] 清理临时文件...")
        
        if not keep_temp and temp_dir and temp_dir.exists():
            shutil.rmtree(temp_dir)
            print(f"   ✅ 删除临时目录: {temp_dir}")
        
        # 删除笔记本
        if notebook_id:
            try:
                nb.delete_notebook(notebook_id)
                print(f"   ✅ 删除笔记本: {notebook_id[:8]}...")
            except Exception as e:
                print(f"   ⚠️ 删除笔记本失败: {e}")
        
        # ─── 页数校验 ───────────────────────────────────────────────────
        h_count = len(all_images_h)
        v_count = len(all_images_v)
        warnings = landscape_warnings + portrait_warnings
        for w in warnings:
            print(f"   ⚠️ {w}")

        # ─── 完成 ───────────────────────────────────────────────────
        step_timer("done")
        total_sec = time.time() - run_start

        print("\n" + "="*60)
        print(f"✅ 流水线完成！（耗时 {total_sec:.0f}s，run_id={run_id}）")
        print("   📦 原始 PPTX:")
        print(f"      - {final_pptx_files['landscape_part1']}")
        print(f"      - {final_pptx_files['landscape_part2']}")
        print(f"      - {final_pptx_files['portrait_part1']}")
        print(f"      - {final_pptx_files['portrait_part2']}")
        print(f"   🖼️  横版图片: {images_dir_h} ({h_count}/{pages} 张)")
        print(f"   🖼️  竖版图片: {images_dir_v} ({v_count}/{pages} 张)")
        if warnings:
            print(f"   ⚠️ 警告: {len(warnings)} 项")
        print("="*60)

        result = {
            "status": "ok" if not warnings else "partial",
            "run_id": run_id,
            "total_seconds": round(total_sec, 1),
            "step_times": {name: round(sec, 1) for name, sec in step_times},
            "pptx_files": {key: str(path) for key, path in final_pptx_files.items()},
            "images_dir_landscape": str(images_dir_h),
            "images_dir_portrait": str(images_dir_v),
            "page_count_landscape": h_count,
            "page_count_portrait": v_count,
            "expected_pages": pages,
            "warnings": warnings,
            "notebook_id": notebook_id,
            "output_dir": str(final_output_dir),
        }

        # 保存运行结果 JSON
        result_file = final_output_dir / "run_result.json"
        result_file.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(f"   📋 运行结果: {result_file}")

        return result
        
    except Exception as e:
        print(f"\n❌ 流水线失败: {e}")
        import traceback
        traceback.print_exc()
        
        # 清理
        if not keep_temp:
            if temp_dir and temp_dir.exists():
                shutil.rmtree(temp_dir)
            if notebook_id:
                try:
                    nb.delete_notebook(notebook_id)
                except:
                    pass
        
        sys.exit(1)

# ═══════════════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="NotebookLM MD → PPTX 完整流水线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    %(prog)s report.md
    %(prog)s report.md --title "我的报告" --pages 40
    %(prog)s report.md --output-dir ~/Desktop/output
    %(prog)s report.md --logo ~/path/to/logo.png
        """
    )
    
    parser.add_argument("md_file", help="Markdown 文件路径")
    parser.add_argument("--title", "-t", help="标题（默认使用文件名）")
    parser.add_argument("--pages", "-p", type=int, default=30, 
                        help="目标页数（默认 30）")
    parser.add_argument("--output-dir", "-o", type=Path,
                        help=f"输出目录（默认 {DEFAULT_OUTPUT_DIR}/<笔记本名称>）")
    parser.add_argument("--logo", "-l", type=Path,
                        help=f"Logo 底图路径（默认 {DEFAULT_LOGO_PATH}）")
    parser.add_argument("--keep-temp", action="store_true",
                        help="保留临时文件（调试用）")
    parser.add_argument("--initial-interval", type=int, default=540,
                        help="初始等待时间/秒（默认 540）")
    parser.add_argument("--max-interval", type=int, default=60,
                        help="轮询间隔/秒（默认 60）")
    parser.add_argument("--timeout", type=int, default=900,
                        help="总超时/秒（默认 900）")
    
    args = parser.parse_args()
    
    # 验证文件
    md_path = Path(args.md_file).expanduser().resolve()
    if not md_path.exists():
        print(f"❌ 文件不存在: {md_path}")
        sys.exit(1)
    
    wait_config = {
        "initial_interval": args.initial_interval,
        "max_interval": args.max_interval,
        "timeout": args.timeout,
    }
    
    result = main(
        md_file=md_path,
        title=args.title,
        pages=args.pages,
        output_dir=args.output_dir,
        logo_path=args.logo,
        keep_temp=args.keep_temp,
        wait_config=wait_config,
    )
