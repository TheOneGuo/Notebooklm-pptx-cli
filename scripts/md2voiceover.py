#!/usr/bin/env python3
"""
MD → 视频口播稿 + 配音 一体化流水线

Step 5: 读取PPT图片 + MD原文 → mimo-v2.5-pro 生成口播稿
Step 6: 口播稿 → MiMo VoiceClone TTS → ffmpeg 1.5倍速 + 双声道

输出：
  - V1-P1.txt ~ V3-P10.txt（每页口播稿）
  - V1-开场.txt, V1-结尾.txt, ...（视频开场结尾）
  - V1-P1.wav ~ V3-P10.wav（每页配音，1.5倍速 + 双声道）
  - 合集-开场.txt, 合集-结尾.txt

用法:
    python md2voiceover.py <md_file> [--images-dir <dir>] [--output-dir <dir>]
    python md2voiceover.py <md_file> --scripts-dir <dir> --synthesize-only
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

try:
    import openai
except ImportError:
    openai = None  # 延迟报错：仅在实际调用 TTS/LLM 时报错，--help 可用

# ═══════════════════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════════════════

WORKSPACE = Path(__file__).parent
CONFIG_PATH = WORKSPACE / "mimo_voice_config.json"
SPEED = 1.5
SCRIPT_GEN_MODEL = "mimo-v2.5-pro"
MAX_RETRIES = 3

# ═══════════════════════════════════════════════════════════════════════
# MiMo Script Generator (Step 5)
# ═══════════════════════════════════════════════════════════════════════

class MiMoScriptGenerator:
    """用 mimo-v2.5-pro 生成口播稿"""

    def __init__(self, config_path: Path = CONFIG_PATH):
        if openai is None:
            raise ImportError("需要安装 openai: pip install openai")
        config = json.loads(config_path.read_text())
        self.client = openai.OpenAI(
            api_key=config["api_key"],
            base_url=config["base_url"],
        )

    def _call(self, messages: list, max_tokens: int = 4096) -> str:
        """调用 mimo-v2.5-pro，带重试"""
        for attempt in range(MAX_RETRIES):
            try:
                resp = self.client.chat.completions.create(
                    model=SCRIPT_GEN_MODEL,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=0.8,
                )
                return resp.choices[0].message.content.strip()
            except Exception as e:
                if attempt < MAX_RETRIES - 1:
                    print(f"   ⚠️ API 调用失败，重试 {attempt+2}/{MAX_RETRIES}: {e}")
                    time.sleep(3)
                else:
                    raise

    def analyze_md_for_videos(self, md_content: str, page_count: int) -> Dict:
        """分析 MD 内容，规划3个视频的页数分配和主题"""
        split_prompt = f"""你是短视频内容策划专家。下面是一份A股行业研究报告，总共 {page_count} 页PPT。
请规划分成3个抖音短视频（每个约10分钟，每页口播约60秒）。
要求：
1. 根据内容逻辑自然切分
2. 每个视频有独立主题线
3. 页数少的增加深度，页数多的精炼

报告前3000字：
{md_content[:3000]}

严格输出JSON，无其他内容：
{{"report_title":"标题","videos":[{{"title":"V1标题","pages":"1-{page_count//3}","theme":"主题","钩子":"钩子"}},{{"title":"V2标题","pages":"{page_count//3+1}-{page_count*2//3}","theme":"主题","hook":"钩子"}},{{"title":"V3标题","pages":"{page_count*2//3+1}-{page_count}","theme":"主题","hook":"钩子"}}]}}"""

        result = self._call([{"role": "user", "content": split_prompt}], max_tokens=4096)

        # 提取JSON
        if "```" in result:
            result = result.split("```")[1]
            if result.startswith("json"):
                result = result[4:]
        result = result.strip()

        try:
            return json.loads(result)
        except json.JSONDecodeError:
            start = result.find("{")
            end = result.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(result[start:end])
                except json.JSONDecodeError:
                    # 尝试修复截断的JSON: 补全缺失的括号
                    partial = result[start:end]
                    open_braces = partial.count('{') - partial.count('}')
                    open_brackets = partial.count('[') - partial.count(']')
                    # 截断到最后一个完整对象
                    last_complete = partial.rfind('}')
                    if last_complete > 0:
                        # 找到最后一个完整的 video 对象
                        fixed = partial[:last_complete+1]
                        # 补全数组和对象
                        fixed += ']' * max(0, open_brackets)
                        fixed += '}' * max(0, open_braces - 1)
                        try:
                            return json.loads(fixed)
                        except:
                            pass
            # 最终回退: 用默认分配
            print(f"   ⚠️ JSON解析失败，使用默认分配")
            return self._default_plan(page_count)

    def _default_plan(self, page_count: int) -> Dict:
        """JSON解析失败时的默认视频分配"""
        ppv = page_count // 3
        return {
            "report_title": "行业研究报告",
            "videos": [
                {"title": "行业格局与技术突破", "pages": f"1-{ppv}", "theme": "行业概况", "hook": "数据冲击"},
                {"title": "产业链核心标的", "pages": f"{ppv+1}-{ppv*2}", "theme": "公司分析", "hook": "龙头对比"},
                {"title": "投资策略与风险", "pages": f"{ppv*2+1}-{page_count}", "theme": "投资建议", "hook": "收益测算"},
            ]
        }

    def generate_page_script(self, md_content: str, page_text: str,
                             page_num: int, total_pages: int,
                             video_info: Dict, prev_ending: str = "") -> str:
        """为单页生成口播稿（~60秒，含钩子和换气停顿）

        Args:
            md_content: 完整MD原文（上下文参考）
            page_text: 本页对应的MD段落
            page_num: 当前页码
            total_pages: 总页数
            video_info: 视频规划信息
            prev_ending: 上一页口播结尾
        """

        context = f"""你是专业财经短视频口播撰稿人，风格：口语化、有节奏感、专业不失吸引力。

当前视频：{video_info['title']}
当前是第 {page_num}/{total_pages} 页
{"上一页结尾：" + prev_ending if prev_ending else "这是视频第一页"}

本页内容（来自研究报告）：
{page_text}

报告全文（参考上下文，不要照读）：
{md_content[:6000]}

请根据本页内容，写一段约250-320字的口播稿（对应约60秒朗读时长）。

要求：
1. 开头5秒必须有爆款钩子（数据冲击、反常识、悬念、利益相关任选其一）
2. 这是视频口播版，绝对不要出现"这一页""如图所示""PPT中"等讲PPT的措辞
3. 口语化但专业，像在和观众聊天
4. 每80-120字左右换一次气，用空行分隔（总共2-3次换气）
5. 结尾要承上启下或留下思考
6. 所有内容用中文
7. 不要加标题、页码等标记，纯口播文字

输出格式：
[PAGE:{page_num}]
（口播文字，换气用空行分隔）"""

        messages = [{"role": "user", "content": context}]
        return self._call(messages, max_tokens=4096)

    def generate_video_opening(self, video_title: str, video_theme: str,
                               hook_idea: str, video_num: int,
                               prev_video_ending: str = "") -> str:
        """生成视频开场白（~15-20秒）"""
        prompt = f"""写一个抖音财经短视频的开场白，约60-80字。

视频标题：{video_title}
主题：{video_theme}
开场钩子思路：{hook_idea}
{"上一个视频结尾：" + prev_video_ending if prev_video_ending else "这是第一个视频"}

要求：
1. 前3秒必须抓住注意力（数据冲击/提问/反转）
2. 快速交代这个视频要讲什么
3. 用"我"不用"我们"，口语化
4. 纯中文
5. 不要加任何标记，纯口播文字"""

        return self._call([{"role": "user", "content": prompt}], max_tokens=2048)

    def generate_video_ending(self, video_title: str, video_theme: str,
                              video_num: int, is_last: bool = False,
                              next_video_title: str = "") -> str:
        """生成视频结尾（~10-15秒）"""
        if is_last:
            prompt = f"""写一个抖音财经短视频的结尾，约40-60字。

视频标题：{video_title}
主题：{video_theme}
这是系列最后一个视频。

要求：
1. 总结核心观点
2. 引导点赞/收藏/关注
3. 口语化，不要官方腔
4. 纯中文
5. 不要加标记，纯口播文字"""
        else:
            prompt = f"""写一个抖音财经短视频的结尾，约40-60字。

视频标题：{video_title}
主题：{video_theme}
下一个视频标题：{next_video_title}

要求：
1. 总结本集要点
2. 为下一个视频留悬念，让观众想继续看
3. 口语化
4. 纯中文
5. 不要加标记，纯口播文字"""

        return self._call([{"role": "user", "content": prompt}], max_tokens=2048)

    def generate_combined_intro(self, report_title: str, video_titles: List[str]) -> str:
        """生成合集版开场白"""
        prompt = f"""写一个抖音财经长视频（合集版）的开场白，约80-100字。

报告主题：{report_title}
分集标题：{' / '.join(video_titles)}

要求：
1. 告诉观众这是一个完整系列的合集版
2. 快速预告整体内容亮点
3. 口语化，有节奏感
4. 纯中文
5. 不要加标记，纯口播文字"""

        return self._call([{"role": "user", "content": prompt}], max_tokens=2048)


# ═══════════════════════════════════════════════════════════════════════
# Pipeline: 生成全部口播稿
# ═══════════════════════════════════════════════════════════════════════

import re


def split_md_by_pages(md_content: str, page_count: int) -> List[str]:
    """将 MD 内容按页数均匀切分"""
    # 先尝试按 ## 标题切分
    sections = re.split(r'\n(?=#{1,3}\s)', md_content)
    sections = [s.strip() for s in sections if s.strip()]

    if len(sections) >= page_count:
        # 段落数 >= 页数，按段落分组
        pages = []
        per_page = len(sections) / page_count
        for i in range(page_count):
            start = int(i * per_page)
            end = int((i + 1) * per_page)
            pages.append("\n\n".join(sections[start:end]))
        return pages
    else:
        # 段落数 < 页数，按字符数均匀切分
        text = md_content
        total_len = len(text)
        chunk_size = total_len // page_count
        pages = []
        for i in range(page_count):
            start = i * chunk_size
            end = start + chunk_size if i < page_count - 1 else total_len
            # 在段落边界切分
            if i < page_count - 1:
                newline_pos = text.rfind("\n\n", start, end + chunk_size // 2)
                if newline_pos > start:
                    end = newline_pos
            pages.append(text[start:end].strip())
        return pages


def generate_all_scripts(md_path: Path, images_dir: Path, output_dir: Path):
    """完整 pipeline：读MD → LLM生成全部口播稿 → 保存txt"""

    md_content = md_path.read_text()
    images = sorted(images_dir.glob("P*.png"), key=lambda x: int(x.stem[1:]))
    page_count = len(images)

    if page_count == 0:
        print(f"❌ 图片目录为空: {images_dir}")
        sys.exit(1)

    print(f"📄 MD: {md_path}")
    print(f"🖼️  图片: {images_dir} ({page_count}页)")
    print(f"📁 输出: {output_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    gen = MiMoScriptGenerator()

    # 切分MD内容
    page_texts = split_md_by_pages(md_content, page_count)
    print(f"📝 MD内容已切分为 {len(page_texts)} 段")

    # ── Phase 1: 视频规划 ──
    print("\n📊 [Phase 1] 分析报告内容，规划视频分配...")
    plan = gen.analyze_md_for_videos(md_content, page_count)
    report_title = plan["report_title"]
    videos = plan["videos"]

    # 解析每个视频的页码范围
    video_pages = []
    for v in videos:
        pages_str = v["pages"]  # e.g. "1-10"
        parts = pages_str.replace(" ", "").split("-")
        start, end = int(parts[0]), int(parts[-1])
        v["start"] = start
        v["end"] = end
        video_pages.append(list(range(start, end + 1)))

    for i, v in enumerate(videos):
        print(f"   V{i+1}: {v['title']} (P{v['start']}-P{v['end']}, {v['end']-v['start']+1}页)")

    # ── Phase 2: 逐页生成口播稿 ──
    print(f"\n✍️  [Phase 2] 逐页生成口播稿...")
    all_scripts = {}  # {filename: text}

    for vid_idx, v in enumerate(videos):
        vid_num = vid_idx + 1
        pages = video_pages[vid_idx]
        print(f"\n   📹 V{vid_num}: {v['title']}")

        for i, page_num in enumerate(pages):
            if page_num > len(page_texts):
                print(f"      ⚠️ P{page_num} 超出范围，跳过")
                continue

            prev_ending = ""
            if i > 0:
                prev_key = f"V{vid_num}-P{pages[i-1]}.txt"
                if prev_key in all_scripts:
                    prev_lines = [l for l in all_scripts[prev_key].split("\n") if l.strip()]
                    prev_ending = " ".join(prev_lines[-2:]) if len(prev_lines) >= 2 else ""

            print(f"      P{page_num}...", end="", flush=True)
            script = gen.generate_page_script(
                md_content, page_texts[page_num - 1],
                page_num, page_count, v, prev_ending
            )
            filename = f"V{vid_num}-P{i+1}.txt"
            all_scripts[filename] = script
            (output_dir / filename).write_text(script)
            print(f" ✅ ({len(script)}字)")

            time.sleep(1)

    # ── Phase 3: 视频开场/结尾 ──
    print(f"\n🎬 [Phase 3] 生成视频开场/结尾...")

    for vid_idx, v in enumerate(videos):
        vid_num = vid_idx + 1
        is_last = (vid_idx == len(videos) - 1)
        next_title = videos[vid_idx + 1]["title"] if not is_last else ""

        # 开场
        prev_ending = ""
        if vid_idx > 0:
            prev_key = f"V{vid_num-1}-结尾.txt"
            if prev_key in all_scripts:
                prev_ending = all_scripts[prev_key]

        print(f"   V{vid_num} 开场...", end="", flush=True)
        opening = gen.generate_video_opening(
            v["title"], v["theme"], v["hook"], vid_num, prev_ending
        )
        all_scripts[f"V{vid_num}-开场.txt"] = opening
        (output_dir / f"V{vid_num}-开场.txt").write_text(opening)
        print(f" ✅ ({len(opening)}字)")

        # 结尾
        print(f"   V{vid_num} 结尾...", end="", flush=True)
        ending = gen.generate_video_ending(
            v["title"], v["theme"], vid_num, is_last, next_title
        )
        all_scripts[f"V{vid_num}-结尾.txt"] = ending
        (output_dir / f"V{vid_num}-结尾.txt").write_text(ending)
        print(f" ✅ ({len(ending)}字)")

        time.sleep(1)

    # ── Phase 4: 合集版 ──
    print(f"\n📦 [Phase 4] 生成合集版开场...")

    print(f"   合集开场...", end="", flush=True)
    combined_intro = gen.generate_combined_intro(report_title, [v["title"] for v in videos])
    all_scripts["合集-开场.txt"] = combined_intro
    (output_dir / "合集-开场.txt").write_text(combined_intro)
    print(f" ✅ ({len(combined_intro)}字)")

    # 合集结尾复用 V3 结尾
    v3_ending = all_scripts.get("V3-结尾.txt", "")
    all_scripts["合集-结尾.txt"] = v3_ending
    (output_dir / "合集-结尾.txt").write_text(v3_ending)

    # ── 输出统计 ──
    print(f"\n{'='*50}")
    print(f"✅ 口播稿生成完成")
    print(f"   报告标题: {report_title}")
    print(f"   总文件数: {len(all_scripts)}")
    print(f"   输出目录: {output_dir}")
    print(f"   文件列表:")
    for f in sorted(output_dir.glob("*.txt")):
        chars = len(f.read_text())
        print(f"      {f.name} ({chars}字)")

    return all_scripts


# ═══════════════════════════════════════════════════════════════════════
# MiMo VoiceClone TTS (Step 6)
# ═══════════════════════════════════════════════════════════════════════

class VoiceCloneTTS:
    """MiMo-V2.5-TTS-VoiceClone 封装"""

    def __init__(self, config_path: Path = CONFIG_PATH):
        if openai is None:
            raise ImportError("需要安装 openai: pip install openai")
        config = json.loads(config_path.read_text())
        self.client = openai.OpenAI(
            api_key=config["api_key"],
            base_url=config["base_url"],
        )
        voice_path = config["voice_sample_path"]
        with open(voice_path, "rb") as f:
            voice_b64 = base64.b64encode(f.read()).decode()
        self.voice_url = f"data:audio/wav;base64,{voice_b64}"

    def synthesize(self, text: str, output_path: Path,
                   instruction: str = "用自然流畅的语气朗读") -> bool:
        try:
            resp = self.client.chat.completions.create(
                model="mimo-v2.5-tts-voiceclone",
                messages=[
                    {"role": "user", "content": instruction},
                    {"role": "assistant", "content": text},
                ],
                extra_body={"audio": {"format": "wav", "voice": self.voice_url}},
            )
            audio_data = resp.choices[0].message.audio.data
            audio_bytes = base64.b64decode(audio_data)
            output_path.write_bytes(audio_bytes)
            return True
        except Exception as e:
            print(f"   ❌ 合成失败: {e}")
            return False


def speed_up_audio(input_path: Path, output_path: Path, speed: float = SPEED) -> bool:
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(input_path),
            "-filter:a", f"atempo={speed}",
            "-ac", "2",
            str(output_path),
        ],
        capture_output=True,
    )
    if result.returncode != 0:
        print(f"   ⚠️ ffmpeg 加速/双声道处理失败: {result.stderr.decode()[:200]}")
        return False
    return True


# ═══════════════════════════════════════════════════════════════════════
# 批量合成配音
# ═══════════════════════════════════════════════════════════════════════

def batch_synthesize(scripts_dir: Path, output_dir: Path, speed: float = SPEED):
    tts = VoiceCloneTTS()
    txt_files = sorted(scripts_dir.glob("*.txt"), key=lambda x: x.name)
    if not txt_files:
        print(f"❌ 未找到口播稿文件: {scripts_dir}")
        return

    print(f"\n🎤 批量合成配音")
    print(f"   口播稿: {scripts_dir}")
    print(f"   输出: {output_dir}")
    print(f"   倍速: {speed}x | 文件数: {len(txt_files)}")

    output_dir.mkdir(parents=True, exist_ok=True)
    success = failed = 0

    for i, txt_file in enumerate(txt_files, 1):
        text = txt_file.read_text().strip()
        if not text:
            print(f"   ⏭️  [{i}/{len(txt_files)}] {txt_file.name} (空)")
            continue

        stem = txt_file.stem
        raw_wav = output_dir / f"{stem}_raw.wav"
        final_wav = output_dir / f"{stem}.wav"

        print(f"   🔊 [{i}/{len(txt_files)}] {stem} ({len(text)}字)...", end="", flush=True)

        if not tts.synthesize(text, raw_wav):
            failed += 1
            print(" ❌")
            continue

        if not speed_up_audio(raw_wav, final_wav, speed):
            failed += 1
            print(" ❌ (加速失败)")
            continue
        raw_wav.unlink(missing_ok=True)

        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(final_wav)],
            capture_output=True, text=True,
        )
        if result.returncode != 0 or not result.stdout.strip():
            failed += 1
            print(f" ❌ (ffprobe 失败)")
            continue
        try:
            duration = float(json.loads(result.stdout)["format"]["duration"])
            print(f" ✅ {duration:.1f}s")
        except (KeyError, json.JSONDecodeError, ValueError):
            failed += 1
            print(" ❌ (时长解析失败)")
            continue

        success += 1
        if i < len(txt_files):
            time.sleep(1)

    print(f"\n   📊 完成: {success}成功, {failed}失败")


# ═══════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MD → 视频口播稿 + 配音 流水线")
    parser.add_argument("md_file", help="Markdown 文件路径")
    parser.add_argument("--images-dir", "-i", type=Path, help="图片目录（默认自动推断）")
    parser.add_argument("--output-dir", "-o", type=Path, help="输出目录（默认自动推断）")
    parser.add_argument("--speed", "-s", type=float, default=SPEED, help=f"倍速（默认 {SPEED}）")
    parser.add_argument("--scripts-dir", type=Path, help="已有口播稿目录（跳过生成，直接配音）")
    parser.add_argument("--synthesize-only", action="store_true", help="仅合成配音")

    args = parser.parse_args()
    md_path = Path(args.md_file).expanduser().resolve()
    if not md_path.exists():
        print(f"❌ 文件不存在: {md_path}")
        sys.exit(1)

    md_stem = md_path.stem
    default_base = Path.home() / "Documents" / "A股研报" / md_stem

    if args.synthesize_only and args.scripts_dir:
        output_dir = args.output_dir or (args.scripts_dir.parent / "配音")
        batch_synthesize(args.scripts_dir, output_dir, args.speed)
    else:
        images_dir = args.images_dir or (default_base / "images_landscape")
        output_dir = args.output_dir or (default_base / "配音")

        if not images_dir.exists():
            print(f"❌ 图片目录不存在: {images_dir}")
            print(f"   请先运行 nb2pptx.py 生成图片")
            sys.exit(1)

        # Step 5: 生成口播稿
        scripts = generate_all_scripts(md_path, images_dir, output_dir)

        # Step 6: 合成配音
        print(f"\n🎤 [Step 6] 开始合成配音...")
        batch_synthesize(output_dir, output_dir / "audio", args.speed)
