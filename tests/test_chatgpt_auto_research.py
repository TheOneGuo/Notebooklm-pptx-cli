from pathlib import Path
import importlib.util
import subprocess
from types import SimpleNamespace


def load_module(module_name: str, relative_path: str):
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


chatgpt_auto_research = load_module(
    "chatgpt_auto_research", "scripts/chatgpt_auto_research.py"
)


def completed(stdout: str = "", stderr: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_check_login_status_treats_localized_login_page_as_logged_out(monkeypatch, tmp_path):
    def fake_ab(subcmd, timeout=30):
        if subcmd[:2] == ["open", "https://chatgpt.com/"]:
            return completed()
        if subcmd[:1] == ["snapshot"]:
            return completed(
                '- button "登录"\n'
                '- button "免费注册"\n'
                '- button "模型选择器": ChatGPT\n'
            )
        raise AssertionError(f"unexpected command: {subcmd}")

    monkeypatch.setattr(chatgpt_auto_research, "_ab", fake_ab)
    monkeypatch.setattr(chatgpt_auto_research.time, "sleep", lambda *_: None)

    session = chatgpt_auto_research.SessionManager(profile_dir=tmp_path / "profile")

    assert session.check_login_status() is False


def test_ab_prefers_configured_cdp_port_over_profile(monkeypatch, tmp_path):
    captured = []

    def fake_run(cmd, timeout=30):
        captured.append(cmd)
        return completed()

    monkeypatch.setattr(chatgpt_auto_research, "_run", fake_run)
    monkeypatch.setattr(chatgpt_auto_research, "_profile_dir", tmp_path / "profile")
    monkeypatch.setattr(chatgpt_auto_research, "_cdp_port", 9222, raising=False)

    chatgpt_auto_research._ab(["get", "title"])

    assert captured == [["agent-browser", "--cdp", "9222", "get", "title"]]


def test_send_message_uses_native_setter_and_form_submit_instead_of_press_enter(monkeypatch, tmp_path):
    captured = []
    submit_state_payloads = iter([
        '{"user_count": 1, "assistant_count": 1, "composer_text": "", "is_generating": false}',
        '{"user_count": 1, "assistant_count": 1, "composer_text": "", "is_generating": true}',
    ])

    def fake_run(cmd, timeout=30):
        captured.append(cmd)
        if "snapshot" in cmd:
            return completed('textbox "与 ChatGPT 聊天"\n')
        if "eval" in cmd:
            script = cmd[-1]
            if 'user_count' in script and 'composer_text' in script:
                return completed(next(submit_state_payloads))
            if 'requestSubmit' in script:
                return completed('{"ok": true, "submitted": true, "method": "requestSubmit"}')
            return completed()
        if "focus" in cmd:
            return completed()
        if "type" in cmd:
            return completed()
        if cmd[-2:] == ["press", "Shift+Enter"]:
            return completed()
        if cmd[-2:] == ["press", "Enter"]:
            return completed()
        if cmd[-2:] == ["press", "Control+a"]:
            return completed()
        if cmd[-2:] == ["press", "Backspace"]:
            return completed()
        return completed()

    monkeypatch.setattr(chatgpt_auto_research, "_run", fake_run)
    monkeypatch.setattr(chatgpt_auto_research, "_detect_cdp_port", lambda: None)
    monkeypatch.setattr(chatgpt_auto_research.time, "sleep", lambda *_: None)

    session = chatgpt_auto_research.SessionManager(profile_dir=tmp_path / "profile")
    automator = chatgpt_auto_research.ConversationAutomator(
        session=session,
        output_dir=tmp_path,
        topic="测试主题",
    )

    assert automator._send_message("hello") is True

    eval_cmds = [cmd for cmd in captured if "eval" in cmd]
    assert len(eval_cmds) >= 2
    assert eval_cmds[0][:3] == [
        "agent-browser",
        "--profile",
        str(tmp_path / "profile"),
    ]
    assert any("Object.getOwnPropertyDescriptor" in cmd[-1] for cmd in eval_cmds)
    assert any("InputEvent" in cmd[-1] for cmd in eval_cmds)
    assert any("requestSubmit" in cmd[-1] for cmd in eval_cmds)
    assert not any("type" in cmd for cmd in captured)
    assert not any(cmd[-2:] == ["press", "Enter"] for cmd in captured)


def test_send_message_falls_back_to_agent_browser_type_when_dom_submit_does_not_create_message(monkeypatch, tmp_path):
    captured = []
    submit_state_payloads = iter([
        '{"user_count": 0, "assistant_count": 0, "composer_text": "", "is_generating": false}',
        '{"user_count": 0, "assistant_count": 0, "composer_text": "", "is_generating": false}',
        '{"user_count": 0, "assistant_count": 0, "composer_text": "", "is_generating": false}',
        '{"user_count": 1, "assistant_count": 0, "composer_text": "", "is_generating": true}',
    ])

    def fake_run(cmd, timeout=30):
        captured.append(cmd)
        if "snapshot" in cmd:
            return completed('textbox "与 ChatGPT 聊天"\n')
        if "eval" in cmd:
            script = cmd[-1]
            if 'user_count' in script and 'composer_text' in script:
                return completed(next(submit_state_payloads))
            if 'requestSubmit' in script:
                return completed('{"ok": true, "submitted": true, "method": "requestSubmit"}')
            return completed()
        if "type" in cmd:
            return completed()
        if cmd[-2:] == ["press", "Shift+Enter"]:
            return completed()
        if cmd[-2:] == ["press", "Enter"]:
            return completed()
        if cmd[-2:] == ["press", "Control+a"]:
            return completed()
        if cmd[-2:] == ["press", "Backspace"]:
            return completed()
        if cmd[:4] == ["agent-browser", "--profile", str(tmp_path / "profile"), "focus"]:
            return completed()
        return completed()

    monkeypatch.setattr(chatgpt_auto_research, "_run", fake_run)
    monkeypatch.setattr(chatgpt_auto_research, "_detect_cdp_port", lambda: None)
    monkeypatch.setattr(chatgpt_auto_research.time, "sleep", lambda *_: None)

    session = chatgpt_auto_research.SessionManager(profile_dir=tmp_path / "profile")
    automator = chatgpt_auto_research.ConversationAutomator(
        session=session,
        output_dir=tmp_path,
        topic="测试主题",
    )

    assert automator._send_message("hello") is True

    type_cmds = [cmd for cmd in captured if "type" in cmd]
    assert type_cmds == [[
        "agent-browser",
        "--profile",
        str(tmp_path / "profile"),
        "type",
        'div[contenteditable="true"][role="textbox"]',
        "hello",
    ]]
    assert [cmd[-1] for cmd in captured if cmd[-2:] == ["press", "Shift+Enter"]] == []
    assert [cmd[-1] for cmd in captured if cmd[-2:] == ["press", "Enter"]] == ["Enter"]


def test_send_message_requires_delta_from_preexisting_counts_before_returning_success(monkeypatch, tmp_path):
    captured = []
    submit_state_payloads = iter([
        '{"user_count": 1, "assistant_count": 1, "composer_text": "", "is_generating": false}',
        '{"user_count": 1, "assistant_count": 1, "composer_text": "", "is_generating": false}',
        '{"user_count": 1, "assistant_count": 1, "composer_text": "", "is_generating": false}',
        '{"user_count": 2, "assistant_count": 1, "composer_text": "", "is_generating": true}',
    ])

    def fake_run(cmd, timeout=30):
        captured.append(cmd)
        if "snapshot" in cmd:
            return completed('textbox "与 ChatGPT 聊天"\n')
        if "eval" in cmd:
            script = cmd[-1]
            if 'user_count' in script and 'composer_text' in script:
                return completed(next(submit_state_payloads))
            if 'requestSubmit' in script:
                return completed('{"ok": true, "submitted": true, "method": "requestSubmit"}')
            return completed()
        if "type" in cmd:
            return completed()
        if cmd[-2:] == ["press", "Shift+Enter"]:
            return completed()
        if cmd[-2:] == ["press", "Enter"]:
            return completed()
        if cmd[-2:] == ["press", "Control+a"]:
            return completed()
        if cmd[-2:] == ["press", "Backspace"]:
            return completed()
        if cmd[:4] == ["agent-browser", "--profile", str(tmp_path / "profile"), "focus"]:
            return completed()
        return completed()

    monkeypatch.setattr(chatgpt_auto_research, "_run", fake_run)
    monkeypatch.setattr(chatgpt_auto_research, "_detect_cdp_port", lambda: None)
    monkeypatch.setattr(chatgpt_auto_research.time, "sleep", lambda *_: None)

    session = chatgpt_auto_research.SessionManager(profile_dir=tmp_path / "profile")
    automator = chatgpt_auto_research.ConversationAutomator(
        session=session,
        output_dir=tmp_path,
        topic="测试主题",
    )

    assert automator._send_message("hello") is True

    type_cmds = [cmd for cmd in captured if "type" in cmd]
    assert type_cmds == [[
        "agent-browser",
        "--profile",
        str(tmp_path / "profile"),
        "type",
        'div[contenteditable="true"][role="textbox"]',
        "hello",
    ]]


def test_new_chat_prefers_localized_create_button_via_dom_click(monkeypatch, tmp_path):
    calls = []
    snapshots = iter([
        '- link "新聊天" [ref=e3]\n- link "New chat" [ref=e20]\n- textbox "与 ChatGPT 聊天" [ref=e85]\n',
    ])
    states = iter([
        {"url": "https://chatgpt.com/", "title": "ChatGPT", "user_count": 0, "assistant_count": 0, "composer_text": "", "has_composer": True},
    ])

    def fake_ab(subcmd, timeout=30):
        calls.append(subcmd)
        if subcmd[:2] == ["snapshot", "-i"]:
            return completed(next(snapshots))
        if subcmd[:1] == ["eval"]:
            return completed('{"clicked": true, "selector": "a[data-testid=\\"create-new-chat-button\\"][data-active][href=\\"/\\"]", "text": "新聊天"}')
        raise AssertionError(f"unexpected command: {subcmd}")

    monkeypatch.setattr(chatgpt_auto_research, "_ab", fake_ab)
    monkeypatch.setattr(chatgpt_auto_research.time, "sleep", lambda *_: None)

    session = chatgpt_auto_research.SessionManager(profile_dir=tmp_path / "profile")
    automator = chatgpt_auto_research.ConversationAutomator(
        session=session,
        output_dir=tmp_path,
        topic="测试主题",
    )
    monkeypatch.setattr(automator, "_read_chat_state", lambda: next(states))

    assert automator._new_chat() is True
    eval_cmds = [cmd for cmd in calls if cmd[:1] == ["eval"]]
    assert len(eval_cmds) == 1
    assert "create-new-chat-button" in eval_cmds[0][-1]
    assert [cmd for cmd in calls if cmd[:2] == ["open", "https://chatgpt.com/"]] == []


def test_new_chat_requires_verified_fresh_chat_state_before_returning_success(monkeypatch, tmp_path):
    calls = []
    snapshots = iter([
        '- link "新聊天" [ref=e3]\n- textbox "与 ChatGPT 聊天" [ref=e85]\n',
    ])
    states = iter([
        {"url": "https://chatgpt.com/c/old", "title": "旧会话", "user_count": 1, "assistant_count": 1, "composer_text": "二、继续", "has_composer": True},
        {"url": "https://chatgpt.com/", "title": "ChatGPT", "user_count": 0, "assistant_count": 0, "composer_text": "", "has_composer": True},
    ])

    def fake_ab(subcmd, timeout=30):
        calls.append(subcmd)
        if subcmd[:2] == ["snapshot", "-i"]:
            return completed(next(snapshots))
        if subcmd[:1] == ["eval"]:
            return completed('{"clicked": true, "selector": "a[data-testid=\\"create-new-chat-button\\"][href=\\"/\\"]", "text": "新聊天"}')
        raise AssertionError(f"unexpected command: {subcmd}")

    monkeypatch.setattr(chatgpt_auto_research, "_ab", fake_ab)
    monkeypatch.setattr(chatgpt_auto_research.time, "sleep", lambda *_: None)

    session = chatgpt_auto_research.SessionManager(profile_dir=tmp_path / "profile")
    automator = chatgpt_auto_research.ConversationAutomator(
        session=session,
        output_dir=tmp_path,
        topic="测试主题",
    )
    monkeypatch.setattr(automator, "_read_chat_state", lambda: next(states))

    assert automator._new_chat() is True
    assert sum(1 for cmd in calls if cmd[:1] == ["eval"]) == 1


def test_extract_latest_response_routes_eval_through_connection_aware_command(monkeypatch, tmp_path):
    captured = []

    def fake_run(cmd, timeout=30):
        captured.append(cmd)
        if "eval" in cmd:
            return completed('"assistant reply"')
        return completed()

    monkeypatch.setattr(chatgpt_auto_research, "_run", fake_run)
    monkeypatch.setattr(chatgpt_auto_research, "_detect_cdp_port", lambda: None)

    session = chatgpt_auto_research.SessionManager(profile_dir=tmp_path / "profile")
    automator = chatgpt_auto_research.ConversationAutomator(
        session=session,
        output_dir=tmp_path,
        topic="测试主题",
    )

    assert automator._extract_latest_response("ignored snapshot") == "assistant reply"

    eval_cmds = [cmd for cmd in captured if "eval" in cmd]
    assert eval_cmds == [[
        "agent-browser",
        "--profile",
        str(tmp_path / "profile"),
        "eval",
        """
            (function() {
                const messages = document.querySelectorAll('[data-message-author-role=\"assistant\"]');
                if (messages.length === 0) return '';
                const lastMsg = messages[messages.length - 1];
                return lastMsg.innerText || '';
            })()
            """,
    ]]


def test_extract_latest_response_treats_quoted_empty_eval_payload_as_empty(monkeypatch, tmp_path):
    def fake_run(cmd, timeout=30):
        if "eval" in cmd:
            return completed('""')
        return completed()

    monkeypatch.setattr(chatgpt_auto_research, "_run", fake_run)
    monkeypatch.setattr(chatgpt_auto_research, "_detect_cdp_port", lambda: None)

    session = chatgpt_auto_research.SessionManager(profile_dir=tmp_path / "profile")
    automator = chatgpt_auto_research.ConversationAutomator(
        session=session,
        output_dir=tmp_path,
        topic="测试主题",
    )

    assert automator._extract_latest_response("ignored snapshot") == ""


def test_wait_for_response_complete_ignores_stale_assistant_reply_until_a_new_one_arrives(monkeypatch, tmp_path):
    snapshots = iter([
        '页面中已有旧回复\n',
        '页面中已有旧回复\n停止流式传输\n',
        '页面中已有新回复\n',
        '页面中已有新回复\n',
    ])
    states = iter([
        {"assistant_count": 1, "last_text": "旧回复", "is_generating": False},
        {"assistant_count": 1, "last_text": "旧回复扩写中", "is_generating": True},
        {"assistant_count": 2, "last_text": "新的完整回复", "is_generating": False},
        {"assistant_count": 2, "last_text": "新的完整回复", "is_generating": False},
    ])

    def fake_ab(subcmd, timeout=30):
        if subcmd[:1] == ["snapshot"]:
            return completed(next(snapshots))
        raise AssertionError(f"unexpected command: {subcmd}")

    monkeypatch.setattr(chatgpt_auto_research, "_ab", fake_ab)
    monkeypatch.setattr(chatgpt_auto_research.time, "sleep", lambda *_: None)

    session = chatgpt_auto_research.SessionManager(profile_dir=tmp_path / "profile")
    automator = chatgpt_auto_research.ConversationAutomator(
        session=session,
        output_dir=tmp_path,
        topic="测试主题",
        timeout_per_round=1,
    )
    monkeypatch.setattr(automator, "_read_response_state", lambda: next(states))

    assert automator._wait_for_response_complete(
        round_num=1,
        previous_assistant_count=1,
        previous_response="旧回复",
    ) == "新的完整回复"


def test_wait_for_response_complete_treats_localized_stop_button_as_generating(monkeypatch, tmp_path):
    snapshots = iter([
        '停止流式传输\n',
        '停止流式传输\n',
        '生成完成\n',
        '生成完成\n',
    ])
    states = iter([
        {"assistant_count": 2, "last_text": "第一段", "is_generating": True},
        {"assistant_count": 2, "last_text": "第一段 第二段", "is_generating": True},
        {"assistant_count": 2, "last_text": "第一段 第二段 完整", "is_generating": False},
        {"assistant_count": 2, "last_text": "第一段 第二段 完整", "is_generating": False},
    ])

    def fake_ab(subcmd, timeout=30):
        if subcmd[:1] == ["snapshot"]:
            return completed(next(snapshots))
        raise AssertionError(f"unexpected command: {subcmd}")

    monkeypatch.setattr(chatgpt_auto_research, "_ab", fake_ab)
    monkeypatch.setattr(chatgpt_auto_research.time, "sleep", lambda *_: None)

    session = chatgpt_auto_research.SessionManager(profile_dir=tmp_path / "profile")
    automator = chatgpt_auto_research.ConversationAutomator(
        session=session,
        output_dir=tmp_path,
        topic="测试主题",
        timeout_per_round=1,
    )
    monkeypatch.setattr(automator, "_read_response_state", lambda: next(states))

    assert automator._wait_for_response_complete(
        round_num=2,
        previous_assistant_count=1,
        previous_response="旧回复",
    ) == "第一段 第二段 完整"


def test_wait_for_response_complete_returns_empty_for_chatgpt_error_stub(monkeypatch, tmp_path):
    snapshots = iter([
        'Something went wrong\n重试\n',
        'Something went wrong\n重试\n',
        'Something went wrong\n重试\n',
    ])
    states = iter([
        {"assistant_count": 1, "last_text": "Something went wrong while generating the response. If this issue persists please contact us through our help center at help.openai.com.\n\n重试", "is_generating": False},
        {"assistant_count": 1, "last_text": "Something went wrong while generating the response. If this issue persists please contact us through our help center at help.openai.com.\n\n重试", "is_generating": False},
        {"assistant_count": 1, "last_text": "Something went wrong while generating the response. If this issue persists please contact us through our help center at help.openai.com.\n\n重试", "is_generating": False},
        {"assistant_count": 1, "last_text": "Something went wrong while generating the response. If this issue persists please contact us through our help center at help.openai.com.\n\n重试", "is_generating": False},
    ])

    def fake_ab(subcmd, timeout=30):
        if subcmd[:1] == ["snapshot"]:
            return completed(next(snapshots))
        raise AssertionError(f"unexpected command: {subcmd}")

    monkeypatch.setattr(chatgpt_auto_research, "_ab", fake_ab)
    monkeypatch.setattr(chatgpt_auto_research.time, "sleep", lambda *_: None)

    session = chatgpt_auto_research.SessionManager(profile_dir=tmp_path / "profile")
    automator = chatgpt_auto_research.ConversationAutomator(
        session=session,
        output_dir=tmp_path,
        topic="测试主题",
        timeout_per_round=1,
    )
    monkeypatch.setattr(automator, "_read_response_state", lambda: next(states))

    assert automator._wait_for_response_complete(
        round_num=1,
        previous_assistant_count=0,
        previous_response="",
    ) == ""


def test_run_all_rounds_retries_when_first_response_is_chatgpt_error_stub(monkeypatch, tmp_path):
    session = chatgpt_auto_research.SessionManager(profile_dir=tmp_path / "profile")
    automator = chatgpt_auto_research.ConversationAutomator(
        session=session,
        output_dir=tmp_path,
        topic="测试主题",
        question_blocks=["第一问原文"],
        timeout_per_round=1,
        max_round_attempts=2,
    )

    send_attempts = []
    wait_calls = []
    new_chat_called = []
    responses = iter(["", "第二次尝试后的有效回复"])

    monkeypatch.setattr(automator, "_new_chat", lambda: new_chat_called.append(True))
    monkeypatch.setattr(automator, "_send_message", lambda text: send_attempts.append(text) or True)
    monkeypatch.setattr(
        automator,
        "_wait_for_response_complete",
        lambda *args, **kwargs: wait_calls.append((args, kwargs)) or next(responses),
    )
    monkeypatch.setattr(automator, "_read_response_state", lambda: {"assistant_count": 0, "last_text": "", "is_generating": False})
    monkeypatch.setattr(chatgpt_auto_research.time, "sleep", lambda *_: None)

    output_dir, final_file = automator.run_all_rounds()

    assert new_chat_called == [True]
    assert send_attempts == ["研究主题：测试主题\n\n第一问原文", "研究主题：测试主题\n\n第一问原文"]
    assert len(wait_calls) == 2
    assert output_dir.exists()
    assert final_file.read_text(encoding="utf-8") == (
        "# 测试主题\n\n"
        "## 第一轮\n\n第二次尝试后的有效回复\n"
    )


def test_build_round_message_only_includes_market_context_for_first_round(tmp_path):
    session = chatgpt_auto_research.SessionManager(profile_dir=tmp_path / "profile")
    automator = chatgpt_auto_research.ConversationAutomator(
        session=session,
        output_dir=tmp_path,
        topic="测试主题",
        context_text="市场分析原文",
        question_blocks=["第一问原文", "继续，第二问原文"],
    )

    assert automator._build_round_message(1) == "市场分析原文\n\n第一问原文"
    assert automator._build_round_message(2) == "继续，第二问原文"


def test_build_round_message_includes_topic_when_no_context_text(tmp_path):
    session = chatgpt_auto_research.SessionManager(profile_dir=tmp_path / "profile")
    automator = chatgpt_auto_research.ConversationAutomator(
        session=session,
        output_dir=tmp_path,
        topic="固态电池产业链",
        context_text="",
        question_blocks=["第一问原文", "继续，第二问原文"],
    )

    assert automator._build_round_message(1) == "研究主题：固态电池产业链\n\n第一问原文"
    assert automator._build_round_message(2) == "继续，第二问原文"


def test_run_all_rounds_posts_only_question_blocks_after_round1(monkeypatch, tmp_path):
    session = chatgpt_auto_research.SessionManager(profile_dir=tmp_path / "profile")
    automator = chatgpt_auto_research.ConversationAutomator(
        session=session,
        output_dir=tmp_path,
        topic="测试主题",
        context_text="市场分析原文",
        question_blocks=["第一问原文", "继续，第二问原文", "继续，第三问原文"],
        timeout_per_round=1,
    )

    sent_messages = []
    responses = iter(["第一轮回复", "第二轮回复", "第三轮回复"])
    new_chat_called = []

    monkeypatch.setattr(automator, "_new_chat", lambda: new_chat_called.append(True))
    monkeypatch.setattr(automator, "_send_message", lambda text: sent_messages.append(text) or True)
    monkeypatch.setattr(automator, "_wait_for_response_complete", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(automator, "_read_response_state", lambda: {"assistant_count": 0, "last_text": "", "is_generating": False})
    monkeypatch.setattr(chatgpt_auto_research.time, "sleep", lambda *_: None)

    output_dir, final_file = automator.run_all_rounds()

    assert new_chat_called == [True]
    assert sent_messages == [
        "市场分析原文\n\n第一问原文",
        "继续，第二问原文",
        "继续，第三问原文",
    ]
    assert output_dir.exists()
    assert final_file.read_text(encoding="utf-8") == (
        "# 测试主题\n\n"
        "## 第一轮\n\n第一轮回复\n\n"
        "## 第二轮\n\n第二轮回复\n\n"
        "## 第三轮\n\n第三轮回复\n"
    )


def test_parse_args_accepts_question_file_and_main_injects_context(monkeypatch, tmp_path):
    questions_file = tmp_path / "questions.txt"
    questions_file.write_text("一、Q1\n\n二、Q2\n\n三、Q3\n\n四、Q4\n\n五、Q5\n\n六、Q6\n", encoding="utf-8")
    context_file = tmp_path / "context.md"
    context_file.write_text("外部市场分析", encoding="utf-8")

    monkeypatch.setattr(
        chatgpt_auto_research.argparse.ArgumentParser,
        "parse_args",
        lambda self: SimpleNamespace(
            topic="测试主题",
            output_dir=str(tmp_path / "out"),
            headless=False,
            resume_from=1,
            chrome_path=None,
            context_file=str(context_file),
            questions_file=str(questions_file),
        ),
    )

    created = {}

    class FakeSession:
        def __init__(self, profile_dir, headless=False, browser_executable=""):
            created["session_init"] = {
                "profile_dir": profile_dir,
                "headless": headless,
                "browser_executable": browser_executable,
            }

        def ensure_browser_launched(self):
            return True

        def check_login_status(self):
            return True

        def wait_for_manual_login(self):
            return True

    class FakeAutomator:
        def __init__(self, **kwargs):
            created["automator_kwargs"] = kwargs

        def run_all_rounds(self, start_from=1):
            created["run_all_rounds"] = start_from
            out_dir = Path(created["automator_kwargs"]["output_dir"])
            out_dir.mkdir(parents=True, exist_ok=True)
            final_file = out_dir / "research_source.md"
            final_file.write_text("ok", encoding="utf-8")
            return out_dir, final_file

    monkeypatch.setattr(chatgpt_auto_research, "SessionManager", FakeSession)
    monkeypatch.setattr(chatgpt_auto_research, "ConversationAutomator", FakeAutomator)

    chatgpt_auto_research.main()

    kwargs = created["automator_kwargs"]
    assert kwargs["topic"] == "测试主题"
    assert kwargs["question_blocks"] == ["一、Q1", "二、Q2", "三、Q3", "四、Q4", "五、Q5", "六、Q6"]
    assert kwargs["context_text"] == "外部市场分析"
    assert created["run_all_rounds"] == 1
