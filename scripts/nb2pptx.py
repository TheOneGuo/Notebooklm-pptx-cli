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
    7. 下载并分别合并横版和竖版 PPTX
    8. 提取图片（images_landscape/ + images_portrait/）
    9. 遮盖 NotebookLM Logo
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
            "--format", "pptx",  # 强制使用 pptx 格式
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

def create_pptx_from_images(images: List[Path], output_path: Path, orientation: str = "landscape") -> None:
    """从图片创建 PPTX
    
    参数:
        images: 图片路径列表
        output_path: 输出 PPTX 路径
        orientation: 方向 - "landscape"(横版 16:9) 或 "portrait"(竖版 9:16)
    """
    try:
        from pptx import Presentation
        from pptx.util import Inches
    except ImportError:
        print("❌ 需要安装 python-pptx: pip install python-pptx")
        sys.exit(1)
    
    prs = Presentation()
    if orientation == "portrait":
        prs.slide_width = Inches(7.5)   # 9:16 竖版
        prs.slide_height = Inches(13.333)
    else:
        prs.slide_width = Inches(13.333)  # 16:9 横版
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
    print(f"✅ PPTX 创建完成: {output_path} ({orientation})")

def merge_pptx_files(pptx1_path: Path, pptx2_path: Path, output_path: Path, notebook_title: str) -> None:
    """
    合并两个 PPTX 文件：在 ppt1 后增加空白页 + 粘贴 ppt2 的图片
    
    参数：
        pptx1_path: PPT1 文件路径
        pptx2_path: PPT2 文件路径
        output_path: 输出文件路径
        notebook_title: 笔记本名称（用于输出文件名）
    """
    try:
        from pptx import Presentation
        from pptx.util import Inches
    except ImportError:
        print("❌ 需要安装 python-pptx: pip install python-pptx")
        sys.exit(1)
    
    print("   → 打开 PPT 1...")
    prs1 = Presentation(str(pptx1_path))
    slide_width = prs1.slide_width
    slide_height = prs1.slide_height
    blank_layout = prs1.slide_layouts[6]  # 空白布局
    
    print(f"   → PPT 1 原有 {len(prs1.slides)} 页")
    
    # 提取 ppt2 的图片
    temp_dir = pptx2_path.parent / "temp_ppt2_images"
    temp_dir.mkdir(exist_ok=True)
    print("   → 提取 PPT 2 的图片...")
    images_ppt2 = extract_images_from_pptx(pptx2_path, temp_dir)
    print(f"   ✅ 提取 {len(images_ppt2)} 张图片")
    
    # 在 ppt1 后增加空白页并粘贴图片
    print("   → 在 PPT 1 后增加页面并粘贴图片...")
    for i, img_path in enumerate(sorted(images_ppt2, key=lambda x: int(x.stem[1:])), 1):
        slide = prs1.slides.add_slide(blank_layout)
        # 添加图片，占满整张幻灯片
        slide.shapes.add_picture(
            str(img_path),
            Inches(0), Inches(0),
            width=slide_width,
            height=slide_height
        )
        print(f"   ✓ 第{len(prs1.slides)}页: {img_path.name}")
    
    # 保存合并后的 PPTX
    prs1.save(str(output_path))
    print(f"✅ PPTX 合并完成: {output_path} (共 {len(prs1.slides)} 页)")
    
    # 清理临时图片
    shutil.rmtree(temp_dir)

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
    notebook_title = title  # 初始化为 title，后续会被步骤3重命名
    
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
        print("\n[5/10] 将大纲笔记转为来源 B...")
        # 获取笔记内容
        note_content = nb.get_note_content(note_id, notebook_id)
        print(f"   📝 笔记内容: {len(note_content)} 字符")
        
        # 添加为来源
        source_b_id = nb.add_source_text(note_content, notebook_id, note_title)
        # 重命名为 b
        nb.rename_source(source_b_id, notebook_id, "b")
        print(f"   ✅ 来源 B: {source_b_id}")
        
        # ─── Step 6: 并行生成 PPT（横版 PPT1/PPT2 + 竖版 PPT3/PPT4）──────────────────────
        print("\n[6/10] 并行生成 PPT（横版+竖版）...")
        pages_per_deck = pages // 2
        
        # 获取生成前的 artifacts 列表（用于排除已存在的）
        artifacts_result = nb.run(["artifact", "list", "-n", notebook_id, "--json"], timeout=30)
        initial_artifacts = artifacts_result.get("artifacts", [])
        initial_artifact_ids = {a.get("id") for a in initial_artifacts}
        print(f"   → 已有 {len(initial_artifacts)} 个 artifacts")
        
        # ═══════════════════════════════════════════════════════════════════
        # 横版 PPT 提示词（PPT1 + PPT2）
        # ═══════════════════════════════════════════════════════════════════
        
        # PPT 1 提示词（横版前半部分）
        ppt1_prompt = f'''[LANGUAGE: CHINESE ONLY - 禁止使用任何英文]

根据来源a的分析内容，按照来源b的大纲制作PPT。这份PPT总共包含{pages}页。

【强制语言要求】
- 所有页面必须100%使用中文
- 标题、正文、图表标签、页脚、按钮文字必须全部是中文
- 严禁出现任何英文单词或字母
- 如果必须使用专有名词，请用中文翻译

【版式要求】横版（16:9）。页面宽度大于高度，适合PC端展示和宽屏投影。

【风格要求】采用高端商务黑金/暗黑机械风格。背景使用深邃黑与暗灰色渐变，营造沉浸式暗室感。主体图表（如结构图、流程图）必须呈现 3D 拟物化的哑光红铜/古铜金属材质，避免亮金色。图表边缘需带有亮金色流光特效。整体画面需传达出极度沉稳、权威、严谨与精密的质感。

【免责声明】所有页面底部必须显示以下文字（分两行）：
市场有风险，决策需独立；
股市有风险，入市需谨慎。

【内容要求】要求插图丰富，确保每个中文字不要出错，字体清晰。研报中提到的所有公司名称、股票代码、核心数据必须在PPT中明确体现，不得遗漏。先制作来源b要求的第1-{pages_per_deck}页。

【PPT标识】这是横版PPT1，包含第1-{pages_per_deck}页。'''

        # PPT 2 提示词（横版后半部分）
        ppt2_prompt = f'''[LANGUAGE: CHINESE ONLY - 禁止使用任何英文]

根据来源a的分析内容，按照来源b里的大纲制作PPT。这份PPT总共包含{pages}页。

【强制语言要求】
- 所有页面必须100%使用中文
- 标题、正文、图表标签、页脚、按钮文字必须全部是中文
- 严禁出现任何英文单词或字母
- 如果必须使用专有名词，请用中文翻译

【版式要求】横版（16:9）。页面宽度大于高度，适合PC端展示和宽屏投影。

【风格要求】采用高端商务黑金/暗黑机械风格。背景使用深邃黑与暗灰色渐变，营造沉浸式暗室感。主体图表（如结构图、流程图）必须呈现 3D 拟物化的哑光红铜/古铜金属材质，避免亮金色。图表边缘需带有亮金色流光特效。整体画面需传达出极度沉稳、权威、严谨与精密的质感。

【免责声明】所有页面底部必须显示以下文字（分两行）：
市场有风险，决策需独立；
股市有风险，入市需谨慎。

【内容要求】要求插图丰富，确保每个中文字不要出错，字体清晰。研报中提到的所有公司名称、股票代码、核心数据必须在PPT中明确体现，不得遗漏。制作来源b要求的第{pages_per_deck+1}-{pages}页，要求和前{pages_per_deck}页保持完全一致的风格和语言。

【PPT标识】这是横版PPT2，包含第{pages_per_deck+1}-{pages}页。'''

        # ═══════════════════════════════════════════════════════════════════
        # 竖版 PPT 提示词（PPT3 + PPT4）
        # ═══════════════════════════════════════════════════════════════════
        
        # PPT 3 提示词（竖版前半部分）
        ppt3_prompt = f'''[LANGUAGE: CHINESE ONLY - 禁止使用任何英文]

根据来源a的分析内容，按照来源b的大纲制作PPT。这份PPT总共包含{pages}页。

【强制语言要求】
- 所有页面必须100%使用中文
- 标题、正文、图表标签、页脚、按钮文字必须全部是中文
- 严禁出现任何英文单词或字母
- 如果必须使用专有名词，请用中文翻译

【版式要求】必须严格使用竖版（9:16）纵向布局。页面高度明显大于宽度（高宽比约为1.77:1），适合手机端短视频展示。所有内容必须纵向排列：大标题在页面上方，正文和图表垂直向下展开，左右留白对称，充分利用竖向空间。严禁使用横版布局。

【风格要求】采用高端商务黑金/暗黑机械风格。背景使用深邃黑与暗灰色渐变，营造沉浸式暗室感。主体图表（如结构图、流程图）必须呈现 3D 拟物化的哑光红铜/古铜金属材质，避免亮金色。图表边缘需带有亮金色流光特效。整体画面需传达出极度沉稳、权威、严谨与精密的质感。

【免责声明】所有页面底部必须显示以下文字（分两行）：
市场有风险，决策需独立；
股市有风险，入市需谨慎。

【内容要求】要求插图丰富，确保每个中文字不要出错，字体清晰。研报中提到的所有公司名称、股票代码、核心数据必须在PPT中明确体现，不得遗漏。先制作来源b要求的第1-{pages_per_deck}页。

【PPT标识】这是竖版PPT3，包含第1-{pages_per_deck}页。'''

        # PPT 4 提示词（竖版后半部分）
        ppt4_prompt = f'''[LANGUAGE: CHINESE ONLY - 禁止使用任何英文]

根据来源a的分析内容，按照来源b里的大纲制作PPT。这份PPT总共包含{pages}页。

【强制语言要求】
- 所有页面必须100%使用中文
- 标题、正文、图表标签、页脚、按钮文字必须全部是中文
- 严禁出现任何英文单词或字母
- 如果必须使用专有名词，请用中文翻译

【版式要求】必须严格使用竖版（9:16）纵向布局。页面高度明显大于宽度（高宽比约为1.77:1），适合手机端短视频展示。所有内容必须纵向排列：大标题在页面上方，正文和图表垂直向下展开，左右留白对称，充分利用竖向空间。严禁使用横版布局。

【风格要求】采用高端商务黑金/暗黑机械风格。背景使用深邃黑与暗灰色渐变，营造沉浸式暗室感。主体图表（如结构图、流程图）必须呈现 3D 拟物化的哑光红铜/古铜金属材质，避免亮金色。图表边缘需带有亮金色流光特效。整体画面需传达出极度沉稳、权威、严谨与精密的质感。

【免责声明】所有页面底部必须显示以下文字（分两行）：
市场有风险，决策需独立；
股市有风险，入市需谨慎。

【内容要求】要求插图丰富，确保每个中文字不要出错，字体清晰。研报中提到的所有公司名称、股票代码、核心数据必须在PPT中明确体现，不得遗漏。制作来源b要求的第{pages_per_deck+1}-{pages}页，要求和前{pages_per_deck}页保持完全一致的风格和语言。

【PPT标识】这是竖版PPT4，包含第{pages_per_deck+1}-{pages}页。'''

        # ═══════════════════════════════════════════════════════════════════
        # 并行提交 4 个生成任务
        # ═══════════════════════════════════════════════════════════════════
        
        def submit_and_track(task_name, prompt, excluded_ids):
            """提交生成任务并追踪 artifact ID"""
            print(f"\n   → 提交 {task_name} 生成任务...")
            result = nb.run([
                "generate", "slide-deck",
                "--source", source_b_id,
                "--instructions", prompt,
                "--format", "detailed_deck",
                "--no-wait",
                "-n", notebook_id,
                "--json"
            ], timeout=30)
            
            artifact_id = None
            for retry in range(5):
                time.sleep(3 + retry * 2)
                artifacts_resp = nb.run(["artifact", "list", "-n", notebook_id, "--json"], timeout=30)
                artifacts_list = artifacts_resp.get("artifacts", [])
                
                new_artifacts = [
                    a for a in artifacts_list
                    if a.get("id") not in excluded_ids
                ]
                
                if len(new_artifacts) >= 1:
                    artifact_id = new_artifacts[0].get("id")
                    status = new_artifacts[0].get("status")
                    print(f"   ✅ {task_name} artifact 已创建: {artifact_id[:8]}... (状态: {status})")
                    # 返回更新后的 excluded_ids（包含新发现的 artifact）
                    new_excluded = excluded_ids | {a.get("id") for a in artifacts_list}
                    return artifact_id, new_excluded
                else:
                    print(f"   ⚠️ 第{retry+1}次查询未找到 {task_name} artifact，{'重试中...' if retry < 4 else '将在下载后检查内容'}")
            
            if not artifact_id:
                print(f"   ⚠️ 无法记录 {task_name} artifact ID，将在下载后检查内容")
            return artifact_id, excluded_ids
        
        # 按顺序提交 4 个任务，每个都追踪 artifact ID
        # PPT 1（横版前半）
        ppt1_artifact_id, excluded_after_ppt1 = submit_and_track(
            "PPT 1（横版前半）", ppt1_prompt, initial_artifact_ids
        )
        
        # PPT 2（横版后半）
        ppt2_artifact_id, excluded_after_ppt2 = submit_and_track(
            "PPT 2（横版后半）", ppt2_prompt, excluded_after_ppt1
        )
        
        # PPT 3（竖版前半）
        ppt3_artifact_id, excluded_after_ppt3 = submit_and_track(
            "PPT 3（竖版前半）", ppt3_prompt, excluded_after_ppt2
        )
        
        # PPT 4（竖版后半）
        ppt4_artifact_id, excluded_after_ppt4 = submit_and_track(
            "PPT 4（竖版后半）", ppt4_prompt, excluded_after_ppt3
        )
        
        # ─── 等待 4 个 PPT 完成 ──────────────────────────────────────
        print("\n   ⏳ 等待 PPT 生成完成...")
        
        # 状态码映射
        STATUS_MAP = {0: "pending", 1: "processing", 2: "ready", 3: "completed", 4: "failed"}
        
        start_time = time.time()
        timeout = wait_config.get("timeout", 1800)  # 4个PPT，超时改为30分钟
        initial_interval = wait_config.get("initial_interval", 540)
        max_interval = wait_config.get("max_interval", 60)
        
        # 初始静默等待
        if initial_interval > 0:
            print(f"   → 初始静默等待 {initial_interval}s...")
            time.sleep(initial_interval)
        
        poll_count = 0
        ppt1_completed = ppt1_artifact_id is None
        ppt2_completed = ppt2_artifact_id is None
        ppt3_completed = ppt3_artifact_id is None
        ppt4_completed = ppt4_artifact_id is None
        
        while not (ppt1_completed and ppt2_completed and ppt3_completed and ppt4_completed):
            elapsed = time.time() - start_time
            if elapsed > timeout:
                raise RuntimeError(f"PPT 生成超时（{timeout}s）")
            
            # 查询 artifact 列表
            result = nb.run(["artifact", "list", "-n", notebook_id, "--json"], timeout=30)
            artifacts = result.get("artifacts", [])
            
            # 创建 ID -> artifact 的映射
            artifact_map = {a.get("id"): a for a in artifacts}
            
            # 检查 PPT 1 状态
            if not ppt1_completed and ppt1_artifact_id and ppt1_artifact_id in artifact_map:
                status_code = artifact_map[ppt1_artifact_id].get("status", 0)
                if status_code == 3:
                    print(f"   ✅ PPT 1（横版前半）已完成")
                    ppt1_completed = True
                elif status_code == 4:
                    raise RuntimeError("PPT 1（横版前半）生成失败")
            
            # 检查 PPT 2 状态
            if not ppt2_completed and ppt2_artifact_id and ppt2_artifact_id in artifact_map:
                status_code = artifact_map[ppt2_artifact_id].get("status", 0)
                if status_code == 3:
                    print(f"   ✅ PPT 2（横版后半）已完成")
                    ppt2_completed = True
                elif status_code == 4:
                    raise RuntimeError("PPT 2（横版后半）生成失败")
            
            # 检查 PPT 3 状态
            if not ppt3_completed and ppt3_artifact_id and ppt3_artifact_id in artifact_map:
                status_code = artifact_map[ppt3_artifact_id].get("status", 0)
                if status_code == 3:
                    print(f"   ✅ PPT 3（竖版前半）已完成")
                    ppt3_completed = True
                elif status_code == 4:
                    raise RuntimeError("PPT 3（竖版前半）生成失败")
            
            # 检查 PPT 4 状态
            if not ppt4_completed and ppt4_artifact_id and ppt4_artifact_id in artifact_map:
                status_code = artifact_map[ppt4_artifact_id].get("status", 0)
                if status_code == 3:
                    print(f"   ✅ PPT 4（竖版后半）已完成")
                    ppt4_completed = True
                elif status_code == 4:
                    raise RuntimeError("PPT 4（竖版后半）生成失败")
            
            # 如果全部完成，退出循环
            if ppt1_completed and ppt2_completed and ppt3_completed and ppt4_completed:
                break
            
            poll_count += 1
            s1 = STATUS_MAP.get(artifact_map.get(ppt1_artifact_id, {}).get("status", 0), "unknown") if ppt1_artifact_id else "N/A"
            s2 = STATUS_MAP.get(artifact_map.get(ppt2_artifact_id, {}).get("status", 0), "unknown") if ppt2_artifact_id else "N/A"
            s3 = STATUS_MAP.get(artifact_map.get(ppt3_artifact_id, {}).get("status", 0), "unknown") if ppt3_artifact_id else "N/A"
            s4 = STATUS_MAP.get(artifact_map.get(ppt4_artifact_id, {}).get("status", 0), "unknown") if ppt4_artifact_id else "N/A"
            print(f"   → 第{poll_count}次轮询：横1={s1}, 横2={s2}, 竖1={s3}, 竖2={s4}")
            
            time.sleep(max_interval)
        
        # 方案C：如果无法记录ID，下载后检查内容
        if not all([ppt1_artifact_id, ppt2_artifact_id, ppt3_artifact_id, ppt4_artifact_id]):
            print("\n   ⚠️ 无法通过立即查询记录部分 artifact ID，将下载后检查内容（方案C）")
        
        print(f"\n   ✅ PPT 1（横版前半）: {ppt1_artifact_id}")
        print(f"   ✅ PPT 2（横版后半）: {ppt2_artifact_id}")
        print(f"   ✅ PPT 3（竖版前半）: {ppt3_artifact_id}")
        print(f"   ✅ PPT 4（竖版后半）: {ppt4_artifact_id}")
        
        # ─── Step 7: 下载 PPT ─────────────────────────────────────
        print("\n[7/10] 下载 PPT...")
        
        # 创建临时目录
        temp_dir = Path(tempfile.mkdtemp(prefix="nb2pptx_"))
        print(f"   📂 临时目录: {temp_dir}")
        
        def download_with_fallback(task_label, artifact_id, temp_name, excluded_ids_set):
            """下载 PPT，如果 ID 缺失则通过内容识别"""
            if artifact_id:
                path = nb.download_slides(temp_dir / temp_name, artifact_id, notebook_id)
                print(f"   ✅ {task_label}: {path.name}")
                return path
            
            # 方案C：通过内容识别
            print(f"   ⚠️ {task_label} ID 缺失，执行方案C...")
            result = nb.run(["artifact", "list", "-n", notebook_id, "--json"], timeout=30)
            artifacts = result.get("artifacts", [])
            
            candidates = [
                a for a in artifacts
                if a.get("status") == 3
                and a.get("kind") == "slide_deck"
                and a.get("id") not in excluded_ids_set
            ]
            
            if not candidates:
                raise RuntimeError(f"未找到 {task_label} 的 artifact")
            
            picked = candidates[0]
            picked_id = picked.get("id")
            path = nb.download_slides(temp_dir / temp_name, picked_id, notebook_id)
            print(f"   ✅ {task_label} (方案C): {path.name}")
            excluded_ids_set.add(picked_id)
            return path
        
        excluded_ids = set(initial_artifact_ids)
        
        # 下载横版 PPT1 + PPT2
        print("   → 下载横版 PPT...")
        pptx_h1 = download_with_fallback("PPT 1（横版前半）", ppt1_artifact_id, "ppt_h1.pptx", excluded_ids)
        pptx_h2 = download_with_fallback("PPT 2（横版后半）", ppt2_artifact_id, "ppt_h2.pptx", excluded_ids)
        
        # 下载竖版 PPT3 + PPT4
        print("   → 下载竖版 PPT...")
        pptx_v1 = download_with_fallback("PPT 3（竖版前半）", ppt3_artifact_id, "ppt_v1.pptx", excluded_ids)
        pptx_v2 = download_with_fallback("PPT 4（竖版后半）", ppt4_artifact_id, "ppt_v2.pptx", excluded_ids)
        
        # ─── Step 8: 合并 PPTX（横版 + 竖版分别合并）─────────────────
        print("\n[8/10] 合并 PPTX 并提取图片...")
        
        # 创建输出目录：/Users/gray/Documents/A股研报/<笔记本名称>/
        final_output_dir = DEFAULT_OUTPUT_DIR / notebook_title
        final_output_dir.mkdir(parents=True, exist_ok=True)
        print(f"   📁 输出目录: {final_output_dir}")
        
        # ── 横版处理 ────────────────────────────────────────────────
        print("\n   📐 处理横版 PPT（16:9）...")
        images_dir_h = final_output_dir / "images_landscape"
        images_dir_h.mkdir(exist_ok=True)
        
        print("      → 提取 PPT 1（横版前半）图片...")
        images_h1 = extract_images_from_pptx(pptx_h1, images_dir_h)
        print(f"      ✅ 提取 {len(images_h1)} 张")
        
        print("      → 提取 PPT 2（横版后半）图片...")
        temp_dir_h2 = temp_dir / "images_h2"
        temp_dir_h2.mkdir(exist_ok=True)
        images_h2 = extract_images_from_pptx(pptx_h2, temp_dir_h2)
        
        # 重命名并移动（接在 h1 后面）
        for img in images_h2:
            new_name = f"P{len(images_h1) + int(img.stem[1:])}.png"
            img.rename(images_dir_h / new_name)
        print(f"      ✅ 提取 {len(images_h2)} 张")
        
        # 创建横版合并 PPTX
        all_images_h = sorted(images_dir_h.glob("P*.png"), key=lambda x: int(x.stem[1:]))
        final_pptx_h = final_output_dir / f"{notebook_title}_横版.pptx"
        create_pptx_from_images(all_images_h, final_pptx_h, orientation="landscape")
        
        # ── 竖版处理 ────────────────────────────────────────────────
        print("\n   📱 处理竖版 PPT（9:16）...")
        images_dir_v = final_output_dir / "images_portrait"
        images_dir_v.mkdir(exist_ok=True)
        
        print("      → 提取 PPT 3（竖版前半）图片...")
        images_v1 = extract_images_from_pptx(pptx_v1, images_dir_v)
        print(f"      ✅ 提取 {len(images_v1)} 张")
        
        print("      → 提取 PPT 4（竖版后半）图片...")
        temp_dir_v2 = temp_dir / "images_v2"
        temp_dir_v2.mkdir(exist_ok=True)
        images_v2 = extract_images_from_pptx(pptx_v2, temp_dir_v2)
        
        # 重命名并移动（接在 v1 后面）
        for img in images_v2:
            new_name = f"P{len(images_v1) + int(img.stem[1:])}.png"
            img.rename(images_dir_v / new_name)
        print(f"      ✅ 提取 {len(images_v2)} 张")
        
        # 创建竖版合并 PPTX
        all_images_v = sorted(images_dir_v.glob("P*.png"), key=lambda x: int(x.stem[1:]))
        final_pptx_v = final_output_dir / f"{notebook_title}_竖版.pptx"
        create_pptx_from_images(all_images_v, final_pptx_v, orientation="portrait")
        
        # ─── Step 9: Logo 遮盖 ──────────────────────────────────────
        print("\n[9/10] 遮盖 NotebookLM logo...")
        
        cover_h = cover_logo_on_images(images_dir_h, logo_path)
        if cover_h != len(all_images_h):
            print(f"   ⚠️ 横版部分图片遮盖失败: {cover_h}/{len(all_images_h)}")
        
        cover_v = cover_logo_on_images(images_dir_v, logo_path)
        if cover_v != len(all_images_v):
            print(f"   ⚠️ 竖版部分图片遮盖失败: {cover_v}/{len(all_images_v)}")
        
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
        print(f"   📦 横版 PPTX: {final_pptx_h}")
        print(f"   📦 竖版 PPTX: {final_pptx_v}")
        print(f"   🖼️  横版图片: {images_dir_h} ({len(all_images_h)} 张)")
        print(f"   🖼️  竖版图片: {images_dir_v} ({len(all_images_v)} 张)")
        print(f"   📊 总页数: {len(all_images_h)} 横版 + {len(all_images_v)} 竖版")
        print("="*60)
        
        return {
            "pptx_landscape": str(final_pptx_h),
            "pptx_portrait": str(final_pptx_v),
            "images_dir_landscape": str(images_dir_h),
            "images_dir_portrait": str(images_dir_v),
            "page_count_landscape": len(all_images_h),
            "page_count_portrait": len(all_images_v),
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
