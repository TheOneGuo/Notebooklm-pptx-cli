---
title: "NotebookLM → PPTX 流水线"
description: |
  将 Markdown 研报一键转换为精美 PPT 的完整自动化流水线。
  支持：NotebookLM 笔记本创建、PPT 大纲生成、四任务并行生成（横版+竖版）、
  图片提取合并、前瞻客 Logo 遮盖、临时文件清理。
  同时支持 ChatGPT 网页版自动化 6 轮行业研究 → MD 来源生成 → NotebookLM → PPTX 完整链路。
  触发词：生成PPT、MD转PPT、NotebookLM生成幻灯片、研报转PPT、
  制作PPT、pptx生成、幻灯片制作、nb2pptx、行业研究自动化、6轮分析
author: "Gray / 前瞻客·Foresig"
version: "1.4.0"
---

# NotebookLM → PPTX 流水线 Skill

## 功能概述

一键完成 Markdown 研报 → NotebookLM PPT → 合并去 Logo → 最终 PPTX 的完整流程。
**同时生成横版（16:9）和竖版（9:16）两套 PPT**，适配不同播放场景。

## 核心流程（10 步）

1. **创建笔记本** — 在 NotebookLM 创建新笔记本
2. **上传 MD 来源** — 将 Markdown 文件作为来源 A 上传，并重命名为 `a`
3. **提取主题并重命名** — 从来源提取核心主题，自动重命名笔记本
4. **生成 PPT 大纲** — 向 NotebookLM 提问生成结构化大纲（强制中文 + 风格要求）并保存为笔记
5. **笔记转来源** — 将大纲笔记转为来源 B，重命名为 `b`
6. **并行生成 4 个 PPT** — 同时生成横版前半(PPT1)、横版后半(PPT2)、竖版前半(PPT4)、竖版后半(PPT5)
7. **等待并下载** — 手动轮询 4 个 artifact 状态，避免 `artifact wait` 超时
8. **分别合并 PPTX** — 横版和竖版分别提取图片后重新嵌入
9. **分别 Logo 遮盖** — 两套 PPT 图片分别覆盖前瞻客 Logo
10. **清理** — 删除临时文件和 NotebookLM 笔记本

## 依赖要求

- **Python**: 3.11+
- **NotebookLM CLI**: `notebooklm_cdp_cli`（已安装在独立虚拟环境）
- **Python 库**: `python-pptx>=1.0.0`, `Pillow>=10.0.0`

## 工具

### `nb2pptx`

主流水线脚本，完整参数化调用。

**用法**:
```bash
python scripts/nb2pptx.py <md_file> [选项]
```

**参数**:
| 参数 | 说明 | 默认值 |
|------|------|--------|
| `md_file` | Markdown 文件路径（必填） | - |
| `--title, -t` | PPT 标题 | 文件名 |
| `--pages, -p` | 目标页数 | 30 |
| `--output-dir, -o` | 输出目录 | `~/Documents/A股研报/<笔记本名称>/` |
| `--logo, -l` | Logo 底图路径 | `assets/logo.png` |
| `--keep-temp` | 保留临时文件 | false |
| `--initial-interval` | 初始等待秒数 | 540 |
| `--max-interval` | 轮询间隔秒数 | 60 |
| `--timeout` | 总超时秒数 | 900 |

**示例**:
```bash
# 基本用法
python scripts/nb2pptx.py report.md

# 自定义标题和页数
python scripts/nb2pptx.py report.md --title "AI算力液冷赛道报告" --pages 40

# 调试模式（保留临时文件）
python scripts/nb2pptx.py report.md --keep-temp
```

### `chatgpt_auto_research`

ChatGPT 网页版自动化 6 轮行业研究脚本。通过 `agent-browser` (Playwright) 控制持久化 Profile 浏览器，自动完成 6 轮递进对话，最终输出 `research_source.md` 作为 NotebookLM 来源。

**核心特点**:
- 持久化 Chromium Profile，保持登录态（方案 A）
- 多重回复完成检测（字数稳定 + "Stop generating" 消失）
- 断点恢复支持（`--resume-from N`）
- 6 轮结论自动继承注入后续轮次

**用法**:
```bash
# 基本用法
python scripts/chatgpt_auto_research.py --topic "固态电池产业链"

# 从第3轮恢复
python scripts/chatgpt_auto_research.py --topic "低空经济" --resume-from 3

# 指定外部背景资料
python scripts/chatgpt_auto_research.py --topic "人形机器人" --context-file background.md

# 流水线模式：自动生成 MD 后传入 nb2pptx
python scripts/chatgpt_auto_research.py --topic "固态电池" && \
python scripts/nb2pptx.py ~/Documents/A股研报/固态电池/research_source.md
```

**参数**:
| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--topic, -t` | 研究主题（必填） | - |
| `--output-dir, -o` | 输出目录 | `~/Documents/A股研报/` |
| `--resume-from` | 从第几轮恢复（1-6） | 1 |
| `--headless` | 无头模式 | false |
| `--chrome-path` | 指定 Chrome 路径 | - |
| `--context-file` | 外部背景资料文件 | - |

**输出结构**:
```
~/Documents/A股研报/<主题>/
├── round_01_output.md     # 第一轮回复
├── round_02_output.md     # 第二轮回复
├── round_03_output.md     # ...
├── round_04_output.md
├── round_05_output.md
├── round_06_output.md
└── research_source.md      # 最终汇总 MD（NotebookLM 来源）
```

**技术细节**:
- 回复完成检测：连续 5 次 snapshot 字数稳定 或 "Stop generating" 按钮消失 → 回复完成
- 文本提取：JavaScript `document.querySelectorAll('[data-message-author-role="assistant"]')` → 取最后一条 `innerText`
- 登录态：首次手动登录后持久化 Profile，后续自动复用；session 过期时脚本检测并引导重新登录
- 超时策略：单轮默认 5 分钟超时，超时后尝试提取已有内容继续

**已知限制**:
- Cloudflare 验证页面可能阻断首次访问，需手动处理一次
- ChatGPT DOM 更新后选择器可能失效，需定期检查兼容性
- 无头模式下无法处理验证码，建议使用 `--headless` 仅在确认无验证码环境时使用

## 文件结构

```
nb2pptx/
├── SKILL.md                         # 本文件
├── README.md                        # 完整使用文档
├── scripts/
│   ├── nb2pptx.py                  # 主流水线脚本（MD → PPTX）
│   └── chatgpt_auto_research.py     # ChatGPT 自动化脚本（研究 → MD 来源）
├── assets/
│   └── logo.png                     # 默认前瞻客 Logo 底图
└── .chatgpt-browser-profile/        # ChatGPT 持久化浏览器 Profile（自动创建）
```

## 输出结构

```
~/Documents/A股研报/<笔记本名称>/
├── <笔记本名称>.pptx              # 横版 16:9 PPTX
├── images/                         # 横版图片（P1.png ~ P30.png）
├── <笔记本名称>_竖版.pptx         # 竖版 9:16 PPTX
└── images_竖版/                    # 竖版图片（P1.png ~ P30.png）
```

## 注意事项

- **双版本输出**: 同时生成横版（16:9）和竖版（9:16）两套 PPT，分别输出到不同目录
- **来源命名固定化**: `a` = 原始 MD 研报，`b` = PPT 大纲笔记。提示词通用化，不依赖具体标题
- **强制中文输出**: 所有提示词包含 `[LANGUAGE: CHINESE ONLY]` 和多重中文约束，确保 PPT 全中文
- **手机视频适配**: 提示词中包含手机播放适配要求（大字结论、小字细节、3-5个要点、图表优先）
- **竖屏专属优化**: 竖版提示词要求 9:16 比例、F型竖向阅读动线、标题居顶结论居中细节居底
- **Logo 遮盖**: 采用右下角动态对齐策略，根据图片尺寸自适应放置
- **内容长度**: `add_source_text` 支持直接传参，超过 30000 字符自动回退到临时文件方式
- **并行生成**: 4 个任务同时提交（横版前半/后半 + 竖版前半/后半），最大化利用 NotebookLM 并行能力
- **合并策略**: 提取图片后重新嵌入，避免直接合并 PPTX 的 XML relationships 问题
- **虚拟环境**: NotebookLM CLI 安装在 `/Users/gray/.qclaw/workspace-agent-ef704e53/.venv/`，脚本会自动检测

## 踩坑经验

- `add_source_text` / 长内容传递：CLI 直接传参支持大部分场景，但超过 30000 字符或含特殊字符时可能触发 RPC 错误。策略：短内容直接传参，长内容自动回退到临时文件 + `add-file`
- `download_slides` / artifact_id 获取：`task_id` 不能直接用于下载，必须通过 `artifact list` 获取 `artifact_id`，然后用 `--artifact-id` 参数下载
- `artifact wait` / 超时问题：`artifact wait` 命令在长等待期间会触发 ConnectTimeout，已改为手动轮询（`artifact list` + `time.sleep`）
- 并行生成 / artifact 区分：多个 `generate slide-deck` 任务并行提交后，通过提交后立即查询 `artifact list`，对比提交前后的 artifact 差异来区分各 PPT 的 artifact ID
- PPTX 合并 / XML relationships：直接合并两个 PPTX 文件会导致 relationships 冲突，正确策略是提取图片后重新创建 PPTX
- Logo 遮盖 / 坐标策略：固定坐标 (1225,740) 在不同尺寸 PPT 中可能错位，右下角动态对齐更可靠
- 双版本生成 / 资源占用：同时生成 4 个 PPT 任务会占用更多 NotebookLM 资源，建议总页数不超过 40 页，超时时间适当延长
- 竖版比例 / python-pptx：9:16 比例通过 `prs.slide_width = Inches(5.625)` 和 `prs.slide_height = Inches(10.0)` 实现
- 方案C / artifact 混入：当某套PPT的 artifact ID 获取失败时，方案C必须排除**所有其他PPT的已知 artifact IDs**，否则 `new_completed` 会混入横版/竖版的 artifacts 导致内容错乱
- 字体统一 / 多任务渲染：4个并行PPT生成任务若无统一字体约束，NotebookLM 可能在不同任务中使用不同字体（宋体/黑体/楷书混排）和变形比例，必须在提示词中强制指定统一字体族和字号体系
- 大纲画面描述 / 排版质量：大纲提示词若只给总体风格而不指定每页的画面构图（布局、图表类型、配色区域），NotebookLM 生成的PPT会出现排版粗糙、风格不统一的问题，必须要求每页包含"画面构图描述"
- 风格词触发品牌声明 / 免责声明：风格提示词中的"权威/严谨与精密"等强力风格词会触发 NotebookLM 自动生成页脚品牌声明（如"高端商业咨询顾问系统研究|严谨•权威•精密"、"机构内部研究报告"等）。**解决方案是双重保障**：提示词中添加通用封杀令 + `draw_disclaimer()` 函数在代码层用 PIL 强制绘制标准免责声明覆盖
- 通用封杀 / 页脚多余文字：NotebookLM 可能自行编造多种页脚内容（品牌声明、权威背书、保密声明、来源标注等），必须在提示词中明确禁止所有非标准免责声明的页脚文字，并在代码层面用 `draw_disclaimer()` 硬保障
- 代码级免责声明 / PIL 绘制：`draw_disclaimer()` 在 Logo 遮盖后执行，用 Pillow 在图片固定位置直接绘制两行标准免责声明（横版右对齐 / 竖版居中），自动检测系统中文字体（PingFang/思源黑体等），带半透明深色背景增强可读性
