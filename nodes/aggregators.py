"""
Jarvis Agent Pro - 并行汇聚节点 (Aggregator Nodes)

负责在扇入 (Fan-in) 阶段汇总所有并行分支通过 merge_dict_reducer 与 append_reducer
写入的计算成果，提炼综合评估报告，或进行加权汇总与下一步决策。
"""

from collections.abc import Callable
from typing import Any

from langchain_core.messages import AIMessage

from nodes.base import NodeFunction, with_error_boundary
from state.agent_state import AgentState


def default_report_formatter(branch_results: dict[str, Any]) -> str:
    """默认并行结果格式化器"""
    if not branch_results:
        return "未收集到任何并行分支结果。"

    lines = ["【多分支并发执行成果汇总】"]
    for key, val in sorted(branch_results.items()):
        lines.append(f"- **{key}**: {val}")
    return "\n".join(lines)


def create_summary_aggregator_node(
    title: str = "并行分支汇聚报告",
    custom_formatter: Callable[[dict[str, Any]], str] | None = None,
) -> NodeFunction:
    """
    创建通用综合汇聚节点纯函数 (Summary Aggregator)

    Args:
        title: 汇聚报告标题
        custom_formatter: 自定义分支结果文本格式化器

    Returns:
        NodeFunction: 遵循图节点契约的汇聚函数
    """
    formatter = custom_formatter or default_report_formatter

    @with_error_boundary("summary_aggregator")
    def summary_aggregator_node(state: AgentState) -> dict[str, Any]:
        results = state.get("branch_results", {})
        task = state.get("task_goal", "未指定任务")

        formatted_body = formatter(results)
        final_message_content = f"### {title}\n目标: {task}\n\n{formatted_body}"

        branch_count = len(results)
        return {
            "messages": [AIMessage(content=final_message_content)],
            "scratchpad": [f"Aggregator 汇聚完成: 已成功合并 {branch_count} 个并发分支成果"],
        }

    return summary_aggregator_node


def create_dict_aggregator_node(
    target_key: str,
    reducer_func: Callable[[dict[str, Any]], Any],
) -> NodeFunction:
    """
    创建结构化字典汇聚节点 (Dict Aggregator)

    执行用户自定义的聚合计算 (如得分求和、加权平均、投票裁决)，
    并将聚合结果写回 branch_results 的指定目标键中。

    Args:
        target_key: 汇聚产物在 branch_results 中的键名
        reducer_func: 自定义计算函数，接收当前全部 branch_results 返回聚合值

    Returns:
        NodeFunction: 遵循图节点契约的汇聚函数
    """

    @with_error_boundary("dict_aggregator")
    def dict_aggregator_node(state: AgentState) -> dict[str, Any]:
        current_results = state.get("branch_results", {})
        aggregated_val = reducer_func(current_results)
        return {
            "branch_results": {target_key: aggregated_val},
            "scratchpad": [f"DictAggregator 计算就绪: [{target_key}] = {aggregated_val}"],
        }

    return dict_aggregator_node
