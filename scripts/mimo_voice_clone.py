#!/usr/bin/env python3
"""
MiMo-V2.5-TTS-VoiceClone 语音克隆工具

功能：
1. 上传语音样本（一次输入，多次使用）
2. 使用克隆的语音合成文本
3. 支持命令行和API调用

用法：
    # 设置语音样本
    python mimo_voice_clone.py --setup --voice-file /path/to/voice.mp3
    
    # 合成语音
    python mimo_voice_clone.py --text "要合成的文本"
    
    # 指定输出文件
    python mimo_voice_clone.py --text "要合成的文本" --output output.wav
"""

import argparse
import base64
import json
import os
import sys
from pathlib import Path
from typing import Optional

try:
    import openai
except ImportError:
    openai = None  # 延迟报错：--help 可用，实际调用时检查


class MiMoVoiceClone:
    """MiMo语音克隆工具"""
    
    def __init__(self, config_path: str = "mimo_voice_config.json"):
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self.client = None
        
    def _load_config(self) -> dict:
        """加载配置文件"""
        if not self.config_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {self.config_path}")
        
        with open(self.config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # 验证必需字段
        if not config.get('api_key') or config['api_key'] == 'YOUR_MIMO_API_KEY':
            raise ValueError("请先在配置文件中设置有效的API Key")
        
        return config
    
    def _save_config(self):
        """保存配置文件"""
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)
    
    def _init_client(self):
        """初始化OpenAI客户端"""
        if openai is None:
            raise ImportError("需要安装 openai: pip install openai")
        if self.client is None:
            self.client = openai.OpenAI(
                api_key=self.config['api_key'],
                base_url=self.config['base_url']
            )
    
    def _encode_audio(self, audio_path: str) -> str:
        """将音频文件编码为Base64"""
        audio_path = Path(audio_path)
        
        if not audio_path.exists():
            raise FileNotFoundError(f"音频文件不存在: {audio_path}")
        
        # 检查文件大小
        file_size_mb = audio_path.stat().st_size / (1024 * 1024)
        if file_size_mb > self.config.get('max_file_size_mb', 7.5):
            raise ValueError(f"音频文件过大: {file_size_mb:.1f}MB，最大允许{self.config['max_file_size_mb']}MB")
        
        # 读取并编码
        with open(audio_path, 'rb') as f:
            audio_data = f.read()
        
        base64_data = base64.b64encode(audio_data).decode('utf-8')
        
        # 确定MIME类型
        suffix = audio_path.suffix.lower()
        mime_map = {
            '.mp3': 'audio/mpeg',
            '.wav': 'audio/wav',
            '.m4a': 'audio/m4a',
            '.mp4': 'audio/mp4',
            '.ogg': 'audio/ogg',
            '.flac': 'audio/flac'
        }
        mime_type = mime_map.get(suffix, 'audio/mpeg')
        
        return f"data:{mime_type};base64,{base64_data}"
    
    def setup_voice(self, voice_file: str, instruction: Optional[str] = None):
        """设置语音样本"""
        print(f"正在设置语音样本: {voice_file}")
        
        # 编码音频
        voice_data_url = self._encode_audio(voice_file)
        
        # 更新配置
        self.config['voice_sample_path'] = str(Path(voice_file).absolute())
        self.config['voice_sample_base64'] = voice_data_url
        
        if instruction:
            self.config['default_instruction'] = instruction
        
        # 保存配置
        self._save_config()
        
        print("语音样本设置成功！")
        print(f"样本路径: {self.config['voice_sample_path']}")
        print(f"默认指令: {self.config['default_instruction']}")
    
    def synthesize(self, text: str, instruction: Optional[str] = None, output_path: Optional[str] = None) -> str:
        """使用克隆的语音合成文本"""
        # 检查语音样本
        if not self.config.get('voice_sample_base64'):
            raise ValueError("请先设置语音样本: python mimo_voice_clone.py --setup --voice-file /path/to/voice.mp3")
        
        # 初始化客户端
        self._init_client()
        
        # 使用默认指令或指定指令
        inst = instruction or self.config.get('default_instruction', '用自然流畅的语气朗读')
        
        print(f"正在合成语音...")
        print(f"文本: {text[:50]}{'...' if len(text) > 50 else ''}")
        print(f"指令: {inst}")
        
        # 调用API
        response = self.client.chat.completions.create(
            model="mimo-v2.5-tts-voiceclone",
            messages=[
                {"role": "user", "content": inst},
                {"role": "assistant", "content": text}
            ],
            extra_body={
                "audio": {
                    "format": self.config.get('output_format', 'wav'),
                    "voice": self.config['voice_sample_base64']
                }
            }
        )
        
        # 获取音频数据
        audio_data = response.choices[0].message.audio.data
        
        # 解码Base64音频数据
        audio_bytes = base64.b64decode(audio_data)
        
        # 确定输出路径
        if output_path is None:
            output_path = f"output_{hash(text) % 10000}.wav"
        
        # 保存音频文件
        output_path = Path(output_path)
        with open(output_path, 'wb') as f:
            f.write(audio_bytes)
        
        print(f"语音合成完成！")
        print(f"输出文件: {output_path.absolute()}")
        
        return str(output_path.absolute())
    
    def get_status(self) -> dict:
        """获取当前状态"""
        return {
            "api_key_set": self.config.get('api_key') != 'YOUR_MIMO_API_KEY',
            "voice_sample_set": bool(self.config.get('voice_sample_base64')),
            "voice_sample_path": self.config.get('voice_sample_path', ''),
            "default_instruction": self.config.get('default_instruction', ''),
            "output_format": self.config.get('output_format', 'wav')
        }


def main():
    parser = argparse.ArgumentParser(description='MiMo-V2.5-TTS-VoiceClone 语音克隆工具')
    
    # 主要参数
    parser.add_argument('--setup', action='store_true', help='设置语音样本')
    parser.add_argument('--voice-file', type=str, help='语音样本文件路径')
    parser.add_argument('--text', type=str, help='要合成的文本')
    parser.add_argument('--instruction', type=str, help='语音风格指令')
    parser.add_argument('--output', '-o', type=str, help='输出文件路径')
    parser.add_argument('--config', type=str, default='mimo_voice_config.json', help='配置文件路径')
    parser.add_argument('--status', action='store_true', help='显示当前状态')
    
    args = parser.parse_args()
    
    try:
        # 创建工具实例
        tool = MiMoVoiceClone(args.config)
        
        if args.status:
            # 显示状态
            status = tool.get_status()
            print("当前状态:")
            for key, value in status.items():
                print(f"  {key}: {value}")
            return
        
        if args.setup:
            # 设置语音样本
            if not args.voice_file:
                print("错误: 设置语音样本时需要指定 --voice-file 参数")
                sys.exit(1)
            tool.setup_voice(args.voice_file, args.instruction)
            return
        
        if args.text:
            # 合成语音
            output_path = tool.synthesize(args.text, args.instruction, args.output)
            return
        
        # 如果没有指定操作，显示帮助
        parser.print_help()
        
    except Exception as e:
        print(f"错误: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()