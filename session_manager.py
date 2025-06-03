import subprocess
import shlex
import datetime
import sys
import os
import signal
from typing import List, Dict, Optional

import readchar
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

os.system('clear')

def get_tmux_dimensions():
    try:
        current_pane = subprocess.check_output(
            ['tmux', 'display-message', '-p', '#{pane_id}']
        ).decode().strip()

        panes = subprocess.check_output(
            ['tmux', 'list-panes', '-F', '#{pane_id} #{pane_width} #{pane_height}']
        ).decode().splitlines()

        for pane in panes:
            pid, width, height = pane.strip().split()
            if pid == current_pane:
                return int(width), int(height)
        raise Exception("Current pane not found")
    except Exception as e:
        print(f"Failed to get tmux pane size: {e}", file=sys.stderr)
        return None, None


class SessionManager:
    def __init__(self):
        width, height = get_tmux_dimensions()
        self.console = Console(width=width, height=height) if width and height else Console()
        signal.signal(signal.SIGINT, self.ignore_signal)
        signal.signal(signal.SIGTERM, self.ignore_signal)

    def ignore_signal(self, signum, frame):
        pass

    def list_tmux_sessions(self) -> List[Dict]:
        result = subprocess.check_output(
            ["tmux", "list-sessions", "-F", "#{session_name} #{session_created} #{?session_attached,yes,no}"],
            text=True,
        )
        sessions = []
        now = datetime.datetime.now()
        for line in result.strip().splitlines():
            parts = line.split()
            if len(parts) >= 3:
                name = parts[0]
                created_ts = int(parts[1])
                created = datetime.datetime.fromtimestamp(created_ts)
                attached = parts[2] == "yes"
                duration = now - created
                sessions.append({
                    "name": name,
                    "created": created,
                    "attached": attached,
                    "duration": duration
                })
        return sorted(sessions, key=lambda s: s["duration"], reverse=True)

    def get_session_details(self, session_name: str) -> Dict:
        windows = subprocess.check_output(
            ["tmux", "list-windows", "-t", session_name], text=True
        ).strip().splitlines()

        current_window = subprocess.check_output(
            ["tmux", "display-message", "-p", "-t", session_name, "#{window_index}:#{window_name}"],
            text=True,
        ).strip()

        real_ip_result = subprocess.check_output(
            ["tmux", "show-environment", "-t", session_name], text=True
        )
        real_ip = "N/A"
        for line in real_ip_result.strip().splitlines():
            if line.startswith("REAL_IP="):
                real_ip = line.split("=", 1)[1]
                break

        return {
            "windows": windows,
            "current_window": current_window,
            "real_ip": real_ip,
        }

    def escape_rich(self, text: str) -> str:
        return text.replace("[", "\\[").replace("]", "\\]")

    def render_sessions_table(self, sessions: List[Dict], selected_index: Optional[int] = None) -> None:
        width = self.console.width
        table = Table(title="Tmux Sessions", box=box.SIMPLE_HEAVY, expand=True, width=width)
        table.add_column("Index", justify="right", style="cyan", no_wrap=True)
        table.add_column("Name", style="magenta")
        table.add_column("Created", justify="right", style="white", no_wrap=True)
        table.add_column("Attached", justify="center", style="green", no_wrap=True)
        table.add_column("Duration", justify="right", style="white", no_wrap=True)
        table.add_column("Current Window", style="green")
        table.add_column("Logged IP", style="yellow")

        start = max(0, selected_index - 1)
        end = min(len(sessions), start + 3)

        if end - start < 3:
            start = max(0, end - 3)

        for i in range(start, end):
            s = sessions[i]
            details = self.get_session_details(s["name"])
            style = "reverse" if selected_index == i else ""
            table.add_row(
                str(i),
                s["name"],
                s["created"].strftime("%Y-%m-%d %H:%M"),
                "✓" if s["attached"] else "×",
                str(s["duration"]).split('.')[0],
                self.escape_rich(details["current_window"]),
                self.escape_rich(details["real_ip"]),
                style=style,
            )
        self.console.clear()
        self.console.print(table)

    def render_session_details(self, session: Dict, details: Dict) -> None:
        safe_windows = [self.escape_rich(w) for w in details["windows"]]
        detail_text = "[bold]Windows:[/bold]\n" + "\n".join(safe_windows)
        panel = Panel(detail_text, title=f"{self.escape_rich(session['name'])} Details", border_style="blue")
        self.console.print(panel)

    def send_admin_message(self, sessions: List[Dict], selected_index: int):
        self.console.print("\n[bold green]Admin Message[/bold green]")
        target = input("Send to (s)elected session or (a)ll sessions? [s/a]: ").strip().lower()
        if target not in ("s", "a"):
            self.console.print("[red]Invalid choice.[/red]")
            return

        msg = input("Enter message: ").strip()
        self.console.clear()
        if not msg:
            self.console.print("[red]Message is empty.[/red]")
            return

        def show_popup_async(session_name: str, message: str):
            escaped_msg = shlex.quote(message)
            popup_cmd = f'bash -c "echo {escaped_msg}; sleep 5"'
            full_cmd = ["tmux", "display-popup", "-t", session_name, "-E", popup_cmd]
            subprocess.Popen(full_cmd)

        if target == "s":
            session_name = sessions[selected_index]["name"]
            show_popup_async(session_name, msg)
            self.console.print(f"[green]Message sent to session {session_name}[/green]")
        else:
            for s in sessions:
                show_popup_async(s["name"], msg)
            self.console.print(f"[green]Message sent to all sessions ({len(sessions)})[/green]")

    def run(self):
        sessions = self.list_tmux_sessions()
        if not sessions:
            self.console.print("[red]No tmux sessions found.[/red]")
            return

        selected_index = 0

        while True:
            self.render_sessions_table(sessions, selected_index)
            details = self.get_session_details(sessions[selected_index]["name"])
            self.render_session_details(sessions[selected_index], details)

            self.console.print("\nUse ↑/↓ to select session. [green]a[/green] attach, [yellow]r[/yellow] refresh, [blue]m[/blue] message, [red]q[/red] quit.")
            key = readchar.readkey()

            if key == readchar.key.UP:
                if selected_index > 0:
                    selected_index -= 1
            elif key == readchar.key.DOWN:
                if selected_index < len(sessions) - 1:
                    selected_index += 1
            elif key.lower() == "a":
                session_name = sessions[selected_index]["name"]
                self.console.print(f"Attaching to session: {session_name}")
                subprocess.call(["tmux", "attach-session", "-t", session_name])
                sessions = self.list_tmux_sessions()
                if selected_index >= len(sessions):
                    selected_index = max(0, len(sessions) - 1)
            elif key.lower() == "r":
                sessions = self.list_tmux_sessions()
                if not sessions:
                    self.console.print("[red]No tmux sessions found after refresh.[/red]")
                    return
                if selected_index >= len(sessions):
                    selected_index = max(0, len(sessions) - 1)
            elif key.lower() == "m":
                self.send_admin_message(sessions, selected_index)
            elif key.lower() == "q":
                self.console.print("Exiting...")
                break


if __name__ == "__main__":
    manager = SessionManager()
    manager.run()
