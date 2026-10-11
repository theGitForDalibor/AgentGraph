"""
Jarvis Agent Pro - 终端高保真渲染器 (Terminal UI Renderer)

基于 rich 库构建美观、高对比度的交互式终端视觉呈现组件，
包括欢迎横幅、思考气泡、工具调度卡片、Markdown 回显以及 HITL 人工审批交互框。
适配 Windows 控制台编码环境。
"""

import contextlib
import json
import sys
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Windows 终端编码健壮性保障
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        with contextlib.suppress(Exception):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        with contextlib.suppress(Exception):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")

console = Console()


def print_banner(
    thread_id: str,
    model_name: str,
    db_path: str,
    mode: str = "default",
) -> None:
    """打印 CLI 启动欢迎横幅与运行时元数据信息。"""
    banner_text = Text()
    banner_text.append("[*] Jarvis Agent Pro (LangGraph CLI)\n", style="bold cyan")
    banner_text.append("声明式状态图驱动的企业级自主智能体参考实现\n\n", style="dim italic")
    banner_text.append(f"  * 会话 ID (thread_id): {thread_id}\n", style="bold green")
    banner_text.append(f"  * 编排拓扑 (topology):  {mode}\n", style="bold cyan")
    banner_text.append(f"  * 推理模型 (model):     {model_name}\n", style="bold yellow")
    banner_text.append(f"  * 状态持久化 (sqlite):   {db_path}\n", style="bold magenta")
    banner_text.append("  * 退出指令: 输入 'exit'、'quit' 或按 Ctrl+C\n", style="dim")

    console.print(Panel(banner_text, border_style="cyan", padding=(1, 2)))


def print_user(query: str) -> None:
    """打印用户输入提示。"""
    console.print()
    console.print(f"[bold cyan]User[/bold cyan]: {query}")


def print_thought(content: str) -> None:
    """打印智能体内部思考与规划意图。"""
    if not content:
        return
    text = Text(content.strip(), style="dim cyan")
    console.print(
        Panel(text, title="[bold cyan]Agent Thought[/bold cyan]", border_style="dim cyan")
    )


def print_tool_call(tool_name: str, args: dict[str, Any]) -> None:
    """打印工具调用触发卡片。"""
    args_json = json.dumps(args, ensure_ascii=False, indent=2)
    text = Text()
    text.append(f"工具: {tool_name}\n", style="bold yellow")
    text.append(f"参数:\n{args_json}", style="dim")
    console.print(Panel(text, title="[bold yellow]Tool Call[/bold yellow]", border_style="yellow"))


def print_tool_observation(tool_name: str, observation: str) -> None:
    """打印工具执行观察回显。"""
    preview = observation.strip()
    if len(preview) > 500:
        preview = preview[:500] + "... (已截断)"
    text = Text(preview, style="green")
    console.print(
        Panel(
            text, title=f"[bold green]Observation ({tool_name})[/bold green]", border_style="green"
        )
    )


def print_final_answer(content: str) -> None:
    """使用标准 Markdown 渲染最终模型输出。"""
    console.print()
    md = Markdown(content)
    console.print(
        Panel(md, title="[bold blue]Jarvis Answer[/bold blue]", border_style="blue", padding=(1, 2))
    )
    console.print()


def print_error(message: str) -> None:
    """打印错误告警面板。"""
    console.print(
        Panel(
            Text(message, style="bold red"), title="[bold red]Error[/bold red]", border_style="red"
        )
    )


def prompt_hitl_approval(task_goal: str, sensitive_calls: list[dict[str, Any]]) -> tuple[bool, str]:
    """
    终端人机协同 (HITL) 交互审批提示。

    在控制台输出醒目的高危警告面板并阻塞等待用户输入，返回核准布尔值与原因。
    """
    warning_text = Text()
    warning_text.append(
        "检测到即将执行敏感/高危工具操作，已触发执行拦截 (Graph Interrupt)！\n\n", style="bold red"
    )
    warning_text.append(f"当前任务目标: {task_goal or '无目标说明'}\n\n", style="bold yellow")
    warning_text.append("待核准的敏感操作项:\n", style="bold underline")

    for idx, call in enumerate(sensitive_calls, 1):
        name = call.get("name", "unknown")
        args_str = json.dumps(call.get("args", {}), ensure_ascii=False)
        warning_text.append(f"  {idx}. 工具: {name} | 参数: {args_str}\n", style="bold white")

    console.print()
    console.print(
        Panel(
            warning_text,
            title="[bold red]Human Approval Required[/bold red]",
            border_style="red",
            padding=(1, 2),
        )
    )

    try:
        user_choice = console.input(
            "[bold red]是否核准执行上述敏感操作？[y:核准 / n:驳回 / 直接输入反馈理由]: [/bold red]"
        ).strip()
    except (EOFError, KeyboardInterrupt):
        return False, "用户中断终端输入"

    if user_choice.lower() in ("y", "yes"):
        console.print("[bold green][v] 操作已核准放行。[/bold green]")
        return True, "用户终端手动核准"
    elif user_choice.lower() in ("n", "no", ""):
        console.print("[bold red][x] 操作已驳回。[/bold red]")
        return False, "用户终端手动驳回"
    else:
        console.print(f"[bold yellow][x] 操作已驳回，反馈信息: {user_choice}[/bold yellow]")
        return False, user_choice


def print_sessions_table(sessions: list[dict[str, Any]]) -> None:
    """打印历史会话列表。"""
    table = Table(title="Jarvis Agent Pro - 历史会话快照")
    table.add_column("Thread ID", style="cyan", no_wrap=True)
    table.add_column("Checkpoint ID", style="magenta")
    table.add_column("Last Updated Step", style="green")
    table.add_column("Messages Count", justify="right")

    for s in sessions:
        table.add_row(
            str(s.get("thread_id", "")),
            str(s.get("checkpoint_id", "")),
            str(s.get("step", "")),
            str(s.get("messages_count", 0)),
        )

    console.print(table)
