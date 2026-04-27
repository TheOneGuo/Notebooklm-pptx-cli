# NotebookLM → PPTX 流水线 (nb2pptx)

> **版本**: v1.3.0 | **仓库**: [TheOneGuo/Notebooklm-pptx-cli](https://github.com/TheOneGuo/Notebooklm-pptx-cli) | **许可证**: MIT

一键完成 Markdown 研报 → **NotebookLM PPT 生成** → 图片提取 → Logo 遮盖 → 免责声明绘制 → 最终 PPTX 的完整自动化流水线。

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
| ⚠️ **免责声明硬保障** | PIL 代码级强制绘制标准股市免责声明（双重保险） |
| 🔒 **页脚封杀令** | 自动清除所有非标准页脚文字（品牌声明、保密声明等） |
| 🌐 **强制中文** | 所有提示词含中文约束，确保 PPT 全中文输出 |

---

## 🚀 快速开始

### 环境要求

```bash
# Python
python >= 3.11

# NotebookLM CLI（安装在独立虚拟环境）
~/.qclaw/workspace-agent-ef704e53/.venv/bin/notebooklm

# Python 依赖
pip install python-pptx>=1.0.0 Pillow>=10.0.0
```

### 安装

```bash
# 克隆仓库
git clone https://github.com/TheOneGuo/Notebooklm-pptx-cli.git
cd Notebooklm-pptx-cli

# 安装依赖
pip install -r requirements.txt  # 或手动安装 python-pptx Pillow
```

### 使用方法

```bash
# 基本用法（默认 30 页）
python scripts/nb2pptx.py your_report.md

# 自定义参数
python scripts/nb2pptx.py your_report.md \
    --title "AI算力液冷赛道报告" \
    --pages 40 \
    --output-dir ~/Desktop/output \
    --logo ~/path/to/logo.png \
    --keep-temp
```

### 参数说明

| 参数 | 缩写 | 默认值 | 说明 |
|------|------|--------|------|
| `md_file` | - | （必填） | Markdown 文件路径 |
| `--title` | `-t` | 文件名 | PPT 标题 |
| `--pages` | `-p` | `30` | 目标页数 |
| `--output-dir` | `-o` | `~/Documents/A股研报/<笔记本名>/` | 输出目录 |
| `--logo` | `-l` | `assets/logo.png` | Logo 底图路径 |
| `--keep-temp` | - | `false` | 保留临时文件（调试用） |
| `--initial-interval` | - | `540` | 初始等待秒数 |
| `--max-interval` | - | `60` | 轮询间隔秒数 |
| `--timeout` | - | `900` | 总超时秒数 |

---

## 📁 项目结构

```
nb2pptx/
├── README.md                          # 本文件
├── SKILL.md                           # WorkBuddy Skill 定义
├── notebooklm-anti-crawl-patch.md     # 反爬补强文档
├── .gitignore
├── assets/
│   └── logo.png                       # 前瞻客 Logo 底图
└── scripts/
    └── nb2pptx.py                     # 主流水线脚本（核心）
```

### 输出结构

```
~/Documents/A股研报/<笔记本名称>/
├── <笔记本名称>.pptx              # 横版 16:9 PPTX
├── images_landscape/              # 横版图片（P1.png ~ P30.png）
├── <笔记本名称>_竖版.pptx         # 竖版 9:16 PPTX
└── images_portrait/               # 竖版图片（P1.png ~ P30.png）
```

---

## 🔧 核心流程（10 步）

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
Step 8  下载横版 PPT → 提取图片 → 合并为 PPTX → 遮盖 Logo → 绘制免责声明
  ↓
Step 9  下载竖版 PPT → 提取图片 → 合并为 PPTX → 遮盖 Logo → 绘制免责声明
  ↓
Step 10 清理临时文件 + 删除 NotebookLM 笔记本
```

---

## 🛡️ 免责声明保障机制

本系统采用**三层保障**确保每张输出图片均包含标准免责声明：

```
┌──────────────────────────────────────────────┐
│ 第1层: 提示词约束                              │
│  要求 NotebookLM 在生成时放置免责声明          │
├──────────────────────────────────────────────┤
│ 第2层: 通用封杀令                              │
│  禁止所有非标准页脚文字（品牌声明、保密声明等）   │
├──────────────────────────────────────────────┤
│ 第3层: draw_disclaimer() 代码级硬绘制           │
│  用 PIL 在图片固定位置直接覆盖标准免责声明        │
│  • 横版(1376×768): 底部右对齐                 │
│  • 竖版(768×1376):   底部居中                  │
│  • 半透明深色背景 + #AAAAAA 暗灰文字            │
└──────────────────────────────────────────────┘
```

**标准免责声明文本**：
> 市场有风险，决策需独立；  
> 股市有风险，入市需谨慎。

---

## 📝 更新日志

### v1.3.0 (2026-04-28)

**🆕 新功能**
- **代码级免责声明硬保障**：新增 `draw_disclaimer()` 函数，在 Logo 遮盖后用 PIL 直接在图片固定位置绘制标准免责声明
- **通用封杀令**：提示词中全面禁止所有非标准页脚文字（品牌声明、权威背书、保密声明、来源标注等）

**🔧 改进**
- **提示词架构优化**：拆分为 `style_desc` / `font_rules` / `disclaimer` 三个统一变量，4 个提示词共用
- **风格描述恢复完整**：保留"权威/严谨与精密"等强力风格词（配合代码层兜底，不再需要删减）

**🐛 修复**
- 解决 NotebookLM 将风格关键词转化为页脚品牌声明的问题（如"高端商业咨询顾问系统研究"）

---

### v1.2.1 (2026-04-24)

**🐛 修复**
- 排版粗糙、无画面描述 → 大纲提示词新增每页"画面构图描述"要求
- 字体凌乱混排变形 → 4 个提示词统一注入字体规范（无衬线黑体 + 字号体系）
- 竖版合并顺序错乱（第1页跑到第16页）→ 方案 C 排除所有已知 artifact IDs

---

### v1.2.0 (2026-04-24)

**🆕 新功能**
- **双版本输出**：同时生成横版(16:9) + 竖版(9:16) 两套 PPT
- **4 任务并行**：PPT1/PPT2（横版）+ PPT3/PPT4（竖版）同时提交
- **竖屏专属优化**：9:16 强制比例 + F 型竖向阅读动线

**🔧 改进**
- 新增 `submit_ppt_task()` / `wait_for_artifacts()` / `download_and_merge_ppt_pair()` 辅助函数
- `create_pptx_from_images()` 支持 `aspect_ratio` 参数切换 16:9 / 9:16

**🐛 修复**
- `ask --save-as-note` 超时 → 改为普通 `ask` + 直接提取 answer 字段
- 笔记 ID 获取增加回退逻辑

---

### v1.1.0 (2026-04-23)

**🆕 新功能**
- 来源命名固定化（a = 原始 MD, b = 大纲笔记）
- Step 3 自动提取主题并重命名笔记本
- 强制中文输出（所有提示词含 `[LANGUAGE: CHINESE ONLY]`）
- `artifact wait` 超时 → 改为手动轮询
- `add_source_text` >30000 字符自动回退到临时文件
- artifact ID 差分获取（并行任务区分）

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
- **NotebookLM CLI**: 基于 [`notebooklm_cdp_cli`](https://github.com/) 的反爬增强版
- **使用平台**: 前瞻客 Foresig — A股 / 美股 / 贵金属金融数据与内容交付平台

---

## 📄 许可证

MIT License © 2026 TheOneGuo / 前瞻客 Foresig
