"""
Jarvis Agent Pro - 命令行应用程序入口 (CLI Application Entrypoint)

提供 typer 驱动的交互式子命令：
- jarvis chat: 交互式终端 REPL 多轮会话
- jarvis run: 单次即时指令推演
- jarvis sessions: 查看历史检查点会话快照
- jarvis version: 查看系统版本
"""

import os
import sqlite3
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from cli import __version__
from cli.session import SessionRuntime
from cli.ui import print_banner, print_error, print_final_answer

app = typer.Typer(
    name="jarvis",
    help="Jarvis Agent Pro: 基于 LangGraph 的声明式智能体命令行系统",
    add_completion=False,
)
console = Console()


@app.command("chat")
def chat_command(
    thread_id: Annotated[
        str | None,
        typer.Option("--thread-id", "-t", help="指定恢复或新建的会话 ID"),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="指定大语言模型名称 (如 gpt-4o, deepseek-chat)"),
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option("--provider", "-p", help="模型提供商 (demo, openai, deepseek)"),
    ] = None,
    db: Annotated[
        str,
        typer.Option("--db", help="SQLite 检查点持久化数据库路径"),
    ] = ".jarvis_checkpoints.db",
    demo: Annotated[
        bool,
        typer.Option("--demo", help="使用内置离线 Demo 演示模型（无需任何 API Key）"),
    ] = False,
    mode: Annotated[
        str,
        typer.Option(
            "--mode",
            "-M",
            help="图编排拓扑模式: default (ReAct+HITL), hierarchical (多智能体分层子图), review (多维度代码并发审查)",
        ),
    ] = "default",
) -> None:
    """启动交互式多轮对话会话 (REPL 模式)。"""
    try:
        session = SessionRuntime(
            thread_id=thread_id,
            db_path=db,
            model_name=model,
            provider=provider,
            demo=demo,
            mode=mode,
        )
    except Exception as exc:
        print_error(f"初始化运行时失败: {exc!s}")
        raise typer.Exit(code=1) from exc

    print_banner(
        thread_id=session.thread_id,
        model_name=session.model_label,
        db_path=session.db_path,
        mode=session.mode_label,
    )

    while True:
        try:
            user_input = console.input("[bold cyan]Jarvis ❯ [/bold cyan]").strip()
            if not user_input:
                continue

            if user_input.lower() in ("exit", "quit", "q"):
                console.print("\n[dim]👋 感谢使用 Jarvis Agent Pro，会话已保存。再见！[/dim]")
                break

            answer = session.execute_turn(user_input=user_input, verbose=True)
            print_final_answer(answer)

        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]接收到退出信号，会话已保存。再见！[/dim]")
            break
        except Exception as exc:
            print_error(f"执行出错: {exc!s}")


@app.command("run")
def run_command(
    prompt: Annotated[str, typer.Argument(help="待执行的任务自然语言指令")],
    thread_id: Annotated[
        str | None,
        typer.Option("--thread-id", "-t", help="指定会话 ID"),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="指定模型名称"),
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option("--provider", "-p", help="模型提供商 (demo, openai, deepseek)"),
    ] = None,
    db: Annotated[
        str,
        typer.Option("--db", help="SQLite 检查点持久化数据库路径"),
    ] = ".jarvis_checkpoints.db",
    demo: Annotated[
        bool,
        typer.Option("--demo", help="使用内置离线 Demo 演示模型"),
    ] = False,
    mode: Annotated[
        str,
        typer.Option(
            "--mode",
            "-M",
            help="图编排拓扑模式: default (ReAct+HITL), hierarchical (多智能体分层子图), review (多维度代码并发审查)",
        ),
    ] = "default",
    quiet: Annotated[
        bool,
        typer.Option("--quiet", "-q", help="安静模式：只打印最终结论，不打印中间思考与工具卡片"),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="非交互式自动核准所有高危敏感工具调用"),
    ] = False,
) -> None:
    """执行单次任务指令并退出。"""
    try:
        session = SessionRuntime(
            thread_id=thread_id,
            db_path=db,
            model_name=model,
            provider=provider,
            demo=demo,
            mode=mode,
        )
        answer = session.execute_turn(
            user_input=prompt,
            auto_approve=yes,
            verbose=not quiet,
        )
        print_final_answer(answer)
    except Exception as exc:
        print_error(f"任务执行失败: {exc!s}")
        raise typer.Exit(code=1) from exc


@app.command("supervise")
def supervise_command(
    goal: Annotated[str, typer.Argument(help="待多智能体协作完成的任务目标")],
    thread_id: Annotated[
        str | None,
        typer.Option("--thread-id", "-t", help="指定会话 ID"),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="指定模型名称"),
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option("--provider", "-p", help="模型提供商 (demo, openai, deepseek)"),
    ] = None,
    db: Annotated[
        str,
        typer.Option("--db", help="SQLite 检查点持久化数据库路径"),
    ] = ".jarvis_checkpoints.db",
    demo: Annotated[
        bool,
        typer.Option("--demo", help="使用内置离线 Demo 演示模型"),
    ] = False,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", "-q", help="安静模式：只打印最终综合成果"),
    ] = False,
) -> None:
    """[Phase 9] 启动分层多智能体协同 (Supervisor + Researcher + Coder)。"""
    try:
        session = SessionRuntime(
            thread_id=thread_id,
            db_path=db,
            model_name=model,
            provider=provider,
            demo=demo,
            mode="hierarchical",
        )
        answer = session.execute_turn(
            user_input=goal,
            verbose=not quiet,
        )
        print_final_answer(answer)
    except Exception as exc:
        print_error(f"多智能体协同任务执行失败: {exc!s}")
        raise typer.Exit(code=1) from exc


@app.command("review")
def review_command(
    target: Annotated[
        str,
        typer.Argument(help="待审查的代码内容或 Python 文件路径"),
    ],
    thread_id: Annotated[
        str | None,
        typer.Option("--thread-id", "-t", help="指定会话 ID"),
    ] = None,
    db: Annotated[
        str,
        typer.Option("--db", help="SQLite 检查点持久化数据库路径"),
    ] = ".jarvis_checkpoints.db",
    quiet: Annotated[
        bool,
        typer.Option("--quiet", "-q", help="安静模式：只打印最终审查决议"),
    ] = False,
) -> None:
    """[Phase 10] 启动代码多维度并发审查 (安全 + 性能 + 风格并发分析与汇聚)。"""
    try:
        code_content = target
        if os.path.isfile(target):
            with open(target, encoding="utf-8") as f:
                code_content = f.read()

        session = SessionRuntime(
            thread_id=thread_id,
            db_path=db,
            mode="review",
        )
        answer = session.execute_turn(
            user_input="执行多维度代码并发质量审查",
            verbose=not quiet,
            target_code=code_content,
        )
        print_final_answer(answer)
    except Exception as exc:
        print_error(f"代码并发审查任务执行失败: {exc!s}")
        raise typer.Exit(code=1) from exc


@app.command("sessions")
def sessions_command(
    db: Annotated[
        str,
        typer.Option("--db", help="SQLite 检查点持久化数据库路径"),
    ] = ".jarvis_checkpoints.db",
) -> None:
    """查看保存在 SQLite 中的所有历史会话与检查点。"""
    if not os.path.exists(db):
        console.print(f"[yellow]提示: 数据库文件 '{db}' 尚不存在，暂无历史会话。[/yellow]")
        return

    try:
        conn = sqlite3.connect(db)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT thread_id, checkpoint_id, COUNT(*) as step_count
            FROM checkpoints
            GROUP BY thread_id
            ORDER BY rowid DESC
            """
        )
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            console.print("[yellow]当前数据库中暂无会话快照。[/yellow]")
            return

        table = Table(title=f"Jarvis Agent Pro - 历史会话清单 ({db})")
        table.add_column("Thread ID (会话)", style="cyan", no_wrap=True)
        table.add_column("最新 Checkpoint ID", style="magenta")
        table.add_column("快照总数", justify="right", style="green")

        for row in rows:
            table.add_row(str(row[0]), str(row[1]), str(row[2]))

        console.print(table)
    except Exception as exc:
        print_error(f"读取数据库失败: {exc!s}")


@app.command("version")
def version_command() -> None:
    """显示 Jarvis Agent Pro 版本号。"""
    console.print(
        f"[bold cyan]Jarvis Agent Pro[/bold cyan] version [bold green]{__version__}[/bold green]"
    )


def main() -> None:
    """CLI 入口主函数。"""
    app()


if __name__ == "__main__":
    main()
