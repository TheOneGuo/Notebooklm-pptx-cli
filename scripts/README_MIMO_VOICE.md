# MiMo-V2.5-TTS-VoiceClone 语音克隆工具

这是一个基于小米MiMo-V2.5-TTS-VoiceClone API的语音克隆工具，可以实现一次输入语音样本，之后多次使用克隆语音合成文本的功能。

## 功能特性

- **一次输入，多次使用**：只需上传一次语音样本，之后可以无限次使用
- **高质量语音克隆**：基于小米MiMo-V2.5-TTS-VoiceClone模型，克隆效果逼真
- **简单易用**：提供命令行接口，操作简单
- **灵活配置**：支持自定义语音风格指令
- **批量合成**：支持批量文本合成

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置API密钥

编辑 `mimo_voice_config.json` 文件，设置你的API密钥：

```json
{
  "api_key": "你的MiMo API密钥",
  "base_url": "https://api.xiaomimimo.com/v1",
  "voice_sample_path": "",
  "voice_sample_base64": "",
  "default_instruction": "用自然流畅的语气朗读",
  "output_format": "wav",
  "max_file_size_mb": 7.5
}
```

### 3. 设置语音样本

```bash
python mimo_voice_clone.py --setup --voice-file /path/to/your/voice.mp3
```

**语音样本要求：**
- 格式：MP3、WAV、M4A、MP4等常见音频格式
- 大小：最大7.5MB
- 时长：建议30秒左右，清晰无噪音

### 4. 合成语音

```bash
# 基本用法
python mimo_voice_clone.py --text "要合成的文本"

# 指定输出文件
python mimo_voice_clone.py --text "要合成的文本" --output output.wav

# 指定语音风格
python mimo_voice_clone.py --text "要合成的文本" --instruction "用开心的语气朗读"
```

## 使用示例

### 示例1：设置语音样本

```bash
python example_usage.py setup
```

### 示例2：合成语音

```bash
python example_usage.py synthesize
```

### 示例3：批量合成

```bash
python example_usage.py batch
```

## 命令行参数

```
python mimo_voice_clone.py [选项]

选项：
  --setup              设置语音样本
  --voice-file FILE    语音样本文件路径
  --text TEXT          要合成的文本
  --instruction TEXT   语音风格指令
  --output FILE        输出文件路径
  --config FILE        配置文件路径（默认：mimo_voice_config.json）
  --status             显示当前状态
```

## 集成到现有工作流

### 在Python代码中使用

```python
from mimo_voice_clone import MiMoVoiceClone

# 初始化工具
tool = MiMoVoiceClone()

# 设置语音样本（只需一次）
tool.setup_voice("my_voice.mp3", instruction="用自然亲切的语气朗读")

# 合成语音
output_file = tool.synthesize("要合成的文本", output_path="output.wav")
```

### 集成到PPT流水线

可以在现有的PPT自动化流水线中添加语音合成功能：

```python
from mimo_voice_clone import MiMoVoiceClone

# 在PPT生成后添加语音合成
def add_voice_to_ppt(ppt_text, voice_tool):
    """为PPT添加语音讲解"""
    voice_file = voice_tool.synthesize(ppt_text, output_path="voice.wav")
    return voice_file

# 使用示例
voice_tool = MiMoVoiceClone()
voice_file = add_voice_to_ppt("PPT内容文本", voice_tool)
```

## 测试

运行测试脚本：

```bash
python test_mimo_voice.py
```

## 配置说明

配置文件 `mimo_voice_config.json` 包含以下字段：

- `api_key`: MiMo API密钥（必需）
- `base_url`: API端点（默认：https://api.xiaomimimo.com/v1）
- `voice_sample_path`: 语音样本文件路径（自动设置）
- `voice_sample_base64`: 语音样本的Base64编码（自动设置）
- `default_instruction`: 默认语音风格指令
- `output_format`: 输出音频格式（目前仅支持wav）
- `max_file_size_mb`: 最大文件大小限制（默认7.5MB）

## 注意事项

1. **API密钥安全**：请妥善保管你的API密钥，不要泄露给他人
2. **语音样本质量**：语音样本质量直接影响克隆效果，建议使用清晰、无噪音的录音
3. **文本长度**：虽然官方没有明确限制，但建议单次合成文本控制在几百字以内
4. **网络环境**：需要稳定的网络环境访问小米API服务
5. **费用说明**：目前小米MiMo TTS服务限时免费，具体收费政策请关注官方公告

## 故障排除

### 问题1：配置文件不存在

```
错误: 配置文件不存在: mimo_voice_config.json
```

**解决方案**：确保配置文件存在于当前目录，或使用 `--config` 参数指定配置文件路径。

### 问题2：API密钥无效

```
错误: 请先在配置文件中设置有效的API Key
```

**解决方案**：在配置文件中设置有效的MiMo API密钥。

### 问题3：语音样本文件过大

```
错误: 音频文件过大: 8.2MB，最大允许7.5MB
```

**解决方案**：压缩音频文件或使用更短的语音样本。

### 问题4：网络连接问题

```
错误: 连接超时
```

**解决方案**：检查网络连接，确保可以访问 `api.xiaomimimo.com`。

## 更新日志

### v1.0.0 (2026-05-01)
- 初始版本
- 支持语音样本设置和语音合成
- 提供命令行接口
- 支持批量合成

## 许可证

MIT License

## 联系方式

如有问题或建议，请提交Issue或联系开发者。