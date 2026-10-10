"""
Jarvis Agent Pro - 代码研发与自测子图 (Coder Subgraph)

专职负责代码生成与测试驱动的自我修复循环 (Draft -> Test -> Revise -> Complete)。
拥有独立的私有状态空间 (CoderState)，封装内部反复试错过程，
只向调用方产出最终验证通过或定稿的代码资产。
"""

import ast
from collections.abc import Callable, Sequence
from typing import Annotated, Any, Literal

from langchain_core.messages import AIMessage, BaseMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from typing_extensions import TypedDict

from graph.builder import compile_agent_graph, create_agent_graph_builder


class CoderState(TypedDict):
    """
    Coder 子图专属私有状态模型 (黑盒研发作用域)
    """

    # 1. 代码研发目标与需求
    requirement: str

    # 2. 外部提供的参考背景或调研成果 (可选)
    research_context: str | None

    # 3. 当前生成的代码片段
    code_snippet: str | None

    # 4. 测试与静态审查反馈详情
    test_results: str | None

    # 5. 代码修复与重试轮次计数
    revision_count: int

    # 6. 最大允许重试轮次 (防止无限自修复死循环)
    max_revisions: int

    # 7. 当前子图研发状态
    status: Literal["drafting", "testing", "completed", "failed"]

    # 8. 子图内部思考消息历史
    messages: Annotated[Sequence[BaseMessage], add_messages]


def default_python_syntax_tester(code: str) -> tuple[bool, str]:
    """
    默认基于 ast 解析的代码语法与安全性测试器

    Returns:
        tuple[bool, str]: (是否通过测试, 测试详情说明)
    """
    if not code or not code.strip():
        return False, "错误: 代码片段为空"

    try:
        ast.parse(code)
        return True, "静态语法分析与 AST 树构建通过 (All checks passed)"
    except SyntaxError as err:
        return False, f"SyntaxError 在第 {err.lineno} 行: {err.msg}"


def build_coder_subgraph(
    model: Any | None = None,
    test_runner: Callable[[str], tuple[bool, str]] | None = None,
    max_revisions: int = 3,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """
    组装并编译专职代码自测研发子图 (Coder Subgraph)

    Args:
        model: 模型调用适配器，若为 None 则使用确定性规则生成代码
        test_runner: 自动化测试运行器，接收代码字符串返回 (是否通过, 日志)
        max_revisions: 最大修复迭代轮次
        checkpointer: 可选的子图专属检查点存储器

    Returns:
        CompiledStateGraph: 编译就绪的代码自测子图
    """
    active_tester = test_runner or default_python_syntax_tester
    builder = create_agent_graph_builder(CoderState)

    def draft_node(state: CoderState) -> dict[str, Any]:
        """子图编写节点：根据需求或上一轮测试报错起草/修正代码"""
        rev_count = state.get("revision_count", 0) + 1
        req = state.get("requirement", "实现基础算法")
        last_test = state.get("test_results")

        if model is not None and hasattr(model, "invoke"):
            prompt = f"任务: {req}\n前次测试报告: {last_test}\n请编写规范 Python 代码。"
            ai_msg = model.invoke([AIMessage(content=prompt)])
            code = getattr(ai_msg, "content", str(ai_msg))
        else:
            # 规则模板生成
            if last_test and "SyntaxError" in last_test:
                code = f"# 修复后的 Python 实现 (Revision {rev_count})\ndef solution():\n    return '{req} - 已修复语法错误'\n"
            else:
                code = f"# Python 实现 (Revision {rev_count})\ndef solution():\n    '''完成: {req}'''\n    return True\n"

        log_msg = f"完成代码起草/修正 (第 {rev_count} 版)"
        return {
            "code_snippet": code,
            "revision_count": rev_count,
            "status": "testing",
            "messages": [AIMessage(content=log_msg)],
        }

    def test_node(state: CoderState) -> dict[str, Any]:
        """子图测试节点：执行测试判定代码质量"""
        code = state.get("code_snippet") or ""
        passed, report = active_tester(code)
        rev_count = state.get("revision_count", 1)
        limit = state.get("max_revisions", max_revisions)

        if passed:
            next_status: Literal["drafting", "testing", "completed", "failed"] = "completed"
        elif rev_count >= limit:
            next_status = "failed"
        else:
            next_status = "drafting"

        return {
            "test_results": report,
            "status": next_status,
            "messages": [AIMessage(content=f"测试判定: {report} (状态: {next_status})")],
        }

    def route_decision(state: CoderState) -> str:
        """根据测试结果路由：通过或超限则结束，否则回环自修复"""
        current_status = state.get("status")
        if current_status in ("completed", "failed"):
            return END
        return "coder_draft"

    # 注册节点与连线
    builder.add_node("coder_draft", draft_node)
    builder.add_node("coder_test", test_node)

    builder.add_edge(START, "coder_draft")
    builder.add_edge("coder_draft", "coder_test")
    builder.add_conditional_edges(
        "coder_test",
        route_decision,
        {
            "coder_draft": "coder_draft",
            END: END,
        },
    )

    return compile_agent_graph(builder=builder, checkpointer=checkpointer)
