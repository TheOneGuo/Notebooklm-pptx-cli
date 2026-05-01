#!/usr/bin/env python3
"""
ChatGPT 网页版自动化 — 行业研究 6 轮分析

原理: 通过 agent-browser (Playwright) 控制 Chromium 浏览器,
      持久化用户 Profile 保持登录态, 自动完成 6 轮递进对话,
      最终输出 research_source.md 作为 NotebookLM 来源。

使用方法:
  python chatgpt_auto_research.py --topic "固态电池产业链"
  python chatgpt_auto_research.py --topic "低空经济" --resume-from 4
"""

import os
import sys
import json
import time
import argparse
import subprocess
import re
import urllib.request
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple

# ─────────────────────────────────────────────────────────────────────────────
# 目录与路径配置
# ─────────────────────────────────────────────────────────────────────────────

SKILL_DIR = Path(__file__).parent
PROFILE_DIR = SKILL_DIR / ".chatgpt-browser-profile"
DEFAULT_OUTPUT_DIR = Path.home() / "Documents" / "A股研报"

BROWSER_EXECUTABLE = os.environ.get("CHROME_PATH", "")  # 可手动指定 Chrome 路径


# ─────────────────────────────────────────────────────────────────────────────
# 用户定义的 6 个问题块（必须原样逐轮发送）
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_QUESTION_BLOCKS = [
    """一、根据上述信息，先对行业发展现状与核心趋势深度分析：全球及国内市场规模、需求增速、核心驱动因素、技术迭代方向、供给侧格局变化、国产替代进度

行业竞争格局拆解：行业集中度（CR3/CR5/CR10）、整个行业核心参与标的名单、市场份额对比、行业进入壁垒

细分赛道市场空间全维度测算：完成 TAM/SAM/SOM 测算，明确行业天花板与公司成长边界""",
    """二、继续，同时对上述行业内标的财务数据进行分析，包括盈利能力：拆解近 3-5 年营收规模与增速、净利润 / 扣非净利润规模与增速、毛利率 / 净利率、ROE/ROIC 的趋势变化，与行业均值、核心竞争对手完成对标

估值指标分析：采集最新交易日收盘价对应的 PE（静态 / 动态 / 滚动）、PB、PS、PCF 等指标，匹配申万三级行业分类，完成行业分位数、历史分位数计算

偿债能力分析：长期偿债能力（资产负债率、有息负债规模、利息保障倍数等）、短期偿债能力（流动比率、速动比率、现金比率等）

营运能力分析：应收账款周转率、存货周转率、总资产周转率，应收 / 应付账款周转天数分析

费用管控效率分析：拆解销售费用、管理费用、研发费用的规模、占营收比例、结构构成，分析费用使用效率，与行业平均水平、核心竞争对手完成对标

现金流质量分析：经营活动现金流、投资活动与筹资活动现金流分析，对比经营性现金流与净利润的匹配度，评估盈利质量""",
    """三、继续，同时对上述标的近 3 年分业务设计产能、实际产能、产能利用率数据，分析利用率异常波动的核心原因

梳理在建工程项目，明确新增产线投资额、建设进度、预期投产时间、设计产能规模与达产周期

测算新产能释放对营收、毛利率、归母净利润的贡献

分析历年资本开支规模、结构投向与未来计划，评估资金来源与投入产出效率""",
    """四、继续，同时对技术壁垒分析：底层核心技术体系、专利布局（国内发明专利、海外专利布局）、专利质量与转化能力、技术迭代速度与研发投入产出效率、核心技术团队与人才储备

客户与品牌壁垒分析：头部客户绑定情况、客户粘性、品牌行业地位、标杆项目案例、行业口碑

交付与产能壁垒分析：规模化交付能力、全流程项目管理能力、产能布局与柔性化程度、快速响应客户需求的能力

成本与供应链壁垒分析：核心零部件自主化率、全链条成本控制能力、供应链深度绑定能力、集采规模优势，结合模块一的商业模式定位，验证成本领先优势的可持续性""",
    """五、继续，同时对上述标的进入新的高景气高 PE 赛道筛选与市场空间分析：明确筛选标准，分析目标赛道的行业发展现状、核心增长驱动因素、未来 3-5 年市场规模、竞争格局与进入壁垒

新赛道进入可行性综合评分与优先级排序：从技术、供应链、产线、客户、成本 5 个核心维度，对目标赛道进行量化评分，给出优先进入赛道排序与切入路径

新赛道业务对公司业绩与估值的影响测算：分阶段预测新赛道业务的营收、利润贡献，评估对公司整体毛利率、ROE 的提升作用，以及估值溢价空间

包括平台化技术能力分析：核心技术可迁移性、技术平台化能力、产线复用潜力，为后续新赛道拓展分析提供前置依据

现有技术储备匹配度：核心底层技术的可迁移性、技术平台化能力，与目标新赛道的技术需求匹配度评分

供应链复用能力：现有核心原材料、中间品的品类重合度，现有供应商体系在新赛道的复用可能性

产线与产能复用率：现有产线 / 即将投产产线的可复用领域、产线改造难度与改造成本、产能柔性化程度，新赛道产能复用率测算

客户渠道复用能力：现有客户与目标新赛道客户的重叠度、渠道复用可能性、客户资源协同效应

成本与全生命周期成本优势：依托现有规模效应带来的成本优势，新赛道产品的全生命周期成本与行业竞品的对标分析""",
    """六、继续，同时对上述标的技术面深度分析：近 3 个月股价走势、均线系统（MA5/MA10/MA20/MA60）、成交量变化、MACD/KDJ/RSI 等核心技术指标分析

资金面全景分析：近 10 个交易日主力资金流向、北向资金持仓、机构持仓、龙虎榜资金分析

筹码结构分析：筹码集中度变化、成本均线分布、获利盘 / 套牢盘比例，评估筹码结构稳定性

舆情与短期机会评估：近 1 个月标的相关舆情情绪评估，结合多维度指标完成综合评级，同时评级用不会触犯抖音规则的方式说出。""",
]


def load_question_blocks(path: Optional[str] = None) -> List[str]:
    """加载六个问题块；默认使用用户已确认的原文。"""
    if not path:
        return list(DEFAULT_QUESTION_BLOCKS)

    question_path = Path(path)
    if not question_path.exists():
        raise FileNotFoundError(f"问题文件不存在: {question_path}")

    raw_text = question_path.read_text(encoding="utf-8").strip()
    if question_path.suffix.lower() == ".json":
        payload = json.loads(raw_text)
        if not isinstance(payload, list) or not all(isinstance(item, str) for item in payload):
            raise ValueError("questions JSON 必须是字符串数组")
        blocks = [item.strip() for item in payload if item.strip()]
    else:
        blocks = [block.strip() for block in re.split(r"\n\s*\n(?=[一二三四五六]、)", raw_text) if block.strip()]

    if len(blocks) != 6:
        raise ValueError(f"问题块数量必须等于 6，当前为 {len(blocks)}")
    return blocks


def build_research_markdown(topic: str, round_outputs: List[str]) -> str:
    """按顺序拼接六轮原始回答，不再额外请求 ChatGPT 二次汇总。"""
    chinese_rounds = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
    lines = [f"# {topic}", ""]
    for idx, output in enumerate(round_outputs, start=1):
        round_label = chinese_rounds[idx] if idx < len(chinese_rounds) else str(idx)
        lines.extend([f"## 第{round_label}轮", "", output.strip(), ""])
    return "\n".join(lines).rstrip() + "\n"


# ─────────────────────────────────────────────────────────────────────────────
# 核心工具函数：subprocess 包装 agent-browser
# ─────────────────────────────────────────────────────────────────────────────

def _run(cmd: List[str], timeout: int = 30) -> subprocess.CompletedProcess:
    """运行 agent-browser 命令，返回 CompletedProcess"""
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
        cwd=SKILL_DIR
    )
    return result


def _run_browser(cmd: List[str], timeout: int = 30) -> subprocess.CompletedProcess:
    """运行 agent-browser 命令（自动添加 launch 前缀如需）"""
    return _run(cmd, timeout)


# 全局 profile 命令前缀（由 SessionManager 初始化后注入）
_profile_dir: Optional[Path] = None
_cdp_port: Optional[int] = None


def _detect_cdp_port(candidate_ports: Optional[List[int]] = None) -> Optional[int]:
    """检测本机可复用的 Chrome CDP 端口。"""
    for port in candidate_ports or [9222]:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            if payload.get("Browser") and payload.get("webSocketDebuggerUrl"):
                return port
        except Exception:
            continue
    return None


def _ab(subcmd: List[str], timeout: int = 30) -> subprocess.CompletedProcess:
    """生成带 --profile 前缀的 agent-browser 命令"""
    cmd = ["agent-browser"]
    if _cdp_port:
        cmd.extend(["--cdp", str(_cdp_port)])
    elif _profile_dir:
        cmd.extend(["--profile", str(_profile_dir)])
    cmd.extend(subcmd)
    return _run(cmd, timeout)


# ─────────────────────────────────────────────────────────────────────────────
# 会话管理器
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SessionManager:
    profile_dir: Path
    headless: bool = False
    browser_executable: str = ""

    def __post_init__(self):
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._browser_pid: Optional[int] = None
        # 注入全局 profile dir / cdp port
        global _profile_dir, _cdp_port
        _profile_dir = self.profile_dir
        _cdp_port = _detect_cdp_port()

    def _profile_cmd(self, subcmd: List[str]) -> List[str]:
        """生成带 --profile 前缀的命令"""
        cmd = ["agent-browser", "--profile", str(self.profile_dir)]
        cmd.extend(subcmd)
        return cmd

    def ensure_browser_launched(self) -> bool:
        """启动浏览器，确保 profile 可用"""
        # 使用 --profile 参数，所有命令自动复用该 profile
        try:
            result = _ab(["get", "title"], timeout=10)
            if result.returncode == 0:
                print("  [Browser] 已检测到运行中的浏览器会话")
                return True
        except Exception:
            pass

        # 无运行中会话，通过 open 命令启动
        print(f"  [Browser] 启动 Chromium (profile: {self.profile_dir.name})...")
        result = _ab(["open", "https://www.google.com/"], timeout=15)
        if result.returncode != 0:
            print(f"  [!] 启动失败: {result.stderr}")
            return False

        time.sleep(3)
        return True

    def check_login_status(self) -> bool:
        """检测 ChatGPT 登录状态"""
        print("  [Session] 检测登录状态...")
        try:
            _ab(["open", "https://chatgpt.com/"], timeout=20)
            time.sleep(5)  # 等待 Cloudflare 验证完成
            result = _ab(["snapshot"], timeout=15)
            snapshot = result.stdout

            logged_out_markers = [
                "Sign up", "Log in", "Continue with Google",
                "Continue with Microsoft", "Sign in with Apple",
                "登录", "免费注册", "注册", "继续使用 Google",
                "Continue with phone", "Log in or sign up",
            ]

            logged_in_markers = [
                "New chat", "Send message", 'textbox "与 ChatGPT 聊天"',
                'textbox "Message ChatGPT"', "新聊天", "与 ChatGPT 聊天",
                "打开“个人资料”菜单", "打开\"个人资料\"菜单",
            ]

            # 检测未登录特征
            if any(marker in snapshot for marker in logged_out_markers):
                print("  [!] 未检测到登录状态，需要手动登录")
                return False

            # 检测登录后的特征
            if any(marker in snapshot for marker in logged_in_markers):
                print("  [OK] 已登录 ChatGPT")
                return True

            return False

        except Exception as e:
            print(f"  [!] 登录检测异常: {e}")
            return False

    def wait_for_manual_login(self, timeout: int = 300):
        """等待用户手动完成登录（轮询检测）"""
        print("  [Session] 等待手动登录中...（每10秒检测一次）")
        start = time.time()
        while time.time() - start < timeout:
            if self.check_login_status():
                return True
            time.sleep(10)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 对话自动化器
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ConversationAutomator:
    session: SessionManager
    output_dir: Path
    topic: str
    timeout_per_round: int = 300  # 5分钟
    max_round_attempts: int = 3
    context_text: str = ""
    question_blocks: Optional[List[str]] = None

    def __post_init__(self):
        self.round_outputs: List[str] = []
        self.output_dir = Path(self.output_dir) / self._sanitize_topic(self.topic)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if self.question_blocks is None:
            self.question_blocks = load_question_blocks()
        else:
            self.question_blocks = [block.strip() for block in self.question_blocks if block and block.strip()]
            if not self.question_blocks:
                raise ValueError("question_blocks 不能为空")
        self.context_text = (self.context_text or "").strip()
        self.max_round_attempts = max(1, int(self.max_round_attempts or 1))

    @staticmethod
    def _sanitize_topic(t: str) -> str:
        """清理文件名中的非法字符"""
        return re.sub(r'[\\/:*?"<>|]', '_', t)

    @staticmethod
    def _pick_type_target(snapshot: str) -> str:
        """基于 snapshot 选择更可靠的 composer 目标，优先可见 contenteditable。"""
        textbox_markers = ['textbox "与 ChatGPT 聊天"', 'textbox "Message ChatGPT"']
        if any(marker in snapshot for marker in textbox_markers):
            return 'div[contenteditable="true"][role="textbox"]'

        selector_candidates = [
            'div[contenteditable="true"][role="textbox"]',
            'div[contenteditable="true"]',
            '[data-testid="prompt-textarea"]',
            'textarea[aria-label="与 ChatGPT 聊天"]',
            'textarea[aria-label="Message ChatGPT"]',
            'textarea',
        ]
        for selector in selector_candidates:
            if selector.replace('"', '') in snapshot or selector in snapshot:
                return selector
        return 'div[contenteditable="true"][role="textbox"]'

    @staticmethod
    def _normalize_eval_text(raw_text: str) -> str:
        """agent-browser eval 对字符串通常返回 JSON 编码值，这里解码成纯文本。"""
        text = (raw_text or "").strip()
        if not text:
            return ""
        try:
            parsed = json.loads(text)
            if isinstance(parsed, str):
                return parsed.strip()
        except Exception:
            pass
        return text

    @staticmethod
    def _looks_like_error_response(text: str, snapshot: str = "") -> bool:
        combined = "\n".join(part for part in [(text or "").strip(), (snapshot or "").strip()] if part).strip()
        if not combined:
            return False
        primary_markers = [
            "Something went wrong while generating the response",
            "Something went wrong",
            "If this issue persists please contact us through our help center",
            "help.openai.com",
            "出了点问题",
            "发生错误",
            "An error occurred",
        ]
        retry_markers = ["重试", "Try again", "Retry", "Regenerate", "重新生成", "再试一次"]
        return any(marker in combined for marker in primary_markers) and any(marker in combined for marker in retry_markers)

    def _send_message(self, text: str) -> bool:
        """优先 DOM 提交，失败时回退到经过实测可用的 type + Shift+Enter + Enter。"""
        try:
            result = _ab(["snapshot", "-i"], timeout=15)
            snapshot = result.stdout
            type_target = self._pick_type_target(snapshot)
            escaped_text = json.dumps(text, ensure_ascii=False)

            def verify_submit() -> Dict[str, Any]:
                verify_js = """
                (() => {
                    const composer = document.querySelector('div[contenteditable="true"][role="textbox"], div[contenteditable="true"], [data-testid="prompt-textarea"], textarea[aria-label="与 ChatGPT 聊天"], textarea[aria-label="Message ChatGPT"], textarea');
                    const userNodes = Array.from(document.querySelectorAll('[data-message-author-role="user"]'))
                        .filter(el => !el.parentElement?.closest('[data-message-author-role="user"]'));
                    const assistantNodes = Array.from(document.querySelectorAll('[data-message-author-role="assistant"]'))
                        .filter(el => !el.parentElement?.closest('[data-message-author-role="assistant"]'));
                    const buttonTexts = Array.from(document.querySelectorAll('button'))
                        .map(btn => (btn.innerText || btn.getAttribute('aria-label') || '').trim())
                        .filter(Boolean);
                    return {
                        user_count: userNodes.length,
                        assistant_count: assistantNodes.length,
                        composer_text: composer
                            ? ('value' in composer ? (composer.value || '') : (composer.textContent || ''))
                            : '',
                        is_generating: buttonTexts.some(text => ['Stop generating', '停止流式传输', '停止生成', '正在思考', '已停止思考', 'Thinking', '取消加载', '取消'].some(marker => text.includes(marker))),
                    };
                })()
                """
                verify_result = _ab(["eval", verify_js], timeout=10)
                verify_payload = (verify_result.stdout or "").strip()
                return json.loads(verify_payload) if verify_payload else {}

            baseline_state = verify_submit()

            def submission_succeeded(state: Dict[str, Any]) -> bool:
                user_count = int(state.get("user_count") or 0)
                assistant_count = int(state.get("assistant_count") or 0)
                baseline_user_count = int(baseline_state.get("user_count") or 0)
                baseline_assistant_count = int(baseline_state.get("assistant_count") or 0)
                is_generating = bool(state.get("is_generating"))
                baseline_generating = bool(baseline_state.get("is_generating"))
                return (
                    user_count > baseline_user_count
                    or assistant_count > baseline_assistant_count
                    or (is_generating and not baseline_generating)
                )

            js_set_and_submit = f"""
            (() => {{
                const selectors = [
                    {json.dumps(type_target, ensure_ascii=False)},
                    'div[contenteditable="true"][role="textbox"]',
                    'div[contenteditable="true"]',
                    '[data-testid="prompt-textarea"]',
                    'textarea[aria-label="与 ChatGPT 聊天"]',
                    'textarea[aria-label="Message ChatGPT"]',
                    'textarea',
                ];
                const target = selectors
                    .map(sel => document.querySelector(sel))
                    .find(Boolean);
                if (!target) return {{ ok: false, reason: 'input-not-found' }};

                const text = {escaped_text};
                target.focus();
                if ('value' in target) {{
                    const proto = Object.getPrototypeOf(target);
                    const descriptor = Object.getOwnPropertyDescriptor(proto, 'value')
                        || Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value');
                    if (descriptor?.set) descriptor.set.call(target, text);
                    else target.value = text;
                    target.dispatchEvent(new InputEvent('input', {{ bubbles: true, data: text, inputType: 'insertText' }}));
                    target.dispatchEvent(new Event('change', {{ bubbles: true }}));
                }} else {{
                    target.textContent = text;
                    target.dispatchEvent(new InputEvent('input', {{ bubbles: true, data: text, inputType: 'insertText' }}));
                    target.dispatchEvent(new Event('change', {{ bubbles: true }}));
                }}

                const form = target.closest('form');
                let submitted = false;
                let method = '';
                if (form) {{
                    const submitButton = form.querySelector('button[type="submit"]');
                    if (submitButton && !submitButton.disabled) {{
                        submitButton.click();
                        submitted = true;
                        method = 'submit-button';
                    }} else if (typeof form.requestSubmit === 'function') {{
                        form.requestSubmit();
                        submitted = true;
                        method = 'requestSubmit';
                    }} else {{
                        form.dispatchEvent(new Event('submit', {{ bubbles: true, cancelable: true }}));
                        submitted = true;
                        method = 'dispatch-submit';
                    }}
                }}

                return {{
                    ok: true,
                    submitted,
                    method,
                    value: 'value' in target ? target.value : (target.textContent || ''),
                }};
            }})()
            """
            submit_result = _ab(["eval", js_set_and_submit], timeout=10)
            payload = (submit_result.stdout or "").strip()
            submit_data = json.loads(payload) if payload else {}
            if submit_result.returncode != 0 or not submit_data.get("ok"):
                raise RuntimeError(f"输入框注入失败: {submit_result.stderr or submit_result.stdout}")
            if not submit_data.get("submitted"):
                raise RuntimeError(f"消息未提交: {submit_data}")

            verify_data: Dict[str, Any] = {}
            for _ in range(2):
                time.sleep(1)
                verify_data = verify_submit()
                if submission_succeeded(verify_data):
                    return True

            print("  [...] DOM 提交未生效，回退到 type + Shift+Enter + Enter")
            lines = text.splitlines() or [text]
            _ab(["focus", type_target], timeout=5)
            _ab(["press", "Control+a"], timeout=5)
            _ab(["press", "Backspace"], timeout=5)
            for idx, line in enumerate(lines):
                if line:
                    _ab(["type", type_target, line], timeout=max(30, min(180, len(line) // 8 + 30)))
                if idx < len(lines) - 1:
                    _ab(["press", "Shift+Enter"], timeout=5)
            _ab(["press", "Enter"], timeout=5)

            verify_data: Dict[str, Any] = {}
            for _ in range(2):
                time.sleep(1)
                verify_data = verify_submit()
                if submission_succeeded(verify_data):
                    return True
            raise RuntimeError(f"消息似乎仍停留在输入框中，未真正发送: {verify_data}")

        except Exception as e:
            print(f"  [!] 发送消息失败: {e}")
            return False

    def _read_chat_state(self) -> Dict[str, Any]:
        """读取当前会话/输入框状态，用于验证是否已真正进入 fresh chat。"""
        js_code = """
        (() => {
            const userNodes = Array.from(document.querySelectorAll('[data-message-author-role="user"]'))
                .filter(el => !el.parentElement?.closest('[data-message-author-role="user"]'));
            const assistantNodes = Array.from(document.querySelectorAll('[data-message-author-role="assistant"]'))
                .filter(el => !el.parentElement?.closest('[data-message-author-role="assistant"]'));
            const composer = document.querySelector('textarea[aria-label="与 ChatGPT 聊天"], textarea[aria-label="Message ChatGPT"], [data-testid="prompt-textarea"], textarea, div[contenteditable="true"]');
            return {
                url: location.href,
                title: document.title,
                user_count: userNodes.length,
                assistant_count: assistantNodes.length,
                composer_text: composer
                    ? ('value' in composer ? (composer.value || '') : (composer.textContent || ''))
                    : '',
                has_composer: Boolean(composer),
            };
        })()
        """
        try:
            result = _ab(["eval", js_code], timeout=10)
            payload = (result.stdout or "").strip()
            data = json.loads(payload) if payload else {}
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {
            "url": "",
            "title": "",
            "user_count": 0,
            "assistant_count": 0,
            "composer_text": "",
            "has_composer": False,
        }

    def _is_fresh_chat_state(self, state: Dict[str, Any]) -> bool:
        """判断是否已经真正回到空白新对话。"""
        return bool(state.get("has_composer")) and int(state.get("user_count") or 0) == 0 and int(state.get("assistant_count") or 0) == 0

    def _new_chat(self) -> bool:
        """新建对话，且必须验证已真正回到空白对话。"""
        print("  [Chat] 新建对话...")
        try:
            result = _ab(["snapshot", "-i"], timeout=10)
            snapshot = result.stdout

            js_click_new_chat = """
            (() => {
                const selectors = [
                    'a[data-testid="create-new-chat-button"][data-active][href="/"]',
                    'a[data-testid="create-new-chat-button"][data-revealed][href="/"]',
                    'a[data-testid="create-new-chat-button"][href="/"]',
                    'a[href="/"][data-sidebar-item="true"]',
                ];
                const textPattern = /新聊天|New chat/;
                for (const selector of selectors) {
                    const matches = Array.from(document.querySelectorAll(selector)).filter(el => {
                        const label = (el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || '').trim();
                        const href = el.getAttribute('href') || '';
                        return href === '/' && (!label || textPattern.test(label));
                    });
                    if (!matches.length) continue;
                    const target = matches.find(el => {
                        const label = (el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || '').trim();
                        return textPattern.test(label);
                    }) || matches[0];
                    target.click();
                    return {
                        clicked: true,
                        selector,
                        text: (target.innerText || '').trim(),
                        aria: target.getAttribute('aria-label'),
                        href: target.getAttribute('href'),
                    };
                }
                return { clicked: false };
            })()
            """

            def wait_for_fresh_chat(max_attempts: int = 4) -> bool:
                last_state: Dict[str, Any] = {}
                for _ in range(max_attempts):
                    time.sleep(1)
                    last_state = self._read_chat_state()
                    if self._is_fresh_chat_state(last_state):
                        return True
                print(f"  [...] 新对话状态未确认: {last_state}")
                return False

            should_try_dom_click = any(marker in snapshot for marker in ["新聊天", "New chat", "与 ChatGPT 聊天", "Message ChatGPT"])
            if should_try_dom_click:
                click_result = _ab(["eval", js_click_new_chat], timeout=10)
                payload = (click_result.stdout or "").strip()
                try:
                    click_data = json.loads(payload) if payload else {}
                except json.JSONDecodeError:
                    click_data = {}
                if click_result.returncode == 0 and click_data.get("clicked") and wait_for_fresh_chat():
                    return True

            # fallback：直接打开主页，让 ChatGPT 自己路由到 fresh composer
            open_result = _ab(["open", "https://chatgpt.com/"], timeout=20)
            if open_result.returncode != 0:
                print(f"  [!] 新建对话 fallback 失败: {open_result.stderr or open_result.stdout}")
                return False
            if wait_for_fresh_chat():
                return True
            return False
        except Exception as e:
            print(f"  [!] 新建对话失败: {e}")
            return False

    def _read_response_state(self) -> Dict[str, Any]:
        """读取当前会话中 assistant 回复状态。"""
        js_code = """
        (() => {
            const assistantNodes = Array.from(document.querySelectorAll('[data-message-author-role="assistant"]'))
                .filter(el => !el.parentElement?.closest('[data-message-author-role="assistant"]'));
            const lastAssistant = assistantNodes.length
                ? (assistantNodes[assistantNodes.length - 1].innerText || '').trim()
                : '';
            const buttonTexts = Array.from(document.querySelectorAll('button'))
                .map(btn => (btn.innerText || btn.getAttribute('aria-label') || '').trim())
                .filter(Boolean);
            const generatingMarkers = [
                'Stop generating',
                '停止流式传输',
                '停止生成',
                '正在思考',
                '已停止思考',
                'Thinking',
            ];
            return {
                assistant_count: assistantNodes.length,
                last_text: lastAssistant,
                is_generating: buttonTexts.some(text => generatingMarkers.some(marker => text.includes(marker))),
            };
        })()
        """
        try:
            result = _ab(["eval", js_code], timeout=10)
            payload = (result.stdout or "").strip()
            data = json.loads(payload) if payload else {}
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {"assistant_count": 0, "last_text": "", "is_generating": False}

    def _wait_for_response_complete(
        self,
        round_num: int,
        previous_assistant_count: int = 0,
        previous_response: str = "",
    ) -> str:
        """等待回复完成并提取文本（多重策略）"""
        print(f"  [Round {round_num}] 等待回复中...")
        start_time = time.time()

        last_signature: Optional[Tuple[int, str]] = None
        stable_count = 0
        last_error_signature: Optional[Tuple[int, str]] = None
        error_stable_count = 0

        while time.time() - start_time < self.timeout_per_round:
            try:
                result = _ab(["snapshot", "-i"], timeout=15)
                snapshot = result.stdout

                state = self._read_response_state()
                response_text = (state.get("last_text") or "").strip() or self._extract_latest_response(snapshot)
                assistant_count = int(state.get("assistant_count") or 0)
                is_generating = bool(state.get("is_generating")) or any(
                    marker in snapshot for marker in ["Stop generating", "停止流式传输", "停止生成", "正在思考", "已停止思考"]
                )

                has_new_response = assistant_count > previous_assistant_count or (
                    response_text and response_text != previous_response
                )

                if self._looks_like_error_response(response_text, snapshot):
                    error_signature = (assistant_count, response_text)
                    if error_signature == last_error_signature and not is_generating:
                        error_stable_count += 1
                    else:
                        error_stable_count = 1
                        last_error_signature = error_signature

                    print(f"  [!] 检测到 ChatGPT 错误回复，等待重试（{error_stable_count}/2）")
                    stable_count = 0
                    last_signature = None

                    if not is_generating and error_stable_count >= 2:
                        print("  [!] 错误回复已稳定，返回空结果以触发上层重试")
                        return ""
                elif has_new_response and response_text:
                    error_stable_count = 0
                    last_error_signature = None
                    signature = (assistant_count, response_text)
                    if signature == last_signature and not is_generating:
                        stable_count += 1
                    else:
                        stable_count = 1
                        last_signature = signature

                    if is_generating:
                        print(f"  [...] 生成中（assistant={assistant_count}）")
                    else:
                        print(f"  [...] 收到新回复，等待稳定（{stable_count}/2）")

                    if not is_generating and stable_count >= 2:
                        print("  [OK] 回复完成（新回复已稳定）")
                        return response_text
                else:
                    stable_count = 0
                    last_signature = None
                    error_stable_count = 0
                    last_error_signature = None

                time.sleep(3)

            except Exception as e:
                print(f"  [!] 检测回复状态异常: {e}")
                time.sleep(5)

        print(f"  [!] 等待超时（{self.timeout_per_round}s），尝试提取已有内容")
        try:
            final_result = _ab(["snapshot"], timeout=15)
            final_snapshot = final_result.stdout
        except Exception as e:
            print(f"  [!] 获取最终 snapshot 失败: {e}")
            return ""

        final_state = self._read_response_state()
        final_text = (final_state.get("last_text") or "").strip() or self._extract_latest_response(final_snapshot)
        final_count = int(final_state.get("assistant_count") or 0)
        if self._looks_like_error_response(final_text, final_snapshot):
            return ""
        if final_count > previous_assistant_count or (final_text and final_text != previous_response):
            return final_text
        return ""

    def _extract_latest_response(self, snapshot: str) -> str:
        """从 snapshot 提取最新的 assistant 回复文本"""
        try:
            # 使用 eval 执行 JavaScript 提取最新回复
            js_code = """
            (function() {
                const messages = document.querySelectorAll('[data-message-author-role="assistant"]');
                if (messages.length === 0) return '';
                const lastMsg = messages[messages.length - 1];
                return lastMsg.innerText || '';
            })()
            """
            result = _ab(["eval", js_code], timeout=10)
            text = self._normalize_eval_text(result.stdout)
            return text if text else self._extract_from_snapshot_fallback(snapshot)
        except Exception:
            return self._extract_from_snapshot_fallback(snapshot)

    def _extract_from_snapshot_fallback(self, snapshot: str) -> str:
        """Fallback: 从纯文本 snapshot 中提取回复"""
        # 简单策略：取 snapshot 中最后一个已知回复块的文本
        lines = snapshot.split('\n')
        # 找到最后一对 "Assistant" 相关行到末尾
        collected = []
        in_response = False
        for line in lines:
            if any(marker in line for marker in ['[assistant]', 'Assistant', '> assistant']):
                in_response = True
                collected = []
            if in_response:
                collected.append(line)

        if collected:
            # 清理标记，只保留内容
            cleaned = []
            for line in collected:
                # 移除 UI 元素标记
                line = re.sub(r'\[(?:click|type|hover|press).*?\]', '', line)
                line = line.strip()
                if line and not line.startswith('---') and not line.startswith('[ '):
                    cleaned.append(line)
            return '\n'.join(cleaned)
        return ""

    def _build_round_message(self, round_num: int) -> str:
        """构建某一轮要发送的消息。仅第一轮拼接研究主题/市场分析输入，其余轮次逐条原样发送问题块。"""
        if round_num < 1 or round_num > len(self.question_blocks):
            raise IndexError(f"round_num 超出问题块范围: {round_num}")

        block = self.question_blocks[round_num - 1].strip()
        if round_num == 1:
            preface_parts = []
            if self.context_text:
                preface_parts.append(self.context_text)
            else:
                preface_parts.append(f"研究主题：{self.topic}")
            preface_parts.append(block)
            return "\n\n".join(part for part in preface_parts if part.strip())
        return block

    def run_all_rounds(self, start_from: int = 1):
        """执行全部问题块，统一在同一对话中逐轮发送。"""
        self._new_chat()
        time.sleep(2)

        total_rounds = len(self.question_blocks)
        if start_from < 1 or start_from > total_rounds:
            raise ValueError(f"resume-from 必须在 1 到 {total_rounds} 之间")

        for round_num in range(start_from, total_rounds + 1):
            print(f"\n{'='*60}")
            print(f"[Round {round_num}/{total_rounds}] 发送问题块")
            print(f"{'='*60}")

            prompt_text = self._build_round_message(round_num)

            prompt_file = self.output_dir / f"round_{round_num:02d}_prompt.txt"
            prompt_file.write_text(prompt_text, encoding='utf-8')
            print(f"  [保存] prompt → {prompt_file.name}")

            previous_assistant_count = 0
            previous_response = self.round_outputs[-1] if self.round_outputs else ""
            try:
                state_before_send = self._read_response_state()
                previous_assistant_count = int(state_before_send.get("assistant_count") or 0)
                previous_response = (state_before_send.get("last_text") or "").strip() or previous_response
            except Exception:
                pass

            response = ""
            for attempt in range(1, self.max_round_attempts + 1):
                print(f"  [发送] 发送第 {round_num} 轮 prompt (attempt {attempt}/{self.max_round_attempts})...")
                if not self._send_message(prompt_text):
                    print(f"  [!] 发送失败")
                    continue

                response = self._wait_for_response_complete(
                    round_num,
                    previous_assistant_count=previous_assistant_count,
                    previous_response=previous_response,
                )
                if response:
                    break
                print(f"  [!] 回复为空或命中错误回复，准备重试")

            if not response:
                print(f"  [!] 多次尝试后仍无有效回复，跳过")
                continue

            self.round_outputs.append(response)
            output_file = self.output_dir / f"round_{round_num:02d}_output.md"
            output_file.write_text(response, encoding='utf-8')
            print(f"  [保存] 回复 → {output_file.name} ({len(response)} chars)")

            time.sleep(2)

        final_md = build_research_markdown(self.topic, self.round_outputs)
        final_file = self.output_dir / "research_source.md"
        final_file.write_text(final_md, encoding='utf-8')
        print(f"\n[完成] 最终报告 → {final_file}")
        print(f"        输出目录: {self.output_dir}")

        return self.output_dir, final_file


# ─────────────────────────────────────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(description="ChatGPT 网页版自动化行业研究")
    parser.add_argument("--topic", "-t", required=True, help="研究主题（如：固态电池产业链）")
    parser.add_argument("--output-dir", "-o", default=str(DEFAULT_OUTPUT_DIR), help="输出目录")
    parser.add_argument("--headless", action="store_true", help="无头模式（不显示浏览器窗口）")
    parser.add_argument("--resume-from", type=int, default=1, help="从第几轮恢复（1-6）")
    parser.add_argument("--chrome-path", help="手动指定 Chrome 可执行文件路径")
    parser.add_argument("--context-file", help="外部背景资料文件路径（会在第一轮前作为市场分析输入）")
    parser.add_argument("--questions-file", help="自定义六个问题块文件路径（txt/json）")
    return parser.parse_args()


def main():
    args = parse_args()

    print(f"""
╔══════════════════════════════════════════════════════╗
║     ChatGPT 自动化行业研究 — 6 轮递进分析               ║
╠══════════════════════════════════════════════════════╣
║  主题: {args.topic}
║  输出: {args.output_dir}
║  起始轮: {args.resume_from}
║  无头: {args.headless}
╚══════════════════════════════════════════════════════╝
""")

    context_text = ""
    if args.context_file:
        ctx_path = Path(args.context_file)
        if ctx_path.exists():
            context_text = ctx_path.read_text(encoding='utf-8').strip()
            print(f"[背景] 已加载外部资料: {ctx_path}")

    question_blocks = load_question_blocks(args.questions_file)

    # 启动会话管理器
    session = SessionManager(
        profile_dir=PROFILE_DIR,
        headless=args.headless,
        browser_executable=args.chrome_path or BROWSER_EXECUTABLE
    )

    # 启动浏览器
    if not session.ensure_browser_launched():
        print("[错误] 无法启动浏览器，退出")
        sys.exit(1)

    # 检测登录状态
    if not session.check_login_status():
        print("\n[等待] 请在打开的浏览器中登录 ChatGPT...")
        if not session.wait_for_manual_login():
            print("[错误] 登录超时，退出")
            sys.exit(1)

    # 创建自动化器并执行
    automator = ConversationAutomator(
        session=session,
        output_dir=args.output_dir,
        topic=args.topic,
        timeout_per_round=300,
        context_text=context_text,
        question_blocks=question_blocks,
    )

    output_dir, final_file = automator.run_all_rounds(start_from=args.resume_from)

    print(f"\n✅ 全流程完成！")
    print(f"   输出目录: {output_dir}")
    print(f"   最终报告: {final_file}")
    print(f"\n   下一步：将 {final_file.name} 作为 NotebookLM 来源，传入 nb2pptx 流程")


if __name__ == "__main__":
    main()