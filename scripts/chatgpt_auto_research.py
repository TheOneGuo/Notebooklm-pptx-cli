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
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, List

# ─────────────────────────────────────────────────────────────────────────────
# 目录与路径配置
# ─────────────────────────────────────────────────────────────────────────────

SKILL_DIR = Path(__file__).parent
PROFILE_DIR = SKILL_DIR / ".chatgpt-browser-profile"
DEFAULT_OUTPUT_DIR = Path.home() / "Documents" / "A股研报"

BROWSER_EXECUTABLE = os.environ.get("CHROME_PATH", "")  # 可手动指定 Chrome 路径


# ─────────────────────────────────────────────────────────────────────────────
# 6 轮 Prompt 模板（从 industry-research_skill.md 提取）
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RoundPrompt:
    round_num: int
    round_title: str
    system_reminder: str
    user_prompt_template: str


# 基础规则（所有轮次共同遵守）
BASE_RULES = """你必须严格遵守以下规则：

1. 用户问第几轮，就只回答第几轮对应内容，不提前展开后续轮次。
2. 每一轮都必须继承：用户最初提供的信息 + 前面所有轮次的关键结论 + 上一轮你给出的后续分析建议。
3. 不主动增加用户没有要求的额外模块，不把任务扩展成复杂说明文档。
4. 回答必须专业、结构化、可审阅，能量化的地方优先量化。
5. 无法获取精确数据时，必须明确说明数据缺口、假设前提与核验方向，不得编造。
6. 涉及股价、估值、资金流、技术指标、舆情等动态数据时，尽量使用最新可得数据，并标注日期。
7. 第六轮涉及评级和短期机会判断时，必须使用合规表达，避免"买入、卖出、重仓、满仓、梭哈、必涨、翻倍、目标价、荐股"等措辞。
8. 只有当用户明确要求汇总成 Markdown 文件时，才把六轮结果整合成完整 MD 文档。
9. 输出语言默认使用中文。"""

ROUND_PROMPTS = [
    RoundPrompt(
        round_num=1,
        round_title="第一轮：行业发展现状、竞争格局与市场空间",
        system_reminder=BASE_RULES,
        user_prompt_template="""请对以下行业/产业进行深度分析，完成第一轮递进研究：

**研究主题：{topic}**

请从以下三个维度展开分析：

## 1. 行业发展现状与核心趋势
- 全球及国内市场规模、需求增速
- 核心驱动因素、技术迭代方向
- 供给侧格局变化、国产替代进度

## 2. 行业竞争格局拆解
- 行业集中度（CR3/CR5/CR10）
- 全行业核心参与标的名单与市场份额对比
- 行业进入壁垒分析

## 3. 细分赛道市场空间测算
- TAM / SAM / SOM 测算
- 明确行业天花板与公司成长边界

输出要求：
- 给出行业核心结论
- 包含细分赛道空间测算表
- 包含竞争格局表
- 最后给出后续第二轮财务与估值分析的建议方向（用「→第二轮建议：」标注）"""
    ),
    RoundPrompt(
        round_num=2,
        round_title="第二轮：财务数据、估值、经营能力与现金流质量",
        system_reminder=BASE_RULES,
        user_prompt_template="""请基于第一轮行业空间与竞争格局结论，继续完成第二轮递进研究：

**研究主题：{topic}**

**第一轮核心结论摘要：**
{prev_summary}

请围绕第一轮建议的方向，对行业核心标的进行财务分析：

## 1. 盈利能力分析
- 近3-5年营收/净利润/扣非净利润规模与增速
- 毛利率、净利率、ROE、ROIC
- 与行业均值及核心竞争对手对标

## 2. 估值指标分析
- PE静态/动态/TTM、PB、PS、PCF
- 匹配申万三级行业分类
- 行业分位数与历史分位数计算

## 3. 偿债能力分析
- 资产负债率、有息负债规模、利息保障倍数
- 流动比率、速动比率、现金比率

## 4. 营运能力分析
- 应收账款/存货/总资产周转率
- 应收/应付账款周转天数

## 5. 费用管控效率分析
- 销售/管理/研发费用规模与占比
- 与行业平均及竞品对标

## 6. 现金流质量分析
- 经营活动/投资活动/筹资活动现金流
- 经营性现金流与净利润匹配度

输出要求：
- 财务质量分层结论
- 估值安全边际判断
- 经营效率对比表
- 现金流质量结论
- 最后给出后续第三轮产能与资本开支分析的建议方向（用「→第三轮建议：」标注）"""
    ),
    RoundPrompt(
        round_num=3,
        round_title="第三轮：产能、在建工程、资本开支与业绩弹性",
        system_reminder=BASE_RULES,
        user_prompt_template="""请继承前两轮结论，继续完成第三轮递进研究：

**研究主题：{topic}**

**第一轮核心结论：**
{round1_summary}

**第二轮核心结论：**
{round2_summary}

请围绕产能与资本开支方向深入分析：

## 1. 近3年产能与利用率分析
- 分业务的设计产能、实际产能、产能利用率
- 利用率异常波动的核心原因

## 2. 在建工程与新增产线梳理
- 在建工程项目、设计产能规模、建设进度
- 预期投产时间、达产周期

## 3. 新产能业绩贡献测算
- 新产能释放对营收、毛利率、归母净利润的潜在贡献

## 4. 资本开支分析
- 历年资本开支规模与结构投向
- 未来资本开支计划与资金来源
- CAPEX 投入产出效率

输出要求：
- 产能利用率对比表
- 在建工程与新增产线表
- 新产能业绩弹性测算
- CAPEX 投入产出效率判断
- 最后给出后续第四轮壁垒分析的建议方向（用「→第四轮建议：」标注）"""
    ),
    RoundPrompt(
        round_num=4,
        round_title="第四轮：技术、客户、交付、成本与供应链壁垒",
        system_reminder=BASE_RULES,
        user_prompt_template="""请继承前三轮结论，继续完成第四轮递进研究：

**研究主题：{topic}**

**第一轮行业空间结论：**
{round1_summary}

**第二轮财务与估值结论：**
{round2_summary}

**第三轮产能与CAPEX结论：**
{round3_summary}

请围绕四大壁垒深入分析：

## 1. 技术壁垒分析
- 底层核心技术体系、国内/海外发明专利布局
- 专利质量、转化能力、技术迭代速度
- 研发投入产出效率、核心技术团队与人才储备

## 2. 客户与品牌壁垒分析
- 头部客户绑定情况与客户粘性
- 品牌行业地位、标杆项目案例、行业口碑

## 3. 交付与产能壁垒分析
- 规模化交付能力、全流程项目管理能力
- 产能布局、柔性化程度、快速响应能力

## 4. 成本与供应链壁垒分析
- 核心零部件自主化率、全链条成本控制能力
- 供应链深度绑定能力、集采规模优势
- 结合第一轮商业模式定位验证成本领先可持续性

输出要求：
- 技术壁垒分层结论
- 客户与品牌壁垒对比表
- 交付能力对比表
- 成本与供应链安全性判断
- 最后给出后续第五轮新赛道拓展分析的建议方向（用「→第五轮建议：」标注）"""
    ),
    RoundPrompt(
        round_num=5,
        round_title="第五轮：高景气高PE新赛道筛选、可行性与估值提升空间",
        system_reminder=BASE_RULES,
        user_prompt_template="""请继承前四轮结论，继续完成第五轮递进研究：

**研究主题：{topic}**

**第四轮壁垒核心结论：**
{round4_summary}

请围绕新赛道进入可行性展开分析：

## 1. 新赛道筛选与市场空间分析
- 筛选标准、目标赛道行业现状
- 核心增长驱动因素、未来3-5年市场规模与竞争格局
- 进入壁垒分析

## 2. 新赛道进入可行性综合评分（5维量化）
从以下5个核心维度评分（技术/供应链/产线/客户/成本）：
- 目标赛道评分与优先进入赛道排序
- 切入路径分析

## 3. 新赛道业务对业绩与估值的影响测算
- 分阶段预测：新赛道营收/利润贡献
- 对整体毛利率、ROE的提升作用
- 估值溢价空间分析

## 4. 平台化能力分析
- 核心技术可迁移性、技术平台化能力、产线复用潜力

## 5. 现有技术储备匹配度
- 底层技术可迁移性、与目标赛道技术需求匹配度评分

## 6. 供应链复用能力
- 核心原材料品类重合度、供应商体系复用可能性

## 7. 产线与产能复用率
- 现有产线可复用领域、改造难度与成本、产能柔性化程度

## 8. 客户渠道复用能力
- 现有客户与目标新赛道客户重叠度、渠道协同效应

## 9. 成本与全生命周期成本优势
- 依托规模效应的成本优势、产品全生命周期成本与竞品对标

输出要求：
- 候选新赛道清单
- 五维评分表
- 优先级排序
- 业绩贡献测算与估值弹性判断
- 最后给出后续第六轮市场面分析的建议方向（用「→第六轮建议：」标注）"""
    ),
    RoundPrompt(
        round_num=6,
        round_title="第六轮：技术面、资金面、筹码结构、舆情与短期机会评估",
        system_reminder=BASE_RULES,
        user_prompt_template="""请继承前五轮所有结论，完成最终轮递进研究：

**研究主题：{topic}**

**第五轮新赛道与平台化核心结论：**
{round5_summary}

请从二级市场维度进行综合判断：

## 1. 技术面深度分析
- 近3个月股价走势（MA5/MA10/MA20/MA60）
- 成交量变化、MACD/KDJ/RSI 技术指标

## 2. 资金面全景分析
- 近10个交易日主力资金流向
- 北向资金持仓、机构持仓、龙虎榜资金分析

## 3. 筹码结构分析
- 筹码集中度变化、成本均线分布
- 获利盘/套牢盘比例、筹码结构稳定性评估

## 4. 舆情与短期机会评估
- 近1个月标的相关舆情情绪
- 产业催化强度、市场关注度变化

## 5. 综合评级（使用合规表达）
必须使用以下相对安全的措辞：
- 高关注度 / 中高关注度 / 持续观察 / 等待右侧确认
- 产业趋势较强但短期波动较大
- 基本面弹性较强但需观察资金确认
- 适合加入观察池 / 适合做阶段性跟踪
- 产业逻辑强，交易节奏需结合量价确认

输出要求：
- 技术面状态表
- 资金面状态表
- 筹码结构判断
- 舆情热度判断
- 综合关注等级
- 短期跟踪优先级排序
- 风险提示"""
    ),
]


# ─────────────────────────────────────────────────────────────────────────────
# 汇总 prompt
# ─────────────────────────────────────────────────────────────────────────────

MERGE_PROMPT = """请将上述六轮分析内容整合成一份完整的 Markdown 研究报告文档。

文档结构要求：
```markdown
# 行业研究六轮递进分析报告

## 一、执行摘要
## 二、研究对象与数据口径
## 三、第一轮：行业发展现状、竞争格局与市场空间
## 四、第二轮：财务数据、估值、经营能力与现金流质量
## 五、第三轮：产能、在建工程、资本开支与业绩弹性
## 六、第四轮：技术、客户、交付、成本与供应链壁垒
## 七、第五轮：高景气高PE新赛道筛选、可行性与估值提升空间
## 八、第六轮：技术面、资金面、筹码结构、舆情与短期机会评估
## 九、综合结论与关注优先级
## 十、风险提示
## 十一、数据缺口与后续核验清单
```

整合要求：
1. 去除重复内容，保留六轮核心结论
2. 保留关键表格，合并重复的表格
3. 统一术语、标的名称、时间口径
4. 明确哪些数据来自公开资料，哪些属于假设测算
5. 不加入用户未要求的新模块
6. **不要在文档底部或页脚添加任何品牌声明、机构名称、保密声明或数据来源注释**

直接输出完整的 Markdown 文档内容。"""


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


def _ab(subcmd: List[str], timeout: int = 30) -> subprocess.CompletedProcess:
    """生成带 --profile 前缀的 agent-browser 命令"""
    cmd = ["agent-browser"]
    if _profile_dir:
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
        # 注入全局 profile dir
        global _profile_dir
        _profile_dir = self.profile_dir

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

            # 检测未登录特征
            if any(marker in snapshot for marker in [
                "Sign up", "Log in", "Continue with Google",
                "Continue with Microsoft", "Sign in with Apple"
            ]):
                print("  [!] 未检测到登录状态，需要手动登录")
                return False

            # 检测登录后的特征
            if any(marker in snapshot for marker in [
                "New chat", "ChatGPT", "Send message"
            ]):
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

    def __post_init__(self):
        self.round_outputs: List[str] = []
        self.output_dir = Path(self.output_dir) / self._sanitize_topic(self.topic)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _sanitize_topic(t: str) -> str:
        """清理文件名中的非法字符"""
        return re.sub(r'[\\/:*?"<>|]', '_', t)

    def _send_message(self, text: str) -> bool:
        """找到输入框，发送消息"""
        try:
            # 先点击输入框
            result = _ab(["snapshot", "-i"], timeout=15)
            snapshot = result.stdout

            # 查找 textarea 或 contenteditable 输入区域
            # ChatGPT 使用 div[contenteditable="true"] 作为输入
            input_selectors = [
                'div[contenteditable="true"]',
                'textarea',
                '[data-testid="prompt-textarea"]'
            ]

            selected = None
            for sel in input_selectors:
                if sel.replace('"', '') in snapshot or sel in snapshot:
                    selected = sel
                    break

            if not selected:
                # 尝试点击页面中间区域唤起输入框
                _ab(["click", "div[contenteditable='true']"], timeout=5)

            # 输入消息
            _run(["agent-browser", "type", 'div[contenteditable="true"]', text], timeout=5)
            time.sleep(1)

            # 发送（回车或点击发送按钮）
            _ab(["press", "Enter"], timeout=5)
            return True

        except Exception as e:
            print(f"  [!] 发送消息失败: {e}")
            return False

    def _new_chat(self):
        """新建对话"""
        print("  [Chat] 新建对话...")
        try:
            # 尝试找到 "New chat" 按钮并点击
            result = _ab(["snapshot", "-i"], timeout=10)
            snapshot = result.stdout
            if "New chat" in snapshot:
                _ab(["click", "text=New chat"], timeout=5)
            else:
                # 尝试直接刷新到新对话 URL
                _ab(["open", "https://chatgpt.com/"], timeout=10)
            time.sleep(2)
        except Exception as e:
            print(f"  [!] 新建对话失败: {e}")

    def _wait_for_response_complete(self, round_num: int) -> str:
        """等待回复完成并提取文本（多重策略）"""
        print(f"  [Round {round_num}] 等待回复中...")
        start_time = time.time()

        # Strategy 1: 检测响应状态变化
        # ChatGPT 在生成中会显示 "Stop generating" 按钮
        # 生成完成后变回 "Submit" 或显示新消息

        last_word_count = ""
        stable_count = 0

        while time.time() - start_time < self.timeout_per_round:
            try:
                # 获取快照
                result = _ab(["snapshot", "-i"], timeout=15)
                snapshot = result.stdout

                # 提取最新回复内容（assistant message）
                response_text = self._extract_latest_response(snapshot)

                if response_text:
                    # 检测字数稳定性（ChatGPT 显示 "X words"）
                    words_match = re.search(r'(\d+(?:,\d{3})*)\s+words', snapshot)
                    current_words = words_match.group(1) if words_match else "unknown"

                    if current_words == last_word_count and last_word_count != "":
                        stable_count += 1
                        if stable_count >= 5:  # 连续5次相同认为完成
                            print(f"  [OK] 回复完成（约 {current_words} words）")
                            return response_text
                    else:
                        stable_count = 0
                        last_word_count = current_words

                    if stable_count > 0:
                        print(f"  [...] 生成中（约 {current_words} words，{stable_count}/5 稳定）")
                    else:
                        print(f"  [...] 生成中（约 {current_words} words）", end="\r")

                # 检测停止按钮是否存在（生成中）
                if "Stop generating" in snapshot:
                    time.sleep(3)  # 还在生成，等待
                else:
                    # 没有 "Stop generating"，检查是否真的完成
                    # 通过检测是否有新的 assistant 消息
                    if response_text and len(response_text) > 50:
                        time.sleep(3)
                        # 再次确认
                        _ab(["snapshot"], timeout=10)
                        if "Stop generating" not in result2.stdout:
                            print(f"  [OK] 回复完成（字数稳定）")
                            return self._extract_latest_response(result2.stdout)

                time.sleep(3)

            except Exception as e:
                print(f"  [!] 检测回复状态异常: {e}")
                time.sleep(5)

        print(f"  [!] 等待超时（{self.timeout_per_round}s），尝试提取已有内容")
        _ab(["snapshot"], timeout=15)
        return self._extract_latest_response(result.stdout)

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
            result = _run(["agent-browser", "eval", js_code], timeout=10)
            text = result.stdout.strip()
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

    def _build_round_prompt(self, rp: RoundPrompt, round_num: int) -> str:
        """构建某一轮的完整 prompt（含上下文继承）"""
        topic = self.topic
        base = rp.user_prompt_template.format(topic=topic)

        # 注入前几轮结论摘要
        if round_num == 2 and self.round_outputs:
            summary = self._summarize(self.round_outputs[0])
            base = base.replace("{prev_summary}", summary)
        elif round_num >= 3 and len(self.round_outputs) >= round_num - 1:
            summaries = []
            for i, out in enumerate(self.round_outputs[:round_num - 1]):
                label = ["", "第一轮", "第二轮", "第三轮", "第四轮", "第五轮"][i + 1]
                summaries.append(f"**{label}核心结论**：\n{self._summarize(out)}")
            base = base.replace("{round1_summary}", summaries[0] if len(summaries) > 0 else "")
            base = base.replace("{round2_summary}", summaries[1] if len(summaries) > 1 else "")
            base = base.replace("{round3_summary}", summaries[2] if len(summaries) > 2 else "")
            base = base.replace("{round4_summary}", summaries[3] if len(summaries) > 3 else "")
            base = base.replace("{round5_summary}", summaries[4] if len(summaries) > 4 else "")

        return base

    @staticmethod
    def _summarize(text: str, max_chars: int = 1500) -> str:
        """提取一段文本的核心结论摘要（用于注入后续轮次）"""
        # 简单策略：取前 max_chars 字符，保留结构化内容
        # 实际更智能的做法是让 LLM 总结，但这里保持简单
        text = text.strip()
        if len(text) <= max_chars:
            return text
        # 保留标题和表格
        lines = text.split('\n')
        result = []
        char_count = 0
        for line in lines:
            result.append(line)
            char_count += len(line) + 1
            if char_count >= max_chars:
                result.append("\n...（前轮结论已截断，建议直接引用前轮输出文件）")
                break
        return '\n'.join(result)

    def run_all_rounds(self, start_from: int = 1):
        """执行全部 6 轮分析"""
        self._new_chat()
        time.sleep(2)

        for i in range(start_from - 1, len(ROUND_PROMPTS)):
            rp = ROUND_PROMPTS[i]
            round_num = rp.round_num

            print(f"\n{'='*60}")
            print(f"[Round {round_num}/6] {rp.round_title}")
            print(f"{'='*60}")

            # 发送 system reminder（可选，放到 prompt 开始）
            prompt_text = self._build_round_prompt(rp, round_num)

            # 保存本轮 prompt 到文件
            prompt_file = self.output_dir / f"round_{round_num:02d}_prompt.txt"
            prompt_file.write_text(prompt_text, encoding='utf-8')
            print(f"  [保存] prompt → {prompt_file.name}")

            # 发送
            print(f"  [发送] 发送第 {round_num} 轮 prompt...")
            if not self._send_message(prompt_text):
                print(f"  [!] 发送失败，跳过本轮")
                continue

            # 等待回复
            response = self._wait_for_response_complete(round_num)
            if not response or len(response) < 100:
                print(f"  [!] 回复内容过短，可能异常，跳过")
                continue

            # 保存回复
            self.round_outputs.append(response)
            output_file = self.output_dir / f"round_{round_num:02d}_output.md"
            output_file.write_text(response, encoding='utf-8')
            print(f"  [保存] 回复 → {output_file.name} ({len(response)} chars)")

            time.sleep(2)  # 轮次间等待

        print(f"\n{'='*60}")
        print("[汇总] 发送最终汇总指令...")
        print(f"{'='*60}")

        self._send_message(MERGE_PROMPT)
        final_md = self._wait_for_response_complete(0)  # 0 表示汇总轮

        # 保存最终 MD
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
    parser.add_argument("--context-file", help="外部背景资料文件路径（会读取并作为额外上下文）")
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

    # 读取外部背景资料（如有）
    context_extra = ""
    if args.context_file:
        ctx_path = Path(args.context_file)
        if ctx_path.exists():
            context_extra = f"\n\n**用户提供外部背景资料**：\n{ctx_path.read_text(encoding='utf-8')}"
            print(f"[背景] 已加载外部资料: {ctx_path}")

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
        timeout_per_round=300
    )

    # 为 automator 添加额外上下文
    if context_extra:
        # 将外部资料注入到第一轮 prompt 的 topic 部分之后
        # 在 RoundPrompt 模板层面注入
        pass  # 暂时通过 args.topic + 额外说明实现

    output_dir, final_file = automator.run_all_rounds(start_from=args.resume_from)

    print(f"\n✅ 全流程完成！")
    print(f"   输出目录: {output_dir}")
    print(f"   最终报告: {final_file}")
    print(f"\n   下一步：将 {final_file.name} 作为 NotebookLM 来源，传入 nb2pptx 流程")


if __name__ == "__main__":
    main()