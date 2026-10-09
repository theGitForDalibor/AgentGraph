"""
Phase 4 测试: 验证节点 (Nodes) 纯函数契约、Planner 决策、Tool 执行与异常隔离边界
"""

from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from nodes.base import with_error_boundary
from nodes.planner import create_planner_node
from nodes.tool_executor import create_tool_node
from state.agent_state import AgentState


@pytest.fixture
def base_state() -> AgentState:
    """提供标准的只读初始状态快照"""
    return {
        "messages": [HumanMessage(content="计算 10 + 20 并总结")],
        "task_goal": "执行数学运算",
        "plan": None,
        "pending_action": None,
        "approval_status": None,
        "scratchpad": [],
        "branch_results": {},
        "metadata": {},
    }


def test_planner_node_direct_answer(base_state: AgentState) -> None:
    """验证 Planner 生成最终普通文本答复行为"""
    mock_model = MagicMock()
    mock_model.invoke.return_value = AIMessage(content="运算结果为 30。")

    planner = create_planner_node(model=mock_model)
    delta = planner(base_state)

    assert "messages" in delta
    assert len(delta["messages"]) == 1
    assert isinstance(delta["messages"][0], AIMessage)
    assert delta["messages"][0].content == "运算结果为 30。"
    assert "Planner 决策: 生成最终答复" in delta["scratchpad"][0]

    # 验证纯函数约束：入参 state 未被污染修改
    assert len(base_state["messages"]) == 1
    assert len(base_state["scratchpad"]) == 0


def test_planner_node_tool_calling(base_state: AgentState) -> None:
    """验证 Planner 生成结构化工具调用指令行为"""
    mock_model = MagicMock()
    tool_call_item = {
        "name": "calculate",
        "args": {"expression": "10 + 20"},
        "id": "call_calc_001",
        "type": "tool_call",
    }
    mock_model.invoke.return_value = AIMessage(content="", tool_calls=[tool_call_item])

    planner = create_planner_node(model=mock_model)
    delta = planner(base_state)

    assert len(delta["messages"]) == 1
    ai_msg = delta["messages"][0]
    assert isinstance(ai_msg, AIMessage)
    assert len(ai_msg.tool_calls) == 1
    assert ai_msg.tool_calls[0]["name"] == "calculate"
    assert "生成 1 个工具调用" in delta["scratchpad"][0]


def test_planner_system_prompt_injection(base_state: AgentState) -> None:
    """验证 Planner 自动注入 SystemMessage 提示词"""
    mock_model = MagicMock()
    mock_model.invoke.return_value = AIMessage(content="收到指令")

    planner = create_planner_node(model=mock_model, system_prompt="你是由 DeepMind 设计的 Jarvis")
    planner(base_state)

    call_args = mock_model.invoke.call_args[0][0]
    assert len(call_args) == 2
    assert isinstance(call_args[0], SystemMessage)
    assert "Jarvis" in call_args[0].content


def test_tool_executor_node_success() -> None:
    """验证 Tool Executor 成功调度本地注册工具并产出 ToolMessage"""

    def add(a: int, b: int) -> int:
        return a + b

    def echo(text: str) -> str:
        return f"Echo: {text}"

    tool_node = create_tool_node(tools={"add": add, "echo": echo})

    ai_msg = AIMessage(
        content="",
        tool_calls=[
            {"name": "add", "args": {"a": 15, "b": 25}, "id": "call_01"},
            {"name": "echo", "args": {"text": "hello"}, "id": "call_02"},
        ],
    )
    state: AgentState = {
        "messages": [ai_msg],
        "task_goal": "",
        "plan": None,
        "pending_action": None,
        "approval_status": None,
        "scratchpad": [],
        "branch_results": {},
        "metadata": {},
    }

    delta = tool_node(state)
    assert "messages" in delta
    assert len(delta["messages"]) == 2

    tool_res1 = delta["messages"][0]
    assert isinstance(tool_res1, ToolMessage)
    assert tool_res1.content == "40"
    assert tool_res1.tool_call_id == "call_01"

    tool_res2 = delta["messages"][1]
    assert isinstance(tool_res2, ToolMessage)
    assert tool_res2.content == "Echo: hello"
    assert tool_res2.tool_call_id == "call_02"


def test_tool_executor_node_unknown_tool_and_error_handling() -> None:
    """验证 Tool Executor 遇到未知工具与工具运行期异常时的安全兜底"""

    def broken_tool() -> None:
        raise ValueError("磁盘配额耗尽")

    tool_node = create_tool_node(tools={"broken": broken_tool})

    ai_msg = AIMessage(
        content="",
        tool_calls=[
            {"name": "non_exist_tool", "args": {}, "id": "call_err_1"},
            {"name": "broken", "args": {}, "id": "call_err_2"},
        ],
    )
    state: AgentState = {
        "messages": [ai_msg],
        "task_goal": "",
        "plan": None,
        "pending_action": None,
        "approval_status": None,
        "scratchpad": [],
        "branch_results": {},
        "metadata": {},
    }

    delta = tool_node(state)
    assert len(delta["messages"]) == 2
    assert "未注册工具" in delta["messages"][0].content
    assert "执行失败: 磁盘配额耗尽" in delta["messages"][1].content


def test_tool_executor_no_tool_calls_safe_return() -> None:
    """验证当最新消息不包含 tool_calls 时工具节点静默返回空增量"""
    tool_node = create_tool_node(tools={})
    state: AgentState = {
        "messages": [HumanMessage(content="普通问题")],
        "task_goal": "",
        "plan": None,
        "pending_action": None,
        "approval_status": None,
        "scratchpad": [],
        "branch_results": {},
        "metadata": {},
    }
    delta = tool_node(state)
    assert delta == {}


def test_error_boundary_isolates_unhandled_exception() -> None:
    """验证异常边界装饰器成功捕获崩溃并转化为状态增量"""

    @with_error_boundary("faulty_node")
    def faulty_node(state: AgentState) -> dict[str, Any]:
        raise RuntimeError("网络超时断连")

    state: AgentState = {
        "messages": [],
        "task_goal": "",
        "plan": None,
        "pending_action": None,
        "approval_status": None,
        "scratchpad": [],
        "branch_results": {},
        "metadata": {},
    }

    delta = faulty_node(state)
    assert len(delta["messages"]) == 1
    assert "节点 [faulty_node] 执行异常: 网络超时断连" in delta["messages"][0].content
    assert delta["metadata"]["failed_node"] == "faulty_node"


def test_tool_executor_adaptive_arg_dispatch() -> None:
    """验证 Tool Executor 参数自适应调度（无参容错、参数过滤与单参数位置回退）"""

    def no_param_tool() -> str:
        return "system_ready"

    def strict_param_tool(filename: str) -> str:
        return f"read:{filename}"

    def single_arg_tool(value: int) -> int:
        return value * 2

    tool_node = create_tool_node(
        tools={
            "no_param": no_param_tool,
            "strict_param": strict_param_tool,
            "single_arg": single_arg_tool,
        }
    )

    ai_msg = AIMessage(
        content="",
        tool_calls=[
            # 1. 无参工具，但模型幻觉附带多余参数
            {"name": "no_param", "args": {"dummy": "extra"}, "id": "c1"},
            # 2. 严格参数工具，模型附带非法参数
            {
                "name": "strict_param",
                "args": {"filename": "data.csv", "format": "table"},
                "id": "c2",
            },
            # 3. 单参数工具，键名与形参不一致
            {"name": "single_arg", "args": {"target_num": 21}, "id": "c3"},
        ],
    )
    state: AgentState = {
        "messages": [ai_msg],
        "task_goal": "",
        "plan": None,
        "pending_action": None,
        "approval_status": None,
        "scratchpad": [],
        "branch_results": {},
        "metadata": {},
    }

    delta = tool_node(state)
    assert len(delta["messages"]) == 3
    assert delta["messages"][0].content == "system_ready"
    assert delta["messages"][1].content == "read:data.csv"
    assert delta["messages"][2].content == "42"
