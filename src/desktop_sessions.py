"""Read local session metadata and open sessions through the official CLI."""

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid


@dataclass(frozen=True)
class Session:
    session_id: str
    project: Path
    title: str
    transcript: Path | None
    modified: float

    def as_dict(self):
        return {"session_id": self.session_id, "project": str(self.project),
                "title": self.title,
                "transcript": str(self.transcript) if self.transcript else None,
                "modified": self.modified}


def session_uuid(value):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("会话 ID 必须是有效的 UUID。") from None


def catalog(metadata_root=None, config_root=None):
    """Read allowlisted fields only; never copy Desktop metadata or credentials."""
    metadata_root = Path(metadata_root) if metadata_root is not None else (
        Path.home() / "Library/Application Support/Claude/claude-code-sessions")
    config_root = Path(config_root) if config_root is not None else Path(
        os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")))
    transcripts = {}
    for path in (config_root / "projects").glob("*/*.jsonl"):
        if not path.is_symlink() and path.is_file():
            transcripts[path.stem] = path.resolve()
    sessions = {}
    for path in metadata_root.rglob("local_*.json"):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            sid = session_uuid(item.get("cliSessionId"))
            raw_cwd = item.get("cwd")
            if not isinstance(raw_cwd, str) or not Path(raw_cwd).is_absolute():
                continue
            project = Path(raw_cwd).resolve(strict=True)
            if not project.is_dir():
                continue
            title = item.get("title")
            title = " ".join(title.split()) if isinstance(title, str) else "未命名会话"
            session = Session(sid, project, title[:240], transcripts.get(sid), path.stat().st_mtime)
            if sid not in sessions or session.modified > sessions[sid].modified:
                sessions[sid] = session
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return sorted(sessions.values(), key=lambda session: session.modified, reverse=True)


def history_excerpt(session, *, max_messages=40, max_message_chars=4000, max_total_chars=80000):
    """Extract recent user/assistant text; skip images, thinking, and tool bodies."""
    if not session.transcript:
        return "# 最近对话节选\n\n本机未找到对应对话记录，请使用交接笔记。\n"
    if session.transcript.is_symlink() or not session.transcript.is_file():
        raise ValueError("原对话记录已移动或不可用，请重新选择会话。")
    messages = deque(maxlen=max_messages)
    with session.transcript.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            try:
                entry = json.loads(line)
                if not isinstance(entry, dict) or entry.get("isMeta"):
                    continue
                if entry.get("sessionId") not in (None, session.session_id):
                    continue
                message = entry.get("message", {})
                role = message.get("role")
                if role not in ("user", "assistant"):
                    continue
                content = message.get("content", "")
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    text = "\n".join(block.get("text", "") for block in content
                                     if isinstance(block, dict) and block.get("type") == "text"
                                     and isinstance(block.get("text"), str))
                else:
                    continue
                if not text.strip():
                    continue
                if len(text) > max_message_chars:
                    text = text[:max_message_chars] + "\n[本条过长，后文省略；可按需查看原记录]"
                messages.append((role, text))
            except (ValueError, TypeError, AttributeError):
                continue
    blocks = []
    used = 0
    for role, text in reversed(messages):
        label = "用户" if role == "user" else "Claude"
        block = f"## {label}\n\n{text}\n\n"
        if used + len(block) > max_total_chars:
            break
        blocks.append(block)
        used += len(block)
    header = ("# 最近对话节选\n\n原始文字节选，不是模型总结。保留最近最多 40 条文本消息；"
              "长消息有截断，工具结果、图片和思考过程未包含。原记录保持原样。\n\n"
              f"会话 ID：{session.session_id}\n\n"
              f"原记录路径（JSON）：{json.dumps(str(session.transcript), ensure_ascii=False)}\n\n")
    return header + ("".join(reversed(blocks)) or "没有可提取的用户/助手文本，请使用交接笔记。\n")


def open_session(session):
    """Request Desktop resume. A zero exit code only confirms command dispatch."""
    sid = session_uuid(session.session_id)
    project = session.project.resolve(strict=True)
    if not project.is_dir():
        raise ValueError("原项目/工作树目录不存在。")
    executable = shutil.which("claude")
    if not executable:
        raise ValueError("未找到 Claude Code CLI。请在桌面 Code 输入 /resume，或使用接续提示词。")
    result = subprocess.run([executable, "--desktop", "--resume", sid], cwd=project,
                            capture_output=True, text=True, errors="replace", timeout=45)
    if result.returncode:
        raise ValueError((result.stderr.strip() or result.stdout.strip() or "恢复命令失败")[:3000])
    return result.stdout.strip()


def timestamp():
    return datetime.now(timezone.utc).isoformat()
