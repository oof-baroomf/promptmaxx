# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "litellm",
#     "pyperclip",
#     "textual",
#     "tiktoken",
# ]
# ///

from __future__ import annotations
import asyncio
import json
import os
import re
import shlex
import subprocess
import sys
import traceback
from pathlib import Path
from typing import List, Dict

import pyperclip
import litellm
import tiktoken
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Header, Input, RichLog, Static

# ──────────────────────────── configuration ──────────────────────────── #

CFG_PATH = Path.home() / ".config" / "promptmaxx" / "config.json"
DEFAULT_CFG: Dict = {
    "show_tree_before_files": True,
    "prompt_prefix": "Here are the files in my folder:\n",
    "editing_prompt": (
        "You are an expert file editor. You will be given the contents of "
        "various files and edits to make, and you must format the edits in a "
        "machine-readable way., by providing the WHOLE edited file.\n\n"
        "To suggest changes to a file you MUST return the entire content of "
        "the updated file.\n"
        "You MUST use this *file listing* format:\n\n"
        "path/to/filename.js\n"
        "```\n"
        "// entire file content ...\n"
        "// ... goes in between\n"
        "```\n\n"
        "Every *file listing* MUST use this format:\n"
        "- First line: the filename with any originally provided path; no extra "
        "markup, punctuation, comments, etc. JUST the filename with path.\n"
        "- Second line: opening ```\n"
        "- ... entire content of the file ...\n"
        "- Final line: closing ```\n\n"
        "To suggest changes to a file you MUST return a *file listing* that "
        "contains the entire content of the file.\n"
        "*NEVER* skip, omit or elide content from a *file listing* using \"...\" "
        "or by adding comments like \"... rest of code...\"!\n"
        "To create a new file you MUST return a *file listing* which includes an "
        "appropriate filename, including any appropriate path. DO NOT provide a patch."
    ),
    "picker_prompt": (
        "You are a highly accurate file selector. You will receive a directory "
        "tree and a set of user instructions describing code edits. "
        "Return ONLY a JSON array of file paths (as strings) that the edits "
        "apply to. If the user needs to create a brand-new file, include the "
        "intended path for that new file in the array. Do NOT include anything "
        "else – no prose, no code fences, no comments."
    ),
    "model_id": "cerebras/qwen-3-32b",
    "api_key": "$CEREBRAS_API_KEY",
    "default_files": ["README.md"],
}

def load_cfg() -> Dict:
    CFG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CFG_PATH.exists():
        CFG_PATH.write_text(json.dumps(DEFAULT_CFG, indent=2))
    try:
        user_cfg = json.loads(CFG_PATH.read_text())
    except Exception:
        user_cfg = {}
    cfg = {**DEFAULT_CFG, **user_cfg}
    CFG_PATH.write_text(json.dumps(cfg, indent=2))
    return cfg

CFG = load_cfg()

def resolve_api_key(raw: str) -> str:
    """Resolve $VARNAME -> os.environ['VARNAME']; escape with \\$."""
    if raw.startswith(r"\$"):
        return raw[1:]
    if raw.startswith("$"):
        return os.getenv(raw[1:], "")
    return raw

API_KEY = resolve_api_key(CFG["api_key"])

# ─────────────────────────────── helpers ─────────────────────────────── #

TOKEN_FACTOR = 0.25

def repo_files() -> List[Path]:
    ignore = Path(".maxxignore") if Path(".maxxignore").exists() else Path(".gitignore")
    patterns = [p.strip() for p in ignore.read_text().splitlines()] if ignore.exists() else []
    return [
        p
        for p in Path.cwd().rglob("*")
        if p.is_file() and not any(p.match(pat) for pat in patterns)
    ]

def est_tokens(txt: str) -> int:
    try:
        enc = tiktoken.encoding_for_model("gpt-4")
        return len(enc.encode(txt))
    except Exception:
        return int(len(txt) * TOKEN_FACTOR)

def _safe_tree() -> str:
    """
    Render a directory tree that respects .gitignore.
    Falls back to the old behavior if the installed `tree`
    lacks the --gitignore flag.
    """
    try:
        proc = subprocess.run(
            ["tree", "--gitignore", "-I", ".git"],
            text=True,
            capture_output=True,
            check=True,
        )
        return proc.stdout
    except subprocess.CalledProcessError:
        # `tree` executed but returned error
        return proc.stdout or ""
    except FileNotFoundError:
        return ""
    except Exception:
        # Unsupported flag or other failure – fall back
        fallback = subprocess.run(
            ["tree", "-I", ".git"],
            text=True,
            capture_output=True,
        ).stdout
        warning = (
            "[WARNING] Your installed `tree` does not support --gitignore. "
            "Upgrade to v2+ for accurate output.\n"
        )
        return warning + fallback

# ──────────────────────── command registry ───────────────────────────── #

COMMANDS: Dict[str, str] = {
    "/a": "Add file(s) to selection",
    "/r": "Remove file(s) from selection",
    "/t": "Estimate tokens of current prompt",
    "/c": "Copy current prompt to clipboard",
    "/p": "Paste output from clipboard and apply edits",
    "/h": "Show this help message",
}

# ─────────────────────────────── UI widgets ──────────────────────────── #

class FilePane(Static):
    """Simple textual widget that lists selected files."""

    files: reactive[List[Path]] = reactive([])

    def watch_files(self, files: List[Path]) -> None:
        self.update("\n".join(map(str, files)) or "No files selected")

# ────────────────────────────── main app ─────────────────────────────── #

class PromptMaxx(App):
    CSS = """
    #files {
      width: 1fr;
      border: solid $panel;
      background: $surface;
      padding: 1;
    }

    #log {
      width: 3fr;
      border: solid $panel;
      background: $surface;
      padding: 1 2;
    }

    #files, #log { height: 1fr; }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", show=False),
        Binding("ctrl+l", "clear_log", "Clear", show=False),
        Binding("ctrl+p", "noop", show=False),  # suppress default palette binding
    ]

    sel_files: reactive[List[Path]] = reactive([])
    prompt_cache: reactive[str] = reactive("")

    # ─────────────────── compose ─────────────────── #

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield FilePane(id="files")
            yield RichLog(id="log", markup=True)
        yield Input(placeholder="Type commands or !shell…", id="input")

    # ─────────────────── utilities ────────────────── #

    def write_log(self, msg: str) -> None:
        self.query_one(RichLog).write(msg)

    def refresh_files(self) -> None:
        pane = self.query_one(FilePane)
        pane.files = list(self.sel_files)

    def build_prompt(self) -> str:
        tree = _safe_tree() if CFG["show_tree_before_files"] else ""
        parts = [CFG["prompt_prefix"], tree]
        for p in self.sel_files:
            parts.append(f"\n### {p} ###\n{p.read_text()}")
        return "".join(parts)

    # ────────────────── lifecycle ─────────────────── #

    def on_mount(self) -> None:
        for f in CFG["default_files"]:
            p = Path(f)
            if p.exists():
                self.sel_files.append(p)
        self.refresh_files()

    # ────────────────── input handling ────────────── #

    async def on_input_submitted(self, ev: Input.Submitted) -> None:
        txt = ev.value.strip()
        ev.input.value = ""
        if not txt:
            return
        if txt.startswith("!"):
            await self.run_shell(txt[1:])
        elif txt.startswith("/"):
            await self.run_cmd(txt)
        else:
            self.write_log(txt)

    async def on_input_changed(self, ev: Input.Changed) -> None:
        text = ev.value
        if text.startswith("/r "):
            rem = set(shlex.split(text[3:]))
            self.sel_files = [p for p in self.sel_files if str(p) not in rem]
            self.refresh_files()
        elif text.startswith("/a "):
            args = shlex.split(text[3:])
            if "." in args:
                args.remove(".")
                args.extend(map(str, repo_files()))
            for f in args:
                p = Path(f)
                if p.is_file() and p not in self.sel_files:
                    self.sel_files.append(p)
            self.refresh_files()
        elif text.startswith("/"):
            ev.input.autocomplete_suggestions = [
                cmd for cmd in COMMANDS if cmd.startswith(text)
            ]

    # ────────────────── shell & commands ──────────── #

    async def run_shell(self, cmd: str) -> None:
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        out, _ = await proc.communicate()
        self.write_log(f"$ {cmd}\n{out.decode()}")

    async def run_cmd(self, txt: str) -> None:
        if txt.startswith("/a "):
            for f in shlex.split(txt[3:]):
                p = Path(f)
                if p.exists() and p not in self.sel_files:
                    self.sel_files.append(p)
            self.refresh_files()
        elif txt.startswith("/r "):
            rem = set(shlex.split(txt[3:]))
            self.sel_files = [p for p in self.sel_files if str(p) not in rem]
            self.refresh_files()
        elif txt == "/t":
            self.write_log(f"Tokens ≈ {est_tokens(self.build_prompt())}")
        elif txt == "/c":
            self.prompt_cache = self.build_prompt()
            pyperclip.copy(self.prompt_cache)
            self.write_log("[cyan]Prompt copied[/cyan]")
        elif txt == "/p":
            await self.handle_paste()
        elif txt in {"/", "/h", "/help"}:
            self.show_help()
        else:
            self.write_log(f"[red]Unknown command {txt}[/red]")

    def show_help(self) -> None:
        lines = [f"[bold]{cmd}[/bold] - {desc}" for cmd, desc in COMMANDS.items()]
        self.write_log("\n".join(lines))

    # ────────────────── LLM interaction ───────────── #

    async def handle_paste(self) -> None:
        paste = pyperclip.paste()
        self.write_log("[magenta]Pasted output:[/magenta]\n" + paste)
        try:
            files = await self.call_picker(paste)
        except Exception as exc:
            self.show_exc(exc)
            return
        await self.call_editor(paste, files)

    async def call_picker(self, paste: str) -> List[str]:
        tree = _safe_tree()
        resp = await asyncio.to_thread(
            litellm.completion,
            model=CFG["model_id"],
            api_key=API_KEY,
            messages=[
                {"role": "system", "content": CFG["picker_prompt"]},
                {"role": "user", "content": "DIRECTORY TREE:\n" + tree + "\n\nUSER INSTRUCTIONS:\n" + paste},
            ],
        )
        raw = resp["choices"][0]["message"]["content"]
        try:
            picked: List[str] = json.loads(raw)
            self.write_log(f"[green]Picker chose:[/green] {picked}")
            return picked
        except Exception:
            raise ValueError("Picker did not return valid JSON array – got:\n" + raw)

    async def call_editor(self, paste: str, files: List[str]) -> None:
        def read_text(f: str) -> str:
            try:
                return Path(f).read_text()
            except Exception:
                return ""
        payload = "\n\n".join(f"### {f}\n{read_text(f)}" for f in files if Path(f).exists())
        self.write_log(str([
            {"role": "system", "content": CFG["editing_prompt"]},
            {"role": "user", "content": paste + "\n\n--- FILES ---\n" + payload},
        ]))
        resp = await asyncio.to_thread(
            litellm.completion,
            model=CFG["model_id"],
            api_key=API_KEY,
            messages=[
                {"role": "system", "content": CFG["editing_prompt"]},
                {"role": "user", "content": paste + "\n\n--- FILES ---\n" + payload},
            ],
        )
        out = resp["choices"][0]["message"]["content"]
        self.write_log(out)
        await self.apply_file_listings(out)

    async def apply_file_listings(self, text: str) -> None:
        pattern = re.compile(r"([^\n]+?)\n```([\s\S]*?)```")
        for match in pattern.finditer(text):
            fname, content = match.group(1).strip(), match.group(2).strip("\n")
            try:
                Path(fname).parent.mkdir(parents=True, exist_ok=True)
                Path(fname).write_text(content)
                self.write_log(f"[green]Updated {fname}[/green]")
            except Exception as exc:
                self.show_exc(exc)

    # ─────────────────────── misc ─────────────────────── #

    def show_exc(self, exc: BaseException) -> None:
        tb = "".join(traceback.format_exception(exc))
        self.write_log(f"[red]ERROR:[/red]\n{tb}")

    def action_clear_log(self) -> None:
        self.query_one(RichLog).clear()

# ────────────────────────── runner ────────────────────────── #

if __name__ == "__main__":
    try:
        PromptMaxx().run()
    except KeyboardInterrupt:
        sys.exit(0)
