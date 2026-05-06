from __future__ import annotations

from pathlib import Path

from rich.console import Console

from agent_factory.application import CreateAgentRequest, CreateAgentService
from agent_factory.cli.rendering import FactoryStreamRenderer, render_banner, render_create_result


def run_shell() -> None:
    console = Console()
    service = CreateAgentService()
    render_banner(console, workspace=Path.cwd(), state="shell")
    console.print("输入需求后直接回车。输入 /exit 退出。")
    while True:
        try:
            line = input("agentfactory> ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("")
            break
        if not line:
            continue
        if line in {"/exit", "exit", "quit"}:
            break
        if line.startswith("/create-agent "):
            prompt = line[len("/create-agent ") :].strip()
        else:
            prompt = line
        request = CreateAgentRequest(prompt=prompt)
        renderer = FactoryStreamRenderer(console)
        events = list(service.stream_create_agent(request))
        for event in events:
            renderer.render(event)
        renderer.close()
        result = service.create_agent(request)
        render_create_result(result, console)
