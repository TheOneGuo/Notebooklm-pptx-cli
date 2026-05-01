# NotebookLM → PPTX → 配音 全自动流水线

> **版本**: v1.4.0 | **仓库**: [TheOneGuo/Notebooklm-pptx-cli](https://github.com/TheOneGuo/Notebooklm-pptx-cli) | **许可证**: MIT

一键完成 Markdown 研报 → **NotebookLM PPT 生成** → 图片提取 → Logo 遮盖 → **AI 口播稿生成** → **语音克隆配音** 的完整自动化流水线。

**同时生成横版（16:9）和竖版（9:16）两套 PPT**，适配不同播放场景。

---

## ✨ 功能特性

| 特性 | 说明 |
|------|------|
| 📄 **MD → PPT 一键转换** | 上传 Markdown 研报，自动完成全流程 |
| 🖼️ **双版式输出** | 横版 16:9 + 竖版 9:16 同时生成（各含完整内容） |
| ⚡ **4 任务并行** | 横版前/后半 + 竖版前/后半，最大化利用 NotebookLM 并行能力 |
| 🎨 **高端暗黑机械风格** | 黑金渐变背景、红铜金属 3D 图表、Neon Glow 光效 |
| 🛡️ **Logo 遮盖** | 自动用前瞻客 Logo 覆盖 NotebookLM 品牌标识 |
| 🌐 **强制中文** | 所有提示词含中文约束，确保 PPT 全中文输出 |
| 🎙️ **AI 口播稿生成** | 基于 MD 内容自动生成抖音风格口播脚本（MiMo-v2.5-pro） |
| 🔊 **语音克隆配音** | MiMo VoiceClone TTS 合成 + 1.5 倍速输出 |

---

## 🚀 快速开始

### 环境要求

```bash
python >= 3.11

# NotebookLM CLI（安装在独立虚拟环境）
~/.qclaw/workspace-agent-ef704e53/.venv/bin/notebooklm

# Python 依赖
pip install python-pptx>=1.0.0 Pillow>=10.0.0 openai>=1.0.0

# 系统依赖（配音加速用）
brew install ffmpeg
```

### 安装

```bash
git clone https://github.com/TheOneGuo/Notebooklm-pptx-cli.git
cd Notebooklm-pptx-cli
pip install python-pptx Pillow openai
```

### 使用方法

```bash
# 完整流水线：MD → PPT（默认 30 页）
python scripts/nb2pptx.py your_report.md

# 自定义参数
python scripts/nb2pptx.py your_report.md \
    --title "AI算力液冷赛道报告" \
    --pages 40 \
    --output-dir ~/Desktop/output \
    --logo ~/path/to/logo.png \
    --keep-temp

# 口播稿生成 + 语音合成
python scripts/md2voiceover.py \
    --md your_report.md \
    --images ~/Documents/A股研报/报告名/images_landscape/ \
    --output-dir ~/Documents/A股研报/报告名/配音/
```

### 参数说明（nb2pptx.py）

| 参数 | 缩写 | 默认值 | 说明 |
|------|------|--------|------|
| `md_file` | - | （必填） | Markdown 文件路径 |
| `--title` | `-t` | 文件名 | PPT 标题 |
| `--pages` | `-p` | `30` | 目标页数 |
| `--output-dir` | `-o` | `~/Documents/A股研报/<笔记本名>/` | 输出目录 |
| `--logo` | `-l` | `~/Documents/前瞻客/logo和表情/前瞻客logo底图.png` | Logo 底图路径 |
| `--keep-temp` | - | `false` | 保留临时文件（调试用） |
| `--initial-interval` | - | `540` | 初始等待秒数 |
| `--max-interval` | - | `60` | 轮询间隔秒数 |
| `--timeout` | - | `900` | 总超时秒数 |

---

## 📁 项目结构

```
Notebooklm-pptx-cli/
├── README.md                           # 本文件
├── SKILL.md                            # WorkBuddy Skill 定义
├── notebooklm-anti-crawl-patch.md      # 反爬补强文档
├── .gitignore
├── assets/
│   └── logo.png                        # 前瞻客 Logo 底图
└── scripts/
    ├── nb2pptx.py                      # MD → PPTX 主流水线
    ├── md2voiceover.py                 # 口播稿生成 + 语音合成
    ├── mimo_voice_clone.py             # MiMo VoiceClone TTS 工具
    ├── mimo_voice_config.json          # MiMo API 配置
    └── chatgpt_auto_research.py        # ChatGPT 6 轮自动研究
```

### 输出结构

```
~/Documents/A股研报/<笔记本名称>/
├── <笔记本名称>_横版.pptx          # 横版 16:9 PPTX
├── <笔记本名称>_竖版.pptx          # 竖版 9:16 PPTX
├── images_landscape/               # 横版图片（P1.png ~ P30.png）
├── images_portrait/                # 竖版图片（P1.png ~ P30.png）
├── run_result.json                 # 运行结果（含耗时、警告等）
└── 配音/                           # 口播稿 + 音频（md2voiceover 输出）
    ├── V1-开场.txt
    ├── V1-P1.txt ~ V1-P10.txt
    ├── V1-结尾.txt
    ├── V1-开场_1.5x.wav
    └── ...
```

---

## 🔧 核心流程（nb2pptx.py · 10 步）

```
Step 1  创建 NotebookLM 笔记本
  ↓
Step 2  上传 MD 来源并重命名为 "a"
  ↓
Step 3  AI 提取主题 → 重命名笔记本
  ↓
Step 4  生成 PPT 大纲笔记（带风格要求 + 画面构图描述）
  ↓
Step 5  大纲转来源 B（重命名为 "b"）
  ↓
Step 6  ┌─────────────────────────────────────┐
         │  并行提交 4 个 PPT 生成任务          │
         │  • PPT1: 横版前半 (第1-15页)        │
         │  • PPT2: 横版后半 (第16-30页)       │
         │  • PPT3: 竖版前半 (第1-15页)        │
         │  • PPT4: 竖版后半 (第16-30页)       │
         └─────────────────────────────────────┘
  ↓
Step 7  手动轮询等待全部 artifact 完成
  ↓
Step 8  下载 PPT → 提取图片 → 遮盖 Logo → 合并为 PPTX
  ↓
Step 9  （Logo 遮盖已在 Step 8 中完成）
  ↓
Step 10 清理临时文件 + 删除 NotebookLM 笔记本
```

---

## 🎙️ 口播稿 + 配音（md2voiceover.py）

### 流程

```
1. 读取 MD 原文 → 按页数分割
2. 调用 MiMo-v2.5-pro 生成视频规划（3 个抖音视频 + 片头片尾）
3. 逐页生成口播脚本（~60s/页，含抖音钩子 + 换气停顿）
4. MiMo VoiceClone TTS 合成语音
5. ffmpeg 1.5 倍速加速
```

### 配置

```json
// mimo_voice_config.json
{
  "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
  "api_key": "your-api-key",
  "model": "mimo-v2.5-tts-voiceclone",
  "voice_sample": "voice_sample.wav"
}
```

语音样本需 30 秒以上清晰录音（MP3/WAV 格式）。

---

## 📝 更新日志

### v1.4.0 (2026-05-01)

**🆕 新功能**
- **AI 口播稿生成**：`md2voiceover.py` 基于 MiMo-v2.5-pro 从 MD 内容生成抖音风格口播脚本
- **语音克隆配音**：`mimo_voice_clone.py` MiMo VoiceClone TTS + ffmpeg 1.5 倍速
- **ChatGPT 自动研究**：`chatgpt_auto_research.py` 6 轮行业深度分析自动化
- **运行结果 JSON**：每次运行自动保存 `run_result.json`（含耗时、步骤计时、警告）

**🔧 改进**
- PPT 提示词去重：4 段 ~90% 重复的 prompt 提取为 `build_ppt_prompt()` 公共函数
- 前置依赖检查：启动时检查 python-pptx、Pillow、ffmpeg，缺失时给出明确提示
- Logo 遮盖顺序修正：在 PPTX 创建**前**先遮盖图片，确保最终 PPTX 中的图片已覆盖
- `--output-dir` 参数真正生效（之前被硬编码忽略）
- 步骤计时：每个 Step 打印耗时，结束时汇总

**🐛 修复**
- `chatgpt_auto_research.py`: `result2` 未定义导致 NameError
- `chatgpt_auto_research.py`: `_extract_latest_response` fallback 引用错误变量
- `--output-dir` 参数被忽略（硬编码为默认目录）

**🗑️ 移除**
- 死代码：`merge_pptx_files()`（已被图片提取+重建方式替代）
- 死代码：旧版 `wait_for_artifact()`（已被新轮询逻辑替代）

---

### v1.3.0 (2026-04-28)

- 代码级免责声明硬保障：新增 `draw_disclaimer()` 函数
- 提示词架构优化：拆分为 `style_desc` / `font_rules` / `disclaimer` 三个统一变量
- 通用封杀令：禁止所有非标准页脚文字

---

### v1.2.1 (2026-04-24)

- 大纲提示词新增每页"画面构图描述"要求
- 4 个提示词统一注入字体规范
- 竖版合并顺序修复（方案 C 排除已知 artifact IDs）

---

### v1.2.0 (2026-04-24)

- 双版本输出：横版(16:9) + 竖版(9:16) 同时生成
- 4 任务并行：PPT1/PPT2（横版）+ PPT3/PPT4（竖版）
- 竖屏专属优化：9:16 强制比例 + F 型竖向阅读动线

---

## ⚡ 性能建议

| 场景 | 建议 |
|------|------|
| 总页数 | 不超过 40 页（4 任务并行资源占用大） |
| 初始等待 | 540s（9 分钟静默等待 NotebookLM 生成） |
| 总超时 | 900s（15 分钟） |
| Chrome Debug | 需保持运行（端口 9222），用于反爬绕过 |

---

## 🔗 相关链接

- **GitHub 仓库**: [TheOneGuo/Notebooklm-pptx-cli](https://github.com/TheOneGuo/Notebooklm-pptx-cli)
- **NotebookLM CLI**: 基于 `notebooklm_cdp_cli` 的反爬增强版
- **MiMo 开放平台**: [小米 MiMo TTS](https://xiaomimimo.com)
- **使用平台**: 前瞻客 Foresig — A股 / 美股 / 贵金属金融数据与内容交付平台

---

## 📄 许可证

MIT License © 2026 TheOneGuo / 前瞻客 Foresig
