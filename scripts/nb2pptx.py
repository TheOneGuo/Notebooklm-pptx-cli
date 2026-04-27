#!/usr/bin/env python3
"""
NotebookLM MD → PPTX 完整流水线

一键完成：MD文件 → NotebookLM笔记本 → PPT生成 → 图片提取 → Logo遮盖

用法:
    python nb2pptx.py <md_file> [选项]

示例:
    python nb2pptx.py report.md
    python nb2pptx.py report.md --title "我的报告" --pages 40
    python nb2pptx.py report.md --output-dir ~/Desktop/output

流程:
    1. 创建 NotebookLM 笔记本
    2. 上传 MD 文件作为来源（重命名为 a）
    3. 从来源提取关键信息并重命名笔记本
    4. 生成 PPT 大纲笔记（带风格要求，强制中文）
    5. 笔记转为来源（重命名为 b）
    6. 并行生成四个 PPT（横版 PPT1/PPT2 + 竖版 PPT4/PPT5）
    7. 等待并下载 PPTX
    8. 分别合并横版和竖版 PPTX
    9. 分别遮盖 NotebookLM Logo
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
        Path(__file__).parent.parent.parent.parent.parent / ".qclaw" / "workspace-agent-ef704e53" / ".venv" / "bin" / "notebooklm",
        Path.home() / ".qclaw" / "workspace-agent-ef704e53" / ".venv" / "bin" / "notebooklm",
        Path.home() / ".local" / "bin" / "notebooklm",
        Path("/usr/local/bin/notebooklm"),
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError("未找到 notebooklm CLI，请确保已安装")

# 默认配置
SKILL_DIR = Path(__file__).parent.parent
DEFAULT_LOGO_PATH = SKILL_DIR / "assets" / "logo.png"
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
        """添加文本作为来源，返回 source ID

        注意:
        - CLI 直接传参支持大部分场景
        - 但超长内容或特殊字符可能导致 RPC 错误
        - 策略：内容过长（>30000字符）或失败时，写入临时文件后用 add-file
        """
        # 尝试直接传参
        if len(content) <= 30000:
            try:
                result = self.run([
                    "source", "add-text", title, content,
                    "-n", notebook_id,
                    "--wait", "--json"
                ], timeout=120)
                return result.get("id")
            except RuntimeError as e:
                if "RPC" in str(e) or "SourceAddError" in str(e):
                    print(f"   ⚠️ 直接传参失败，尝试临时文件方式...")
                else:
                    raise

        # 回退到临时文件方式
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8') as f:
            f.write(content)
            temp_path = Path(f.name)

        try:
            result = self.run([
                "source", "add-file", str(temp_path),
                "-n", notebook_id,
                "--wait", "--json"
            ], timeout=120)
            # 重命名来源
            source_id = result.get("id")
            if source_id:
                self.rename_source(source_id, notebook_id, title)
            return source_id
        finally:
            temp_path.unlink(missing_ok=True)

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
            timeout=300
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
        fmt: str = "detailed_deck"
    ) -> str:
        """生成 PPT（不等待），返回 task ID"""
        result = self.run([
            "generate", "slide-deck",
            "--source", source_id,
            "--instructions", instructions,
            "--format", fmt,
            "--no-wait",
            "-n", notebook_id,
            "--json"
        ], timeout=30)
        return result.get("task_id")

    def wait_for_artifact(
        self,
        task_id: str,
        notebook_id: str,
        initial_interval: int = 540,
        max_interval: int = 60,
        timeout: int = 900
    ) -> bool:
        """等待 artifact 生成完成（手动轮询，避免 artifact wait 超时）"""
        print(f"⏳ 等待生成完成（初始静默{initial_interval}s，后续每{max_interval}s轮询）...")

        # 状态码映射
        STATUS_MAP = {0: "pending", 1: "processing", 2: "ready", 3: "completed", 4: "failed"}

        start_time = time.time()

        # 初始静默等待
        if initial_interval > 0:
            print(f"   → 初始静默等待 {initial_interval}s...")
            time.sleep(initial_interval)

        # 轮询
        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout:
                print(f"❌ 超时（{timeout}s）")
                return False

            # 查询 artifact 列表
            try:
                result = self.run([
                    "artifact", "list",
                    "-n", notebook_id,
                    "--json"
                ], timeout=30)

                artifacts = result.get("artifacts", [])
                target = None
                for a in artifacts:
                    if a.get("id") == task_id or a.get("task_id") == task_id:
                        target = a
                        break

                if target:
                    status_code = target.get("status", 0)
                    status_str = STATUS_MAP.get(status_code, f"unknown({status_code})")
                    print(f"   → 状态: {status_str} (已等待 {int(elapsed)}s)")

                    if status_code == 3:  # completed
                        print("✅ 生成完成！")
                        return True
                    elif status_code == 4:  # failed
                        print(f"❌ 生成失败")
                        return False
                else:
                    print(f"   → 未找到 artifact，继续等待...")

            except Exception as e:
                print(f"   ⚠️ 查询失败: {e}")

            # 等待下一轮
            time.sleep(max_interval)

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
            "--format", "pptx",
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

def create_pptx_from_images(images: List[Path], output_path: Path, aspect_ratio: str = "16:9") -> None:
    """从图片创建 PPTX，支持 16:9 和 9:16 两种比例"""
    try:
        from pptx import Presentation
        from pptx.util import Inches
    except ImportError:
        print("❌ 需要安装 python-pptx: pip install python-pptx")
        sys.exit(1)

    prs = Presentation()

    if aspect_ratio == "9:16":
        # 9:16 竖屏比例（宽:高 = 9:16）
        prs.slide_width = Inches(5.625)
        prs.slide_height = Inches(10.0)
    else:
        # 默认 16:9 横屏比例
        prs.slide_width = Inches(13.333)
        prs.slide_height = Inches(7.5)

    blank_layout = prs.slide_layouts[6]  # 空白布局

    for i, img_path in enumerate(images, 1):
        slide = prs.slides.add_slide(blank_layout)
        # 添加图片，占满整张幻灯片
        slide.shapes.add_picture(
            str(img_path),
            Inches(0), Inches(0),
            width=prs.slide_width,
            height=prs.slide_height
        )
        print(f"   ✓ 第{i}页: {img_path.name}")

    prs.save(str(output_path))
    print(f"✅ PPTX 创建完成: {output_path} ({aspect_ratio})")

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

    采用右下角动态对齐策略，根据每张图片的实际尺寸自适应放置，
    避免固定坐标在不同尺寸 PPT 中错位的问题。

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

            # 右下角动态对齐
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

def find_chinese_font(size: int = 14):
    """查找系统中可用的中文字体"""
    font_candidates = [
        # macOS
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/Library/Arial Unicode.ttf",
        # Linux
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    ]
    for font_path in font_candidates:
        if os.path.exists(font_path):
            try:
                from PIL import ImageFont
                return ImageFont.truetype(font_path, size)
            except Exception:
                continue
    # 回退到默认字体
    try:
        from PIL import ImageFont
        return ImageFont.load_default()
    except Exception:
        return None


def draw_disclaimer(
    image_dir: Path,
    aspect_ratio: str = "16:9",
    font_size: int = 14,
    text_color: tuple = (170, 170, 170),   # #AAAAAA 暗灰
    margin_bottom: int = 12,
    margin_side: int = 16,
) -> int:
    """
    在每张图片的固定位置绘制标准免责声明文字（代码级硬保障）

    无论 NotebookLM 是否在生成时放置了免责声明，此函数确保最终输出
    的每张图片底部都有统一格式、统一位置的标准免责声明。

    参数：
        image_dir: 图片目录
        aspect_ratio: "16:9" 或 "9:16"，决定文字位置策略
        font_size: 字号（px），默认 14
        text_color: 文字颜色 RGB 元组，默认暗灰 #AAAAAA
        margin_bottom: 距底边距（px）
        margin_side: 距侧边距（px）

    返回：
        成功处理的图片数量
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("❌ 需要安装 Pillow: pip install Pillow")
        return 0

    # 免责声明文本（两行）
    line1 = "市场有风险，决策需独立；"
    line2 = "股市有风险，入市需谨慎。"

    # 加载中文字体
    font = find_chinese_font(font_size)
    if not font:
        print("⚠️ 未找到中文字体，跳过免责声明绘制")
        return 0

    # 处理所有图片
    images = sorted(image_dir.glob("P*.png"))
    if not images:
        print(f"⚠️ 未找到图片: {image_dir}/P*.png")
        return 0

    print(f"📝 正在为 {len(images)} 张图片绘制标准免责声明...")
    success = 0

    for img_path in images:
        try:
            img = Image.open(str(img_path)).convert("RGBA")
            img_w, img_h = img.size

            # 创建透明覆盖层用于绘制文字
            overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            # 计算行高和总高度
            line_height = font_size + 4
            total_text_height = line_height * 2

            # 根据版式决定位置
            if aspect_ratio == "9:16":
                # 竖版：底部居中
                bbox1 = draw.textbbox((0, 0), line1, font=font)
                bbox2 = draw.textbbox((0, 0), line2, font=font)
                w1 = bbox1[2] - bbox1[0]
                w2 = bbox2[2] - bbox2[0]
                x1 = (img_w - w1) // 2
                x2 = (img_w - w2) // 2
                y1 = img_h - total_text_height - margin_bottom
                y2 = y1 + line_height
            else:
                # 横版：底部右侧
                x1 = img_w - margin_side
                x2 = img_w - margin_side
                y1 = img_h - total_text_height - margin_bottom
                y2 = y1 + line_height
                # 右对齐：需要从右边界计算
                bbox1 = draw.textbbox((0, 0), line1, font=font)
                bbox2 = draw.textbbox((0, 0), line2, font=font)
                w1 = bbox1[2] - bbox1[0]
                w2 = bbox2[2] - bbox2[0]
                x1 = x1 - w1
                x2 = x2 - w2

            # 绘制两行文字（带微弱背景增强可读性）
            bg_padding = 3
            # 第一行背景
            draw.rounded_rectangle(
                [x1 - bg_padding, y1 - bg_padding,
                 x1 + w1 + bg_padding, y1 + line_height + bg_padding],
                radius=3, fill=(20, 20, 20, 160)  # 半透明深色背景
            )
            # 第二行背景
            draw.rounded_rectangle(
                [x2 - bg_padding, y2 - bg_padding,
                 x2 + w2 + bg_padding, y2 + line_height + bg_padding],
                radius=3, fill=(20, 20, 20, 160)
            )

            # 绘制文字
            draw.text((x1, y1), line1, font=font, fill=text_color + (255,))
            draw.text((x2, y2), line2, font=font, fill=text_color + (255,))

            # 合成到原图
            img = Image.alpha_composite(img, overlay)

            # 保存（转为 RGB 去掉 alpha 通道）
            img.convert("RGB").save(str(img_path), optimize=True)
            success += 1

        except Exception as e:
            print(f"   ✗ {img_path.name}: {e}")

    print(f"✅ 免责声明绘制完成: {success}/{len(images)}")
    return success


# ═══════════════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════════════

def submit_ppt_task(nb: NotebookLM, notebook_id: str, source_b_id: str, prompt: str, task_name: str, existing_artifact_ids: set) -> Tuple[Optional[str], set]:
    """提交 PPT 生成任务并获取 artifact ID
    
    返回: (artifact_id, updated_artifact_ids_set)
    """
    print(f"\n   → 提交 {task_name} 生成任务...")
    nb.run([
        "generate", "slide-deck",
        "--source", source_b_id,
        "--instructions", prompt,
        "--format", "detailed_deck",
        "--no-wait",
        "-n", notebook_id,
        "--json"
    ], timeout=30)

    # 立即查询 artifact list，找到新生成的 artifact
    artifact_id = None
    updated_ids = existing_artifact_ids.copy()

    for retry in range(10):
        wait_sec = 3 + retry * 2
        time.sleep(wait_sec)
        artifacts_result = nb.run(["artifact", "list", "-n", notebook_id, "--json"], timeout=30)
        artifacts_list = artifacts_result.get("artifacts", [])

        new_artifacts = [
            a for a in artifacts_list
            if a.get("id") not in existing_artifact_ids
        ]

        if len(new_artifacts) >= 1:
            artifact_id = new_artifacts[0].get("id")
            status = new_artifacts[0].get("status")
            print(f"   ✅ {task_name} artifact 已创建: {artifact_id[:8]}... (状态: {status})")
            updated_ids = {a.get("id") for a in artifacts_list}
            break
        else:
            print(f"   ⚠️ 第{retry+1}次查询未找到 {task_name} artifact，已等待{sum(range(3, 3+retry*2, 2))}s，{'重试中...' if retry < 9 else '将在下载后检查内容'}")

    if not artifact_id:
        print(f"   ⚠️ 无法记录 {task_name} artifact ID，将在下载后检查内容")

    return artifact_id, updated_ids


def wait_for_artifacts(nb: NotebookLM, notebook_id: str, artifact_ids: Dict[str, Optional[str]], wait_config: Dict) -> None:
    """等待多个 artifact 完成"""
    print("\n   ⏳ 等待 PPT 生成完成...")

    STATUS_MAP = {0: "pending", 1: "processing", 2: "ready", 3: "completed", 4: "failed"}

    start_time = time.time()
    timeout = wait_config.get("timeout", 900)
    initial_interval = wait_config.get("initial_interval", 540)
    max_interval = wait_config.get("max_interval", 60)

    # 初始静默等待
    if initial_interval > 0:
        print(f"   → 初始静默等待 {initial_interval}s...")
        time.sleep(initial_interval)

    poll_count = 0
    completed = {name: (aid is None) for name, aid in artifact_ids.items()}

    while not all(completed.values()):
        elapsed = time.time() - start_time
        if elapsed > timeout:
            raise RuntimeError(f"PPT 生成超时（{timeout}s）")

        # 查询 artifact 列表
        result = nb.run(["artifact", "list", "-n", notebook_id, "--json"], timeout=30)
        artifacts = result.get("artifacts", [])

        # 创建 ID -> artifact 的映射
        artifact_map = {a.get("id"): a for a in artifacts}

        # 检查每个 artifact 状态
        for name, aid in artifact_ids.items():
            if completed[name]:
                continue

            if aid and aid in artifact_map:
                artifact = artifact_map[aid]
                status_code = artifact.get("status", 0)
                if status_code == 3:
                    print(f"   ✅ {name} 已完成")
                    completed[name] = True
                elif status_code == 4:
                    raise RuntimeError(f"{name} 生成失败")

        # 如果全部完成，退出循环
        if all(completed.values()):
            break

        poll_count += 1
        status_strs = []
        for name, aid in artifact_ids.items():
            if aid:
                status = STATUS_MAP.get(artifact_map.get(aid, {}).get("status", 0), "unknown")
                status_strs.append(f"{name}={status}")
            else:
                status_strs.append(f"{name}=N/A")
        print(f"   → 第{poll_count}次轮询：{', '.join(status_strs)}")

        time.sleep(max_interval)


def _extract_ppt_text(pptx_path: Path, max_slides: int = 3) -> str:
    """从PPTX提取前N页的所有文本，用于内容判断"""
    try:
        from pptx import Presentation
        prs = Presentation(str(pptx_path))
        texts = []
        for i, slide in enumerate(prs.slides):
            if i >= max_slides:
                break
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text.strip():
                    texts.append(shape.text.strip())
        return " ".join(texts)
    except Exception:
        return ""


def download_and_merge_ppt_pair(
    nb: NotebookLM,
    notebook_id: str,
    temp_dir: Path,
    final_output_dir: Path,
    artifact_id_1: Optional[str],
    artifact_id_2: Optional[str],
    initial_artifact_ids: set,
    all_known_artifact_ids: set,
    ppt_name_1: str,
    ppt_name_2: str,
    output_name: str,
    aspect_ratio: str,
    logo_path: Path
) -> Tuple[Path, Path, int]:
    """下载、合并、Logo 遮盖一套 PPT（横版或竖版）

    返回: (final_pptx_path, images_dir, page_count)
    """
    # ── 方案C：当有 artifact ID 缺失时，通过内容精确匹配 ───────────
    if not artifact_id_1 or not artifact_id_2:
        print(f"   ⚠️ 有 artifact ID 缺失，执行方案C：精确匹配内容")

        result = nb.run(["artifact", "list", "-n", notebook_id, "--json"], timeout=30)
        artifacts = result.get("artifacts", [])

        # 排除：1) 生成前已有的 2) 其他PPT已知的
        exclude_ids = initial_artifact_ids | all_known_artifact_ids
        new_completed = [
            a for a in artifacts
            if a.get("status") == 3
            and a.get("kind") == "slide_deck"
            and a.get("id") not in exclude_ids
        ]

        if len(new_completed) == 0:
            raise RuntimeError("未找到任何新的完成 artifacts")

        print(f"   → 找到 {len(new_completed)} 个未知 artifacts")

        # 下载所有未知 artifacts 并检查内容
        candidates = []
        for a in new_completed:
            aid = a.get("id")
            temp_path = temp_dir / f"{output_name}_cand_{aid[:8]}.pptx"
            downloaded = nb.download_slides(temp_path, aid, notebook_id)
            text = _extract_ppt_text(downloaded)
            candidates.append({
                "artifact_id": aid,
                "path": downloaded,
                "text": text,
                "created_at": a.get("created_at", "")
            })
            print(f"   📥 下载候选: {aid[:8]}... (文本: {text[:60]}...)")

        # 精确匹配：根据提示词中的 PPT标识 判断
        # PPT1/PPT3 前半部分 → 文本中应包含 "PPT1" 或 "PPT3" 或 "第1页" 相关
        # PPT2/PPT4 后半部分 → 文本中应包含 "PPT2" 或 "PPT4" 或 "第{pages_per_deck+1}页" 相关
        first_markers = ["PPT1", "PPT3", "第1页", "第 1 页"]
        second_markers = ["PPT2", "PPT4", "第16页", "第 16 页"]

        first_half = None
        second_half = None

        for cand in candidates:
            text = cand["text"]
            # 优先匹配明确的PPT标识
            if any(m in text for m in first_markers):
                first_half = cand
                print(f"   ✅ 匹配到前半部分: {cand['artifact_id'][:8]}...")
            elif any(m in text for m in second_markers):
                second_half = cand
                print(f"   ✅ 匹配到后半部分: {cand['artifact_id'][:8]}...")

        # 如果只有一个未知 artifact
        if len(candidates) == 1:
            unknown = candidates[0]
            if artifact_id_1:
                # 已知的是前半部分
                first_half = {"path": nb.download_slides(temp_dir / f"{output_name}_known_1.pptx", artifact_id_1, notebook_id)}
                second_half = unknown
                print(f"   ✅ 单未知: 已知={ppt_name_1}, 未知={ppt_name_2}")
            elif artifact_id_2:
                # 已知的是后半部分
                first_half = unknown
                second_half = {"path": nb.download_slides(temp_dir / f"{output_name}_known_2.pptx", artifact_id_2, notebook_id)}
                print(f"   ✅ 单未知: 未知={ppt_name_1}, 已知={ppt_name_2}")
            else:
                raise RuntimeError("两个 artifact ID 都未知，且只找到1个新 artifact")
        else:
            # 多个候选但未精确匹配，按创建时间排序（先提交的=前半部分）
            if not first_half or not second_half:
                print(f"   ⚠️ 未精确匹配，按创建时间推断")
                candidates.sort(key=lambda x: x["created_at"])
                if not first_half:
                    first_half = candidates[0]
                if not second_half:
                    second_half = candidates[1] if len(candidates) > 1 else candidates[0]

        pptx_first = first_half["path"]
        pptx_second = second_half["path"]

    else:
        # 正常下载（有明确的 artifact ID）
        print(f"   → 下载 {ppt_name_1}...")
        pptx_first = nb.download_slides(temp_dir / f"{output_name}_1.pptx", artifact_id_1, notebook_id)
        print(f"   ✅ {ppt_name_1}: {pptx_first}")

        print(f"   → 下载 {ppt_name_2}...")
        pptx_second = nb.download_slides(temp_dir / f"{output_name}_2.pptx", artifact_id_2, notebook_id)
        print(f"   ✅ {ppt_name_2}: {pptx_second}")

    # 创建输出目录
    images_dir = final_output_dir / f"images_{output_name}"
    images_dir.mkdir(exist_ok=True)

    # 提取图片
    print(f"   → 提取 {ppt_name_1} 图片...")
    images_first = extract_images_from_pptx(pptx_first, images_dir)
    print(f"   ✅ 提取 {len(images_first)} 张")

    print(f"   → 提取 {ppt_name_2} 图片...")
    temp_images_dir = temp_dir / f"images_{output_name}_2"
    temp_images_dir.mkdir(exist_ok=True)
    images_second = extract_images_from_pptx(pptx_second, temp_images_dir)

    # 重命名并移动
    for img in images_second:
        new_name = f"P{len(images_first) + int(img.stem[1:])}.png"
        img.rename(images_dir / new_name)
    print(f"   ✅ 提取 {len(images_second)} 张")

    # 创建合并后的 PPTX
    all_images = sorted(images_dir.glob("P*.png"), key=lambda x: int(x.stem[1:]))
    final_pptx = final_output_dir / f"{output_name}.pptx"
    create_pptx_from_images(all_images, final_pptx, aspect_ratio)

    # Logo 遮盖
    print(f"\n   → 遮盖 {output_name} NotebookLM logo...")
    cover_count = cover_logo_on_images(images_dir, logo_path)

    if cover_count != len(all_images):
        print(f"   ⚠️ 部分图片遮盖失败: {cover_count}/{len(all_images)}")

    # 标准免责声明绘制（代码级硬保障）
    print(f"\n   → 绘制 {output_name} 标准免责声明...")
    disc_count = draw_disclaimer(images_dir, aspect_ratio)

    if disc_count != len(all_images):
        print(f"   ⚠️ 部分图片免责声明绘制失败: {disc_count}/{len(all_images)}")

    return final_pptx, images_dir, len(all_images)


# ═══════════════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════════════

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
    同时生成横版（16:9）和竖版（9:16）两套 PPT
    """
    # 参数处理
    title = title or md_file.stem
    logo_path = logo_path or DEFAULT_LOGO_PATH
    wait_config = wait_config or DEFAULT_WAIT_CONFIG

    print("="*60)
    print(f"📄 输入文件: {md_file}")
    print(f"📝 初始标题: {title}")
    print(f"📊 目标页数: {pages}")
    print(f"🎨 Logo: {logo_path}")
    print("="*60)

    # 初始化
    cli_path = find_notebooklm_cli()
    nb = NotebookLM(cli_path)

    notebook_id = None
    temp_dir = None
    notebook_title = title

    try:
        # ─── Step 1: 创建笔记本 ───────────────────────────────────────
        print("\n[1/10] 创建 NotebookLM 笔记本...")
        notebook_id = nb.create_notebook(title)
        print(f"   ✅ 笔记本 ID: {notebook_id}")

        # ─── Step 2: 上传 MD 作为来源并重命名为 a ────────────────────
        print("\n[2/10] 上传 MD 文件作为来源...")
        source_a_id, source_a_title = nb.add_source_file(md_file, notebook_id)
        print(f"   ✅ 来源上传成功: {source_a_title} ({source_a_id})")

        # 重命名为 a
        print("   → 重命名为 'a'...")
        nb.rename_source(source_a_id, notebook_id, "a")
        print(f"   ✅ 来源 A: a ({source_a_id})")

        # ─── Step 3: 从来源提取关键信息并重命名笔记本 ──────────────────
        print("\n[3/10] 从来源提取关键信息并重命名笔记本...")
        extract_prompt = '请从来源 a 中提取报告的核心主题，用一句话概括（不超过20字），仅返回主题名称，不要任何其他内容。'
        result = nb.run([
            "ask", extract_prompt,
            "-n", notebook_id,
            "--source", source_a_id
        ], timeout=120)

        # 从结果中提取标题
        output_text = result.get("output", "").strip()
        if not output_text:
            output_text = str(result).strip()

        # 清理输出（去除常见前缀如 "answer:"、引号等）
        cleaned = output_text.split('\n')[0][:20] if output_text else title
        # 去除 "answer:"、"Answer:"、"答案：" 等前缀
        for prefix in ["answer:", "Answer:", "答案：", "答案:", "\u201c", "\u201d", '"', "'"]:
            cleaned = cleaned.removeprefix(prefix)
        cleaned = cleaned.strip()
        notebook_title = cleaned if cleaned else title

        # 清理标题中的非法文件名字符（/ \ : * ? " < > |）
        import re
        notebook_title = re.sub(r'[\\/:*?"<>|]', '_', notebook_title)

        # 重命名笔记本
        nb.rename_notebook(notebook_id, notebook_title)
        print(f"   ✅ 笔记本重命名为: {notebook_title}")

        # ─── Step 4: 自动生成 PPT 大纲（带风格要求，强制中文）───────────
        print("\n[4/10] 自动生成 PPT 大纲（带风格要求，强制中文）...")

        prompt = f'''你是一位资深行业分析师。请严格依据来源a的研报原文内容，生成一份{pages}页的PPT演示大纲。

【硬性要求】
- 严禁遗漏研报中提到的任何重点标的，必须逐一覆盖
- 每个重点标的必须分配至少1个独立页面进行专门分析
- 标的分析页面必须包含：公司名称、主营业务、与主题的直接关联、核心受益逻辑、关键数据或财务指标
- 对于涉及投资评级的部分，使用巧妙回避但用户能一目了然的替代性词语表达推荐程度，严禁直接使用"强烈推荐""买入""卖出"等敏感词汇
- 严禁添加研报原文中没有的内容，如"机构内部使用，请勿外传"等额外声明

【每页要求】
- 明确的页面标题
- 3-5个核心要点，要点中必须包含具体公司名称和关键数据
- 严禁使用泛泛而谈的表述，必须落实到具体标的上
- **每页必须包含"画面构图描述"**：说明该页的视觉布局（如"左图右文""全幅图表+底部结论""顶部大标题+中部数据卡片+底部注释"）、建议使用的图表类型（柱状图/折线图/流程图/结构图等）、配色强调区域

【字体与排版规范】
- 全篇统一使用无衬线黑体家族（如思源黑体、阿里巴巴普惠体、微软雅黑），严禁混用宋体、楷体、仿宋等其他字体
- 标题层级：主标题 32-40pt Bold，副标题 24-28pt Medium，正文 18-20pt Regular
- 辅助注释/数据来源：12-14pt Light，灰色(#888888)
- 严禁使用斜体、艺术字、变形字体；严禁字体拉伸或压缩比例
- 中文行距 1.5-1.8 倍，段落间距统一

【语言要求】所有内容必须使用中文，包括标题、正文、图表标签等。严禁出现英文。

【风格要求】设计风格和PPT样式，采用高端商务黑金/暗黑机械风格。背景使用深邃黑与暗灰色渐变，营造沉浸式暗室感。主体图表（如结构图、流程图）必须呈现 3D 拟物化的哑光红铜/古铜金属材质，避免亮金色。图表边缘需带有亮金色流光（Neon Glow）特效。整体画面需传达出极度沉稳、权威、严谨与精密的专业研究质感。

【页脚规范（每页必须遵守）】
- 每页底部只允许放置标准免责声明：「市场有风险，决策需独立；股市有风险，入市需谨慎。」
- 严禁在页脚放置任何其他文字：包括但不限于品牌声明、机构名称、权威背书、保密声明、来源标注等一切非免责声明内容'''

        note_title = f"{pages}页PPT大纲"

        # 使用 ask（不带 --save-as-note）获取大纲内容
        print("\n[4/10] 向 NotebookLM 请求生成 PPT 大纲...")
        result = nb.run([
            "ask", prompt,
            "-n", notebook_id,
            "--source", source_a_id,
            "--json"
        ], timeout=900)

        # 从 ask 返回中提取答案文本
        note_content = result.get("answer", "")
        if not note_content:
            # 尝试其他可能的字段
            note_content = result.get("output", "")
        if not note_content:
            raise RuntimeError("ask 命令未返回有效内容")

        print(f"   ✅ 大纲内容已获取: {len(note_content)} 字符")

        # ─── Step 5: 将大纲内容直接转为来源 B ───────────────────────
        print("\n[5/10] 将大纲内容转为来源 B...")
        print(f"   📝 大纲内容: {len(note_content)} 字符")

        # 添加为来源
        source_b_id = nb.add_source_text(note_content, notebook_id, note_title)
        # 重命名为 b
        nb.rename_source(source_b_id, notebook_id, "b")
        print(f"   ✅ 来源 B: {source_b_id}")

        # ─── Step 6: 并行生成 PPT（横版 + 竖版）────────────────────────
        print("\n[6/10] 并行生成 PPT（横版 16:9 + 竖版 9:16）...")
        pages_per_deck = pages // 2

        # 获取生成前的 artifacts 列表（用于排除已存在的）
        artifacts_result = nb.run(["artifact", "list", "-n", notebook_id, "--json"], timeout=30)
        initial_artifacts = artifacts_result.get("artifacts", [])
        initial_artifact_ids = {a.get("id") for a in initial_artifacts}
        print(f"   → 已有 {len(initial_artifacts)} 个 artifacts")

        # 统一的字体与排版规范（4个PPT共用）
        font_rules = '''【字体与排版强制规范】
- 全篇必须统一使用同一种无衬线黑体（推荐：思源黑体 或 阿里巴巴普惠体），标题/正文/注释仅通过字重区分，严禁混用宋体、楷体、仿宋、圆体等其他字体
- 字号体系：主标题 36-44pt Bold，副标题/章节标题 28-32pt Medium，正文要点 20-24pt Regular，辅助注释/数据来源 14-16pt Light
- 严禁使用斜体（Italic）、艺术字（WordArt）、变形字体、拉伸/压缩字体比例；所有文字必须保持正常宽高比
- 中文行距 1.5-1.8 倍，段落间距统一，严禁文字重叠或超出页面边界
- 每页核心结论使用高对比色（亮金/纯白）突出，辅助说明使用暗灰(#AAAAAA)弱化，形成清晰的信息层级'''

        # 统一的风格描述（4个PPT共用）
        # 注意：包含"权威/严谨/精密"等强力风格词，但必须配合 disclaimer 变量中的
        # 明确禁止规则使用，否则 NotebookLM 可能将这些词转化为页脚品牌声明。
        # 最终由 draw_disclaimer() 函数在代码层强制覆盖为标准免责声明。
        style_desc = '''【风格要求】设计风格和PPT样式，采用高端商务黑金/暗黑机械风格。背景使用深邃黑与暗灰色渐变，营造沉浸式暗室感。主体图表（如结构图、流程图）必须呈现 3D 拟物化的哑光红铜/古铜金属材质，避免亮金色。图表边缘需带有亮金色流光（Neon Glow）特效。整体画面需传达出极度沉稳、权威、严谨与精密的专业研究质感。'''

        # 统一的页脚免责声明要求（4个PPT共用）
        disclaimer = '''
【页脚免责声明（每页必须包含，且是页脚唯一允许的文字）】
- 每页底部只允许出现以下标准免责声明文字（两行），不得有其他任何页脚内容：
  第1行：「市场有风险，决策需独立；」
  第2行：「股市有风险，入市需谨慎。」
- 免责声明使用小字号(12-14pt Light)，颜色为暗灰(#AAAAAA或#888888)
- 横版PPT：免责声明放置于页面底部右侧或居中，靠近页边距
- 竖版PPT：免责声明放置于页面最底部居中

【通用封杀令 — 严禁以下所有类型的页脚/页面文字】
- ❌ 品牌声明类：任何形式的品牌名称、机构名称、产品名（如「高端商业咨询」「顾问系统研究""XX研究院"等）
- ❌ 权威背书类：任何自封的权威性描述（如「严谨•权威•精密」「专业研究报告」「内部资料」等）
- ❌ 保密/权限类：任何虚构的保密声明（如「机构内部使用」「请勿外传」「机密文件」「内部报告」等）
- ❌ 来源标注类：除研报正文引用外，不允许在页脚添加数据来源或版权信息
- ❌ 其他一切非研报内容的额外文字：如果大纲和来源a中没有要求的内容，一律禁止自行编造并放在页脚或其他位置

【核心原则】每页的页脚区域只能包含上述两行标准免责声明，除此之外的任何文字都是多余的、禁止的。'''

        # PPT 1 提示词（横版 16:9，第1-15页）
        ppt1_prompt = f'''[LANGUAGE: CHINESE ONLY - 禁止使用任何英文]

根据来源a的研报原文内容，严格按照来源b的大纲制作PPT。这份PPT总共包含{pages}页。

【强制语言要求】
- 所有页面必须100%使用中文
- 标题、正文、图表标签、页脚、按钮文字必须全部是中文
- 严禁出现任何英文单词或字母
- 如果必须使用专有名词，请用中文翻译

【内容完整性要求】
- 必须严格按照来源b的大纲逐页制作，严禁遗漏大纲中的任何页面
- 大纲中提到的每个标的必须有独立的分析页面，严禁合并或省略
- 必须保留研报中的关键数据、财务指标和具体业务细节
- 严禁添加大纲中没有的额外内容（如"机构内部使用"等声明）

{style_desc}

{font_rules}

【手机视频适配要求】
- 每页PPT将被导出为图片并制作成1分钟短视频，在手机上播放
- 页面设计必须适合手机竖屏观看：信息层级清晰，避免内容过于拥挤
- 核心观点和结论必须使用大号字体（标题级），确保手机屏幕上3米外仍能一目了然
- 辅助说明、数据细节、背景补充可使用较小字体，但不得影响主信息的可读性
- 每页控制在3-5个核心要点，严禁堆砌文字
- 图表和插图必须占据显著位置，视觉冲击力优先于文字密度

{disclaimer}

【制作要求】要求插图丰富，确保每个中文字不要出错，字体清晰。先制作来源b要求的第1-{pages_per_deck}页。

【PPT标识】这是PPT1，包含第1-{pages_per_deck}页。'''

        # PPT 2 提示词（横版 16:9，第16-30页）
        ppt2_prompt = f'''[LANGUAGE: CHINESE ONLY - 禁止使用任何英文]

根据来源a的研报原文内容，严格按照来源b里的大纲制作PPT。这份PPT总共包含{pages}页。

【强制语言要求】
- 所有页面必须100%使用中文
- 标题、正文、图表标签、页脚、按钮文字必须全部是中文
- 严禁出现任何英文单词或字母
- 如果必须使用专有名词，请用中文翻译

【内容完整性要求】
- 必须严格按照来源b的大纲逐页制作，严禁遗漏大纲中的任何页面
- 大纲中提到的每个标的必须有独立的分析页面，严禁合并或省略
- 必须保留研报中的关键数据、财务指标和具体业务细节
- 严禁添加大纲中没有的额外内容（如"机构内部使用"等声明）

{style_desc}

{font_rules}

【手机视频适配要求】
- 每页PPT将被导出为图片并制作成1分钟短视频，在手机上播放
- 页面设计必须适合手机竖屏观看：信息层级清晰，避免内容过于拥挤
- 核心观点和结论必须使用大号字体（标题级），确保手机屏幕上3米外仍能一目了然
- 辅助说明、数据细节、背景补充可使用较小字体，但不得影响主信息的可读性
- 每页控制在3-5个核心要点，严禁堆砌文字
- 图表和插图必须占据显著位置，视觉冲击力优先于文字密度

{disclaimer}

【制作要求】要求插图丰富，确保每个中文字不要出错，字体清晰。制作来源b要求的第{pages_per_deck+1}-{pages}页，要求和前{pages_per_deck}页保持完全一致的风格和语言。

【PPT标识】这是PPT2，包含第{pages_per_deck+1}-{pages}页。'''

        # PPT 3 提示词（竖版 9:16，第1-15页）
        ppt3_prompt = f'''[LANGUAGE: CHINESE ONLY - 禁止使用任何英文]

根据来源a的研报原文内容，严格按照来源b的大纲制作PPT。这份PPT总共包含{pages}页。

【强制页面比例】
- 必须采用9:16竖屏比例设计（宽:高 = 9:16），严禁使用16:9横屏
- 页面布局以竖向信息流为主，从上到下依次展开

【强制语言要求】
- 所有页面必须100%使用中文
- 标题、正文、图表标签、页脚、按钮文字必须全部是中文
- 严禁出现任何英文单词或字母
- 如果必须使用专有名词，请用中文翻译

【内容完整性要求】
- 必须严格按照来源b的大纲逐页制作，严禁遗漏大纲中的任何页面
- 大纲中提到的每个标的必须有独立的分析页面，严禁合并或省略
- 必须保留研报中的关键数据、财务指标和具体业务细节
- 严禁添加大纲中没有的额外内容（如"机构内部使用"等声明）

{style_desc}

{font_rules}

【手机竖屏适配要求】
- 每页PPT将被导出为图片并制作成1分钟短视频，在手机上竖屏播放
- 页面设计必须专为手机竖屏优化：信息从上到下层级递进，避免左右分栏
- 核心观点和结论必须使用超大号字体（占据页面上半部黄金区域），确保手机屏幕上3米外仍能一目了然
- 辅助说明、数据细节、背景补充可使用较小字体（放置页面中下部），但不得影响主信息的可读性
- 每页控制在3-4个核心要点，严禁堆砌文字
- 图表和插图必须竖向排列，占据页面显著位置，视觉冲击力优先于文字密度
- 标题居顶、结论居中、细节居底，形成清晰的F型竖向阅读动线

{disclaimer}

【制作要求】要求插图丰富，确保每个中文字不要出错，字体清晰。先制作来源b要求的第1-{pages_per_deck}页。

【PPT标识】这是PPT3（竖屏版），包含第1-{pages_per_deck}页。'''

        # PPT 4 提示词（竖版 9:16，第16-30页）
        ppt4_prompt = f'''[LANGUAGE: CHINESE ONLY - 禁止使用任何英文]

根据来源a的研报原文内容，严格按照来源b里的大纲制作PPT。这份PPT总共包含{pages}页。

【强制页面比例】
- 必须采用9:16竖屏比例设计（宽:高 = 9:16），严禁使用16:9横屏
- 页面布局以竖向信息流为主，从上到下依次展开

【强制语言要求】
- 所有页面必须100%使用中文
- 标题、正文、图表标签、页脚、按钮文字必须全部是中文
- 严禁出现任何英文单词或字母
- 如果必须使用专有名词，请用中文翻译

【内容完整性要求】
- 必须严格按照来源b的大纲逐页制作，严禁遗漏大纲中的任何页面
- 大纲中提到的每个标的必须有独立的分析页面，严禁合并或省略
- 必须保留研报中的关键数据、财务指标和具体业务细节
- 严禁添加大纲中没有的额外内容（如"机构内部使用"等声明）

{style_desc}

{font_rules}

【手机竖屏适配要求】
- 每页PPT将被导出为图片并制作成1分钟短视频，在手机上竖屏播放
- 页面设计必须专为手机竖屏优化：信息从上到下层级递进，避免左右分栏
- 核心观点和结论必须使用超大号字体（占据页面上半部黄金区域），确保手机屏幕上3米外仍能一目了然
- 辅助说明、数据细节、背景补充可使用较小字体（放置页面中下部），但不得影响主信息的可读性
- 每页控制在3-4个核心要点，严禁堆砌文字
- 图表和插图必须竖向排列，占据页面显著位置，视觉冲击力优先于文字密度
- 标题居顶、结论居中、细节居底，形成清晰的F型竖向阅读动线

{disclaimer}

【制作要求】要求插图丰富，确保每个中文字不要出错，字体清晰。制作来源b要求的第{pages_per_deck+1}-{pages}页，要求和前{pages_per_deck}页保持完全一致的风格和语言。

【PPT标识】这是PPT4（竖屏版），包含第{pages_per_deck+1}-{pages}页。'''

        # 提交 4 个生成任务
        ppt1_artifact_id, ids_after_ppt1 = submit_ppt_task(nb, notebook_id, source_b_id, ppt1_prompt, "PPT1 (横版前半)", initial_artifact_ids)
        ppt2_artifact_id, ids_after_ppt2 = submit_ppt_task(nb, notebook_id, source_b_id, ppt2_prompt, "PPT2 (横版后半)", ids_after_ppt1)
        ppt3_artifact_id, ids_after_ppt3 = submit_ppt_task(nb, notebook_id, source_b_id, ppt3_prompt, "PPT3 (竖版前半)", ids_after_ppt2)
        ppt4_artifact_id, _ = submit_ppt_task(nb, notebook_id, source_b_id, ppt4_prompt, "PPT4 (竖版后半)", ids_after_ppt3)

        # ─── 等待 4 个 PPT 完成 ────────────────────────────────────────
        artifact_ids = {
            "PPT1 (横版前半)": ppt1_artifact_id,
            "PPT2 (横版后半)": ppt2_artifact_id,
            "PPT3 (竖版前半)": ppt3_artifact_id,
            "PPT4 (竖版后半)": ppt4_artifact_id,
        }
        wait_for_artifacts(nb, notebook_id, artifact_ids, wait_config)

        print(f"\n   ✅ PPT1 artifact: {ppt1_artifact_id}")
        print(f"   ✅ PPT2 artifact: {ppt2_artifact_id}")
        print(f"   ✅ PPT3 artifact: {ppt3_artifact_id}")
        print(f"   ✅ PPT4 artifact: {ppt4_artifact_id}")

        # ─── Step 7: 创建临时目录 ────────────────────────────────────
        print("\n[7/10] 准备下载...")
        temp_dir = Path(tempfile.mkdtemp(prefix="nb2pptx_"))
        print(f"   📂 临时目录: {temp_dir}")

        # 创建输出目录
        final_output_dir = output_dir or (DEFAULT_OUTPUT_DIR / notebook_title)
        final_output_dir.mkdir(parents=True, exist_ok=True)
        print(f"   📁 输出目录: {final_output_dir}")

        # ─── Step 8: 下载并合并横版 PPT ──────────────────────────────
        print("\n[8/10] 下载并合并横版 PPT (16:9)...")
        # 横版下载时，排除竖版的已知 artifact IDs
        vertical_known_ids = {aid for aid in [ppt3_artifact_id, ppt4_artifact_id] if aid}
        final_pptx_h, images_dir_h, page_count_h = download_and_merge_ppt_pair(
            nb, notebook_id, temp_dir, final_output_dir,
            ppt1_artifact_id, ppt2_artifact_id,
            initial_artifact_ids,
            vertical_known_ids,
            "PPT1 (横版前半)", "PPT2 (横版后半)",
            notebook_title, "16:9", logo_path
        )

        # ─── Step 9: 下载并合并竖版 PPT ──────────────────────────────
        print("\n[9/10] 下载并合并竖版 PPT (9:16)...")
        # 竖版下载时，排除横版的已知 artifact IDs
        horizontal_known_ids = {aid for aid in [ppt1_artifact_id, ppt2_artifact_id] if aid}
        final_pptx_v, images_dir_v, page_count_v = download_and_merge_ppt_pair(
            nb, notebook_id, temp_dir, final_output_dir,
            ppt3_artifact_id, ppt4_artifact_id,
            initial_artifact_ids,
            horizontal_known_ids,
            "PPT3 (竖版前半)", "PPT4 (竖版后半)",
            f"{notebook_title}_竖版", "9:16", logo_path
        )

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

        # ─── 完成 ───────────────────────────────────────────────────
        print("\n" + "="*60)
        print("✅ 流水线完成！")
        print(f"\n📦 横版 PPTX (16:9): {final_pptx_h}")
        print(f"   🖼️  图片: {images_dir_h} ({page_count_h} 张)")
        print(f"\n📦 竖版 PPTX (9:16): {final_pptx_v}")
        print(f"   🖼️  图片: {images_dir_v} ({page_count_v} 张)")
        print("="*60)

        return {
            "pptx_horizontal": str(final_pptx_h),
            "images_dir_horizontal": str(images_dir_h),
            "page_count_horizontal": page_count_h,
            "pptx_vertical": str(final_pptx_v),
            "images_dir_vertical": str(images_dir_v),
            "page_count_vertical": page_count_v,
        }

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
        description="NotebookLM MD → PPTX 完整流水线（横版+竖版）",
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
