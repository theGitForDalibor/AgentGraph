"""
CLI 测试套件: 验证命令行交互、子命令、HITL 人机审批闭环与模型适配
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from typer.testing import CliRunner

from cli import __version__
from cli.app import app
from cli.llm_factory import DemoModel, OpenAICompatibleModel
from cli.session import SessionRuntime
from cli.tools import calculator, danger_delete_file, get_system_info, read_file

runner = CliRunner()


def test_cli_version() -> None:
    """验证 jarvis version 输出正确版本号"""
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_cli_help() -> None:
    """验证 jarvis --help 列出全部子命令"""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "chat" in result.stdout
    assert "run" in result.stdout
    assert "sessions" in result.stdout


def test_cli_chat_command_exit() -> None:
    """验证 jarvis chat 交互式 REPL 正常启动并退出"""
    result = runner.invoke(app, ["chat", "--demo", "--db", ":memory:"], input="quit\n")
    assert result.exit_code == 0
    assert "感谢使用" in result.stdout


def test_cli_run_demo_calculation() -> None:
    """验证 jarvis run 计算任务的端到端执行与观察回显"""
    result = runner.invoke(app, ["run", "帮我计算 25 * 40", "--demo", "--db", ":memory:"])
    assert result.exit_code == 0
    assert "calculator" in result.stdout
    assert "1000" in result.stdout
    assert "顺利完成" in result.stdout


def test_cli_run_demo_quiet_mode() -> None:
    """验证 jarvis run --quiet 安静模式下抑制中间过程卡片"""
    result = runner.invoke(
        app, ["run", "帮我计算 25 * 40", "--demo", "--quiet", "--db", ":memory:"]
    )
    assert result.exit_code == 0
    assert "Jarvis Answer" in result.stdout
    assert "Tool Call" not in result.stdout


def test_cli_run_hitl_auto_approval() -> None:
    """验证 jarvis run --yes 自动核准敏感工具"""
    result = runner.invoke(app, ["run", "帮我删除 app.log", "--demo", "--yes", "--db", ":memory:"])
    assert result.exit_code == 0
    assert "danger_delete_file" in result.stdout
    assert "安全移至回收站" in result.stdout


def test_cli_run_hitl_manual_rejection() -> None:
    """验证在交互式审批中驳回敏感工具调用时，图正确感知并调整计划"""
    # 模拟终端输入 'n' 驳回
    result = runner.invoke(
        app,
        ["run", "帮我删除 app.log", "--demo", "--db", ":memory:"],
        input="n\n",
    )
    assert result.exit_code == 0
    assert "操作已驳回" in result.stdout
    assert "终止该计划" in result.stdout


def test_cli_sessions_list_empty_and_populated(tmp_path: Path) -> None:
    """验证 jarvis sessions 查看历史会话快照"""
    db_file = str(tmp_path / "test_sessions.db")

    # 1. 数据库未初始化
    result = runner.invoke(app, ["sessions", "--db", db_file])
    assert result.exit_code == 0
    assert "尚不存在" in result.stdout

    # 2. 执行一次任务生成检查点
    runner.invoke(app, ["run", "计算 2+3", "--demo", "--db", db_file, "--thread-id", "test-th-1"])

    # 3. 再次查询
    result2 = runner.invoke(app, ["sessions", "--db", db_file])
    assert result2.exit_code == 0
    assert "test-th-1" in result2.stdout


def test_cli_tools_basic() -> None:
    """验证内置 CLI 工具函数的基础功能与安全兜底"""
    assert calculator("10 + 20 * 2") == "50"
    assert "非法字符" in calculator("import os")

    sys_info = get_system_info()
    assert "OS:" in sys_info
    assert "Python:" in sys_info

    assert "已由" in danger_delete_file("dummy.txt") or "安全移至回收站" in danger_delete_file(
        "dummy.txt"
    )
    assert "错误: 文件未找到" in read_file("non_existent_file_xyz.txt")


def test_demo_model_fallback() -> None:
    """验证 DemoModel 对不同用户意图的分类响应"""
    model = DemoModel()
    greeting = model.invoke([HumanMessage(content="你好")])
    assert "Jarvis Demo" in greeting.content

    calc = model.invoke([HumanMessage(content="求 50 + 50")])
    assert calc.tool_calls and calc.tool_calls[0]["name"] == "calculator"


def test_openai_compatible_model_mock_response() -> None:
    """验证 OpenAICompatibleModel 正确打包与解析 API 响应"""
    fake_response = {
        "choices": [
            {
                "message": {
                    "content": "我已执行指令",
                    "tool_calls": [
                        {
                            "id": "call_123",
                            "type": "function",
                            "function": {
                                "name": "calculator",
                                "arguments": json.dumps({"expression": "100 / 5"}),
                            },
                        }
                    ],
                }
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.json.return_value = fake_response
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.Client.post", return_value=mock_resp):
        client = OpenAICompatibleModel(api_key="sk-fake", base_url="https://api.openai.com/v1")
        msg = client.invoke([SystemMessage(content="系统提示"), HumanMessage(content="测试计算")])

        assert isinstance(msg, AIMessage)
        assert msg.content == "我已执行指令"
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0]["name"] == "calculator"
        assert msg.tool_calls[0]["args"] == {"expression": "100 / 5"}


def test_session_runtime_multi_turn_persistence() -> None:
    """验证 SessionRuntime 在同一 thread_id 下保持多轮对话历史上下文"""
    session = SessionRuntime(
        thread_id="test-multi-turn",
        db_path=":memory:",
        demo=True,
    )

    ans1 = session.execute_turn("请帮我计算 10 + 20", verbose=False)
    assert "30" in ans1

    # 第二轮对话
    ans2 = session.execute_turn("再次计算 5 * 5", verbose=False)
    assert "25" in ans2

    # 验证状态图中的消息已持久化累加
    state = session.app.get_state(session.config)
    messages = state.values.get("messages", [])
    # 至少应有 2 轮问答和工具交互
    assert len(messages) >= 6


def test_cli_help_includes_supervise_and_review() -> None:
    """验证 jarvis --help 显示 supervise 与 review 新增子命令"""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "supervise" in result.stdout
    assert "review" in result.stdout


def test_cli_run_hierarchical_mode() -> None:
    """验证 jarvis run --mode hierarchical 调度分层多智能体"""
    result = runner.invoke(
        app,
        ["run", "开发快速排序算法", "--mode", "hierarchical", "--demo", "--db", ":memory:"],
    )
    assert result.exit_code == 0
    assert "Jarvis 多智能体协同交付报告" in result.stdout
    assert "开发快速排序算法" in result.stdout
    assert "solution()" in result.stdout


def test_cli_run_review_mode() -> None:
    """验证 jarvis run --mode review 执行代码多维并发审查"""
    code_snippet = "def calculate(): return 42"
    result = runner.invoke(
        app,
        ["run", code_snippet, "--mode", "review", "--db", ":memory:"],
    )
    assert result.exit_code == 0
    assert "自动化多维度代码并行审查报告" in result.stdout
    assert "综合评估决议" in result.stdout


def test_cli_supervise_command_standalone() -> None:
    """验证专用子命令 jarvis supervise 正常启动并协同完成任务"""
    result = runner.invoke(
        app,
        ["supervise", "实现二叉树遍历", "--demo", "--db", ":memory:"],
    )
    assert result.exit_code == 0
    assert "Supervisor 主管分析" in result.stdout
    assert "Researcher 子图交付成果" in result.stdout
    assert "Coder 子图交付成果" in result.stdout
    assert "Jarvis 多智能体协同交付报告" in result.stdout


def test_cli_review_command_string_and_file(tmp_path: Path) -> None:
    """验证专用子命令 jarvis review 支持字符串与文件输入"""
    # 1. 直接传入代码字符串
    result1 = runner.invoke(
        app,
        ["review", "def unsafe(): eval('x')", "--db", ":memory:"],
    )
    assert result1.exit_code == 0
    assert "WARNING" in result1.stdout or "检出风险" in result1.stdout

    # 2. 传入本地代码文件
    test_code_file = tmp_path / "sample.py"
    test_code_file.write_text(
        '"""合规模块"""\ndef add(a: int, b: int) -> int:\n    return a + b\n', encoding="utf-8"
    )

    result2 = runner.invoke(
        app,
        ["review", str(test_code_file), "--db", ":memory:"],
    )
    assert result2.exit_code == 0
    assert "自动化多维度代码并行审查报告" in result2.stdout
    assert "审查通过 (APPROVED)" in result2.stdout
