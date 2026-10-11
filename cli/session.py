"""
Jarvis Agent Pro - 终端会话运行时与状态图装配 (Session Runtime)

负责组装完整的 HITL 状态图、挂载持久化检查点存储、管理 thread_id，
并提供多轮对话步进与执行链路观察。
"""

import uuid
from collections.abc import Callable
from typing import Any

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig

from checkpoints.manager import create_sqlite_saver
from cli.hitl_handler import resolve_graph_interrupts
from cli.llm_factory import DemoModel, get_model
from cli.tools import CLI_SENSITIVE_TOOLS, CLI_TOOLS
from cli.ui import (
    print_thought,
    print_tool_call,
    print_tool_observation,
)
from graph.hitl_graph import build_hitl_agent_graph
from graph.parallel_graph import build_code_review_parallel_graph
from graph.parent_graph import build_hierarchical_parent_graph
from graph.subgraphs.coder import build_coder_subgraph
from graph.subgraphs.researcher import build_researcher_subgraph
from nodes.planner import create_planner_node
from nodes.tool_executor import create_tool_node


class SessionRuntime:
    """会话级图执行运行时管理器。"""

    def __init__(
        self,
        thread_id: str | None = None,
        db_path: str = ".jarvis_checkpoints.db",
        model_name: str | None = None,
        provider: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        demo: bool = False,
        system_prompt: str | None = None,
        custom_tools: dict[str, Callable[..., str]] | None = None,
        mode: str = "default",
    ) -> None:
        self.thread_id = thread_id or f"session_{uuid.uuid4().hex[:8]}"
        self.db_path = db_path
        self.mode = mode.lower().strip()
        self.config: RunnableConfig = {"configurable": {"thread_id": self.thread_id}}

        # 1. 组装模型
        self.model, self.model_label = get_model(
            provider=provider,
            model_name=model_name,
            api_key=api_key,
            base_url=base_url,
            demo=demo,
        )

        # 2. 组装检查点持久化存储
        self.checkpointer = create_sqlite_saver(db_path=self.db_path)

        # 3. 根据编排模式组装对应的图引擎
        if self.mode in ("hierarchical", "subgraph", "multi-agent"):
            sub_model = None if isinstance(self.model, DemoModel) else self.model
            self.app = build_hierarchical_parent_graph(
                researcher_subgraph=build_researcher_subgraph(model=sub_model),
                coder_subgraph=build_coder_subgraph(model=sub_model),
                checkpointer=self.checkpointer,
            )
            self.mode_label = "Hierarchical Multi-Agent (Phase 9)"
        elif self.mode in ("review", "parallel", "code-review"):
            self.app = build_code_review_parallel_graph(checkpointer=self.checkpointer)
            self.mode_label = "Parallel Code Review (Phase 10)"
        else:
            # 默认单智能体 ReAct + HITL
            sys_prompt = system_prompt or "你是由 Google DeepMind 理念设计的自主智能体助理 Jarvis。"
            self.planner_node = create_planner_node(model=self.model, system_prompt=sys_prompt)
            active_tools = custom_tools or CLI_TOOLS
            self.tool_node = create_tool_node(tools=active_tools)
            self.app = build_hitl_agent_graph(
                planner_node=self.planner_node,
                tool_node=self.tool_node,
                sensitive_tools=list(CLI_SENSITIVE_TOOLS),
                checkpointer=self.checkpointer,
            )
            self.mode_label = "ReAct + HITL (Phase 7-8)"

    def execute_turn(
        self,
        user_input: str,
        auto_approve: bool = False,
        verbose: bool = True,
        target_code: str | None = None,
    ) -> str:
        """
        执行一轮完整的人机交互对话周期。

        Args:
            user_input: 用户本轮输入的自然语言指令
            auto_approve: 是否自动批准高危工具中断
            verbose: 是否在终端实时打印思考与工具调用卡片
            target_code: 针对代码审查模式可选注入的目标代码

        Returns:
            str: 最终智能体给出的自然语言回答
        """
        # 读取当前会话的历史状态消息数量与草稿日志
        current_state = self.app.get_state(self.config)
        old_messages = current_state.values.get("messages", []) if current_state.values else []
        old_count = len(old_messages)
        old_scratchpad = current_state.values.get("scratchpad", []) if current_state.values else []
        old_scratchpad_len = len(old_scratchpad)

        # 构造输入载荷
        metadata: dict[str, Any] = {}
        if current_state.values:
            metadata = dict(current_state.values.get("metadata", {}))
        if target_code or self.mode in ("review", "parallel", "code-review"):
            metadata["target_code"] = target_code or user_input

        turn_input: dict[str, Any]
        if not current_state.values:
            turn_input = {
                "messages": [HumanMessage(content=user_input)],
                "task_goal": user_input,
                "plan": None,
                "pending_action": None,
                "approval_status": None,
                "scratchpad": [],
                "branch_results": {},
                "metadata": metadata,
            }
        else:
            turn_input = {
                "messages": [HumanMessage(content=user_input)],
                "task_goal": user_input,
                "metadata": metadata,
            }

        # 启动图推演
        raw_result = self.app.invoke(turn_input, config=self.config)

        # 解决人机协同中断挂起
        final_result = resolve_graph_interrupts(
            app=self.app,
            result=raw_result,
            config=self.config,
            auto_approve=auto_approve,
        )

        # 在多智能体协同或并发分支模式下，输出 scratchpad 过程调度轨迹
        if verbose and self.mode in (
            "hierarchical",
            "subgraph",
            "multi-agent",
            "review",
            "parallel",
            "code-review",
        ):
            new_scratchpad = final_result.get("scratchpad", [])[old_scratchpad_len:]
            for note in new_scratchpad:
                print_thought(str(note))

        # 解析本轮新增的消息序列，并在控制台高亮回显步骤
        all_messages = final_result.get("messages", [])
        new_messages = all_messages[old_count:]
        final_answer = ""

        for msg in new_messages:
            if isinstance(msg, AIMessage):
                tool_calls = getattr(msg, "tool_calls", None)
                if tool_calls and verbose:
                    if msg.content:
                        print_thought(str(msg.content))
                    for tc in tool_calls:
                        print_tool_call(tc.get("name", ""), tc.get("args", {}))
                else:
                    final_answer = str(msg.content)
            elif isinstance(msg, ToolMessage) and verbose:
                print_tool_observation(getattr(msg, "name", "tool"), str(msg.content))

        if not final_answer and all_messages:
            final_answer = str(all_messages[-1].content)

        return final_answer
