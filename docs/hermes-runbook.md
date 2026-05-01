# Notebooklm-pptx-cli 在这里执行的操作手册

> 面向当前这台 macOS 环境与本仓库的实际状态编写。
> 当前仓库路径：`/tmp/Notebooklm-pptx-cli`
> 当前远端：`https://github.com/TheOneGuo/Notebooklm-pptx-cli.git`

## 1. 目标

这份手册的目标是让我们之后可以在这里稳定执行如下链路：

1. `chatgpt_auto_research.py`
2. `nb2pptx.py`
3. `md2voiceover.py`

并且严格符合你刚确认的真实业务含义：

- **必须**提取图片
- **必须**对图片覆盖 logo / 绘制免责声明
- **但不使用处理后的图片重建 PPTX**
- 最终保留的是 **NotebookLM 原始导出的 4 份 PPTX**
- 配音音频经过 `ffmpeg` 后处理后为 **1.5x + 双声道**

---

## 2. 当前环境结论

### 已具备

- 仓库代码已同步最新修改
- Python venv 可用：`~/.qclaw/workspace-agent-ef704e53/.venv/bin/python`
- NotebookLM CLI 可用：`~/.qclaw/workspace-agent-ef704e53/.venv/bin/notebooklm`
- `ffmpeg` 已安装：`/opt/homebrew/bin/ffmpeg`
- `agent-browser` 已安装：`/opt/homebrew/bin/agent-browser`
- Chrome 存在：`/Applications/Google Chrome.app`
- 默认 logo 文件存在：`~/Documents/前瞻客/logo和表情/前瞻客logo底图.png`
- 默认输出目录存在：`~/Documents/A股研报`
- MiMo 语音样本路径存在：`/Users/gray/Documents/原音.wav`

### 当前阻塞点

**NotebookLM 认证 / Chrome 9222 调试连接当前不可用。**

现场检查结果：

- `notebooklm auth status` → `ok: False`
- `browser_connected: False`
- `cookie_count: 0`
- `has_sid_cookie: False`
- `doctor` 报错：`502 Bad Gateway` on `http://127.0.0.1:9222/json/version`
- 直接 `curl http://127.0.0.1:9222/json/version` 也连不上

**结论：**
现在这台机器上，`md2voiceover.py` 的本地依赖大体齐全，但 **`nb2pptx.py` 暂时不能真正跑通**，因为 NotebookLM 的登录态 / Chrome remote debugging 没接通。

也就是说：

- **操作手册可以先完成**
- **完整执行（步骤二）现在还不能开始实跑**
- 先修复 Chrome 9222 + NotebookLM 登录态，才能继续

---

## 3. 三段工作流的职责划分

### A. `chatgpt_auto_research.py`
用途：
- 自动做 6 轮研究
- 产出 `research_source.md`
- 这个 MD 可以直接喂给 `nb2pptx.py`

输入：
- 主题 `--topic`
- 可选背景资料 `--context-file`

输出：
- `~/Documents/A股研报/<主题>/research_source.md`
- 各轮 markdown 记录

依赖：
- `agent-browser`
- 可用 Chrome
- ChatGPT 登录态 / 页面可访问

### B. `nb2pptx.py`
用途：
- 把 MD 导入 NotebookLM
- 生成大纲、来源 B、四个 PPT 任务
- 下载四个 NotebookLM 原始 PPTX
- 提取横版/竖版图片
- 对图片做 logo 遮盖和免责声明绘制
- 输出 `run_result.json`

输入：
- 一个 Markdown 文件
- 可选标题 / 页数 / 输出目录 / logo 路径

输出：
- `<标题>_横版_前半.pptx`
- `<标题>_横版_后半.pptx`
- `<标题>_竖版_前半.pptx`
- `<标题>_竖版_后半.pptx`
- `images_landscape/`
- `images_portrait/`
- `run_result.json`

依赖：
- NotebookLM CLI 可用
- Chrome 远程调试端口 `9222` 可用
- 已登录 Google / NotebookLM
- Pillow 可用

### C. `md2voiceover.py`
用途：
- 读取 MD + PPT 图片
- 生成短视频口播稿
- 调用 MiMo VoiceClone TTS
- 用 ffmpeg 做 1.5x + 双声道后处理

输入：
- 原始 MD
- `images_landscape/` 或 `images_portrait/`
- MiMo 配置

输出：
- 分页口播稿 `.txt`
- 对应 `.wav`

依赖：
- `scripts/mimo_voice_config.json`
- 有效 API key
- `voice_sample_path` 指向有效音频
- `ffmpeg`

---

## 4. 标准执行顺序

以后在这里执行时，按这个顺序：

### 路线 1：已有 MD

1. 准备 MD 文件
2. 跑 `nb2pptx.py`
3. 确认输出目录里的四个原始 PPTX、两套图片、`run_result.json`
4. 跑 `md2voiceover.py`
5. 检查配音输出

### 路线 2：先自动研究

1. 跑 `chatgpt_auto_research.py`
2. 拿到 `research_source.md`
3. 跑 `nb2pptx.py`
4. 跑 `md2voiceover.py`

---

## 5. 每次执行前必须做的 preflight 检查

### 5.1 NotebookLM 检查

```bash
"$HOME/.qclaw/workspace-agent-ef704e53/.venv/bin/notebooklm" auth status
"$HOME/.qclaw/workspace-agent-ef704e53/.venv/bin/notebooklm" doctor
curl http://127.0.0.1:9222/json/version
```

通过标准：
- `browser_connected: True`
- `cookie_count > 0`
- `has_sid_cookie: True`
- `curl 127.0.0.1:9222/json/version` 返回 JSON，而不是连接失败/502

若不通过：
- **不要启动 `nb2pptx.py`**
- 先修 Chrome 调试连接和 Google 登录态

### 5.2 MiMo 配置检查

检查配置文件：
- `scripts/mimo_voice_config.json`

要确认：
- `api_key` 已配置
- `base_url` 正确
- `voice_sample_path` 文件存在

建议检查命令：

```bash
python3 - <<'PY'
import json, pathlib
p = pathlib.Path('scripts/mimo_voice_config.json')
cfg = json.loads(p.read_text())
print('has_api_key', bool(cfg.get('api_key')))
print('base_url', cfg.get('base_url'))
vp = cfg.get('voice_sample_path')
print('voice_sample_exists', pathlib.Path(vp).exists() if vp else False)
PY
```

### 5.3 系统依赖检查

```bash
command -v ffmpeg
command -v agent-browser
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --version
```

### 5.4 输入文件检查

执行前要确认：
- MD 文件存在
- 页数目标合理（建议 ≤ 40）
- 输出目录明确
- logo 文件存在

---

## 6. 推荐执行命令模板

### 6.1 直接从 MD 生成 PPT

```bash
cd /tmp/Notebooklm-pptx-cli
python3 scripts/nb2pptx.py /absolute/path/to/report.md \
  --title "报告标题" \
  --pages 30 \
  --output-dir "$HOME/Documents/A股研报/报告标题"
```

如需保留临时文件调试：

```bash
python3 scripts/nb2pptx.py /absolute/path/to/report.md \
  --title "报告标题" \
  --pages 30 \
  --output-dir "$HOME/Documents/A股研报/报告标题" \
  --keep-temp
```

### 6.2 从研究主题自动生成 MD

```bash
cd /tmp/Notebooklm-pptx-cli
python3 scripts/chatgpt_auto_research.py \
  --topic "固态电池产业链" \
  --output-dir "$HOME/Documents/A股研报"
```

然后：

```bash
python3 scripts/nb2pptx.py \
  "$HOME/Documents/A股研报/固态电池产业链/research_source.md" \
  --title "固态电池产业链" \
  --pages 30 \
  --output-dir "$HOME/Documents/A股研报/固态电池产业链"
```

### 6.3 生成口播稿和配音

```bash
cd /tmp/Notebooklm-pptx-cli
python3 scripts/md2voiceover.py \
  --md /absolute/path/to/report.md \
  --images "$HOME/Documents/A股研报/报告标题/images_landscape" \
  --output-dir "$HOME/Documents/A股研报/报告标题/配音"
```

如果要对竖版图片配音，也可以把 `--images` 切到 `images_portrait/`。

---

## 7. 结果验收标准

### `nb2pptx.py` 跑完后，必须看到

在输出目录里：

- 4 个原始 PPTX 文件
- `images_landscape/`
- `images_portrait/`
- `run_result.json`

并且：
- 图片数量与页数一致
- 图片右下角 logo 已处理
- 图片免责声明已绘制
- `run_result.json` 中记录了 `pptx_files`

### `md2voiceover.py` 跑完后，必须看到

- 分页 `.txt`
- 对应 `.wav`
- 音频可播放
- 音频为 **双声道**
- 音频时长比原始 TTS 略短（1.5x）

---

## 8. 常见失败点与处理方式

### 失败点 1：NotebookLM 连不上
现象：
- `browser_connected: False`
- `cookie_count: 0`
- `127.0.0.1:9222` 不通

处理：
1. 用带 remote debugging 的 Chrome 启动
2. 登录 Google / NotebookLM
3. 再跑 `auth status` / `doctor`

### 失败点 2：PPT 任务超时
现象：
- 生成太慢
- 超时退出

处理：
- 增大 `--timeout`
- 适当增大 `--initial-interval`
- 控制页数不超过 40

### 失败点 3：MiMo 合成失败
现象：
- API 报错
- 配音文件没生成

处理：
- 检查 `api_key`
- 检查 `voice_sample_path`
- 用更短文本做 smoke test

### 失败点 4：ffmpeg 后处理失败
现象：
- 输出 wav 不存在
- 终端报 ffmpeg 错误

处理：
- 检查 `ffmpeg` 是否在 PATH
- 手动验证输入 wav 能被 ffmpeg 读取

---

## 9. 当前这台机器的真实可执行结论

### 现在能做
- 维护代码
- 写运行手册
- 做 preflight
- 跑 `md2voiceover.py` 的局部测试
- 准备输入材料

### 现在不能做
- **不能直接开始完整 `nb2pptx.py` 真跑**

原因只有一个核心阻塞：
- **NotebookLM / Chrome 9222 未连通**

### 达到可跑状态前还差什么
只差把以下状态恢复：

- Chrome 以 remote debugging 模式运行
- `127.0.0.1:9222/json/version` 能返回 JSON
- `notebooklm auth status` 显示登录态有效

---

## 10. 下一步建议

按照最稳的顺序：

1. 先修复 Chrome 9222 + NotebookLM 登录态
2. 做一个最小 MD smoke test
3. 再跑一次 `nb2pptx.py`
4. 成功后继续跑 `md2voiceover.py`
5. 最后再把 `chatgpt_auto_research.py` 接入整链路

---

## 11. 供我们之后复用的最短口令

如果你下次只想一句话让我开工，可以直接说：

- **“按 runbook 先做 preflight，再跑完整链路。”**
- **“拿这个 md 按标准工作流跑。”**
- **“先 research，再 nb2pptx，再 md2voiceover。”**

我会按这份手册直接执行。