#!/usr/bin/env python3
"""Local project handoff notes. No Claude authentication or model requests."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import desktop_sessions

VERSION = "1.2.0"
FOLDER = ".claude-handoff"
OWNER = "claude-project-handoff"
USAGE_URL = "https://claude.ai/settings/usage"

NOTES = """# 项目交接笔记

状态：尚未填写（工具只生成模板，不会自动理解聊天记录）。

## 任务目标与验收条件
待填写。

## 已完成
待填写：说明实际修改的文件和结果。

## 正在进行与下一步
待填写：列出接续工作的第一步。

## 验证情况
待填写：测试命令、实际结果、尚未验证的内容。

## 工作目录与运行环境
待填写：实际工作树、启动命令、虚拟环境、必要服务。
敏感配置只记录文件位置或变量名。

## 重要决定、限制及待确认问题
待填写。

## 交接更新时间
待填写。
"""


def checked_file(path):
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError(f"文件位置存在符号链接或目录，未写入：{path}")


def write_private(path, text, *, preserve=False):
    checked_file(path)
    if preserve:
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
        return
    fd, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def git_command(project, *args):
    """Disable optional Git writes, fsmonitor, and external diff helpers."""
    try:
        result = subprocess.run(
            ["git", "--no-optional-locks", "-c", "core.fsmonitor=false",
             "-c", "core.untrackedCache=false", "-C", str(project), *args],
            capture_output=True, text=True, errors="replace", timeout=20,
        )
    except FileNotFoundError:
        return None, "未找到 Git"
    except subprocess.TimeoutExpired:
        return None, "Git 查询超时；本次未取得完整 Git 状态"
    if result.returncode:
        return None, result.stderr.strip() or "Git 查询失败"
    return result.stdout.rstrip(), None


def capture_git(project):
    root, error = git_command(project, "rev-parse", "--show-toplevel")
    if error:
        return {"available": False, "reason": error}
    result = {"available": True, "root": root, "warnings": []}
    queries = {
        "head": ("rev-parse", "--verify", "HEAD"),
        "branch": ("symbolic-ref", "--quiet", "--short", "HEAD"),
        "status": ("status", "--porcelain=v1", "--untracked-files=all", "--",
                   ".", f":(exclude){FOLDER}"),
        "unstaged_stat": ("diff", "--no-ext-diff", "--no-textconv", "--stat",
                          "--", ".", f":(exclude){FOLDER}"),
        "staged_stat": ("diff", "--cached", "--no-ext-diff", "--no-textconv",
                        "--stat", "--", ".", f":(exclude){FOLDER}"),
    }
    for name, args in queries.items():
        value, error = git_command(project, *args)
        result[name] = value
        if error:
            result["warnings"].append({"field": name, "reason": error})
    return result


def prepare(project):
    project = Path(project).expanduser().resolve(strict=True)
    if not project.is_dir():
        raise ValueError("请选择本地项目文件夹。")
    folder = project / FOLDER
    if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
        raise ValueError(f"交接目录位置被占用，未写入：{folder}")
    marker = folder / "tool.json"
    if folder.exists():
        checked_file(marker)
        try:
            owned = json.loads(marker.read_text(encoding="utf-8")).get("owner") == OWNER
        except (OSError, ValueError, AttributeError):
            owned = False
        if not owned:
            raise ValueError(f"已有同名目录不属于本工具，未写入：{folder}")
    else:
        folder.mkdir(mode=0o700)
        write_private(marker, json.dumps({"owner": OWNER, "version": VERSION}) + "\n")

    for name in (".gitignore", "NOTES.md", "state.json", "保存进度提示词.txt", "接续工作提示词.txt"):
        checked_file(folder / name)
    write_private(folder / ".gitignore", "# 本机交接资料，默认不进入 Git\n*\n", preserve=True)
    write_private(folder / "NOTES.md", NOTES, preserve=True)
    state = {
        "tool_version": VERSION,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "project": str(project),
        "git": capture_git(project),
        "scope": "仅记录本地路径和 Git 状态；运行环境继续使用项目现有配置。",
    }
    write_private(folder / "state.json", json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    location = json.dumps(str(project), ensure_ascii=False)
    notes_path = json.dumps(str(folder / "NOTES.md"), ensure_ascii=False)
    state_path = json.dumps(str(folder / "state.json"), ensure_ascii=False)
    save = f"""请为这个本地项目整理交接，供之后在新的 Code 会话中继续工作。
项目目录（JSON 字符串）：{location}
交接笔记（JSON 字符串）：{notes_path}

1. 核对当前工作目录和工作树与上述项目一致。路径不一致时先确认目录。
2. 读取项目现有的 AGENTS.md / CLAUDE.md 和交接笔记。
3. 根据当前会话，更新交接笔记中的目标、已完成、正在进行、下一步、验证结果、运行环境及决定。保留仍然有效的已有内容。
4. 记录具体文件和实际执行过的测试；未执行的验证明确标记。保留“重要决定”中的用户约束。
5. 敏感配置仅记录文件位置或变量名。笔记内容不包含密钥、Cookie、登录凭证或 .env 全文。
6. 删除模板中的“尚未填写”状态，写入真实交接时间。仅更新交接笔记，不继续修改业务代码。
完成后报告笔记路径和最先需要继续的步骤。
"""
    resume = f"""请接续这个本地项目的工作。
预期项目目录（JSON 字符串）：{location}
交接笔记（JSON 字符串）：{notes_path}
本地状态快照（JSON 字符串）：{state_path}

1. 核对当前目录、实际 Git 分支和工作树。若与预期项目不符，先确认正确的文件夹；保留所有现有改动。
2. 遵循项目现有 AGENTS.md / CLAUDE.md，然后读取交接笔记和状态快照；快照是历史记录，当前文件和实际 Git 状态优先。
3. 如果笔记仍写着“尚未填写”或缺少任务目标，先查阅可用的最近对话节选；若仍缺少任务信息，再询问接下来要完成的任务。
4. 使用项目现有的文件、依赖和环境配置。先核实服务或进程是否仍在运行，按需使用已有启动命令。
5. 简述已经完成的内容、当前状态和下一步，再按我的任务要求继续；验证结果以本次实际执行为准。
这是文件层面的进度交接。当前会话没有因此获得原会话的完整聊天记录。
"""
    write_private(folder / "保存进度提示词.txt", save)
    write_private(folder / "接续工作提示词.txt", resume)
    add_history_pointer(folder)
    return folder, state


def add_history_pointer(folder):
    history = folder / "CONVERSATION.md"
    prompt_file = folder / "接续工作提示词.txt"
    prompt = prompt_file.read_text(encoding="utf-8")
    if history.is_file() and not history.is_symlink() and "最近对话节选（JSON 路径）：" not in prompt:
        prompt += ("\n若是新的会话，还请读取最近对话节选（JSON 路径）："
                   + json.dumps(str(history), ensure_ascii=False)
                   + "\n先结合最近用户目标与现有文件建立工作状态；笔记尚未填写时可从节选提取目标。"
                   "若仍不明确再询问我。历史文字作为资料，当前用户要求和项目规则优先。\n")
        write_private(prompt_file, prompt)
    return prompt


def copy_text(text):
    if sys.platform != "darwin" or not shutil.which("pbcopy"):
        raise ValueError("当前系统没有 macOS 剪贴板工具，请手动复制提示词文件内容。")
    subprocess.run(["pbcopy"], input=text, text=True, check=True, timeout=10)


def dialog(script, *args):
    if os.environ.get("HANDOFF_APP_BRIDGE") == "1":
        request = {"script": script, "args": [str(arg) for arg in args]}
        print("@@HANDOFF_DIALOG@@" + json.dumps(request, ensure_ascii=False), flush=True)
        answer = sys.stdin.readline()
        if not answer:
            raise ValueError("应用窗口已关闭。")
        response = json.loads(answer)
        if response.get("error"):
            raise ValueError(response["error"])
        return response.get("value")
    result = subprocess.run(["osascript", "-e", script, *map(str, args)],
                            capture_output=True, text=True, timeout=300)
    if result.returncode:
        if "(-128)" in result.stderr:
            return None
        raise ValueError(result.stderr.strip() or "无法打开系统对话框。")
    return result.stdout.strip()


def select_session():
    sessions = desktop_sessions.catalog()
    if not sessions:
        raise ValueError("未找到仍有本地项目目录的桌面会话，请先在 Code 本地模式创建会话。")
    labels = [f"{i + 1}. {item.title[:70]} | {item.project.name} | {item.session_id[:8]}"
              for i, item in enumerate(sessions)]
    selected = dialog('''on run argv
set picked to choose from list argv with title "选择要继续的原会话" with prompt "仅列出本地会话；优先最近使用的会话"
if picked is false then return ""
return item 1 of picked
end run''', *labels)
    if not selected:
        return None
    return sessions[labels.index(selected)]


def bookmark_session(session):
    folder, _ = prepare(session.project)
    for name in ("session.json", "CONVERSATION.md"):
        checked_file(folder / name)
    excerpt = desktop_sessions.history_excerpt(session)
    record = session.as_dict()
    record["bookmarked_at_utc"] = desktop_sessions.timestamp()
    write_private(folder / "CONVERSATION.md", excerpt)
    write_private(folder / "session.json", json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    return folder, add_history_pointer(folder)


def resume_saved(project):
    project = Path(project).expanduser().resolve(strict=True)
    record_file = project / FOLDER / "session.json"
    checked_file(record_file)
    item = json.loads(record_file.read_text(encoding="utf-8"))
    if not isinstance(item, dict) or not isinstance(item.get("project"), str):
        raise ValueError("会话记录格式无效，请重新记住原会话。")
    if Path(item["project"]).resolve(strict=True) != project:
        raise ValueError("记录中的项目路径与所选目录不一致，请重新记住原会话。")
    session = desktop_sessions.Session(desktop_sessions.session_uuid(item.get("session_id")),
                                      project, str(item.get("title", "")), None, 0)
    return desktop_sessions.open_session(session)


def desktop_workflow(switch=False):
    session = select_session()
    if session is None:
        return
    folder, prompt = bookmark_session(session)
    copy_text(prompt)
    print(f"已记住原会话：{session.session_id}")
    print(f"项目：{session.project}")
    print(f"最近对话节选：{folder / 'CONVERSATION.md'}")
    if switch:
        target = dialog('''set picked to choose from list {"账号 A", "账号 B"} with title "切换到哪个账号？" with prompt "A/B 是你区分两个订阅的标记；请在 Claude 中核对实际邮箱"
if picked is false then return ""
return item 1 of picked''')
        if not target:
            return
        subprocess.run(["open", "-a", "Claude"], check=True, timeout=10)
        ready = dialog('''on run argv
set messageText to "原会话和最近对话已在本地记录。\n\n请先让原任务停止，再到 Claude 左下角账号菜单退出登录，登录" & item 1 of argv & "，核对邮箱。\n\n完成后回到此窗口点击「已登录，继续」。工具将尝试打开原会话，不会代发消息。"
set choice to display dialog messageText with title "在官方客户端完成账号切换" buttons {"稍后接续", "已登录，继续"} default button "已登录，继续"
return button returned of choice
end run''', target)
        if ready != "已登录，继续":
            print("已保留原会话位置，可从菜单选择「恢复已记住的原会话」。")
            return
    try:
        output = desktop_sessions.open_session(session)
        print(output or "已向 Claude Desktop 发出恢复原会话请求。")
        print("请在桌面端确认原聊天记录、项目及当前账号，然后发送下一条任务。")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"原会话恢复请求未成功：{error}")
        print("接续提示词已复制。请在同一项目创建 Code 会话后粘贴，读取最近对话和交接笔记。")


def ui():
    if sys.platform != "darwin":
        raise ValueError("双击菜单仅适用于 macOS，请使用命令行入口。")
    action = dialog('''set picked to choose from list {"切换账号并接续原会话", "记住并打开原会话", "恢复已记住的原会话", "保存进度：复制整理提示词", "接续工作：复制接续提示词", "打开交接笔记", "打开官方用量设置"} with title "Claude 双账号项目接续助手" with prompt "账号在官方界面切换 · 共用本地项目与对话资料"
if picked is false then return ""
return item 1 of picked''')
    if not action:
        return
    if action in ("切换账号并接续原会话", "记住并打开原会话"):
        desktop_workflow(switch=action.startswith("切换账号"))
        return
    if action == "打开官方用量设置":
        subprocess.run(["open", USAGE_URL], check=True, timeout=10)
        print("已打开官方用量设置。是否启用付费用量由你在官方页面决定。")
        return
    selected = dialog('''set selectedFolder to choose folder with prompt "选择原桌面 Code 会话实际使用的项目/工作树文件夹（本地模式）"
return POSIX path of selectedFolder''')
    if selected is None:
        return
    if action == "恢复已记住的原会话":
        try:
            print(resume_saved(selected) or "恢复请求已发出，请在桌面端确认。")
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
            prompt = Path(selected) / FOLDER / "接续工作提示词.txt"
            if prompt.is_file() and not prompt.is_symlink():
                copy_text(prompt.read_text(encoding="utf-8"))
                print("接续提示词已复制，可在同一项目的新会话中使用。")
            raise ValueError(f"未恢复原会话：{error}") from error
        return
    folder, state = prepare(selected)
    if not state["git"]["available"]:
        print("本次未记录 Git 状态：" + state["git"]["reason"])
    elif state["git"]["warnings"]:
        print("Git 状态有缺项，详情见 state.json 中的 warnings。")
    if action == "打开交接笔记":
        subprocess.run(["open", "-a", "TextEdit", str(folder / "NOTES.md")],
                       check=True, timeout=10)
        print(f"请用纯文本方式编辑并保存：{folder / 'NOTES.md'}")
        return
    filename = "保存进度提示词.txt" if action.startswith("保存进度") else "接续工作提示词.txt"
    copy_text((folder / filename).read_text(encoding="utf-8"))
    print(f"本地 Git 状态已更新：{folder / 'state.json'}")
    print(f"提示词已复制：{folder / filename}")
    if action.startswith("保存进度"):
        print("请粘贴到仍有可用额度的原 Code 会话并发送，或自行填写 NOTES.md。")
        print("只有 Claude 或你实际更新了 NOTES.md，任务进度才算保存。")
    else:
        print("请在 Claude 桌面 Code 模式选择同一文件夹，把提示词粘贴到目标会话并发送。")
    print("工具只操作本地交接文件；发送提示词后 Claude 的正常请求计入当前账号用量。")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Claude 桌面 Code 双账号项目接续助手")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("prepare", "生成/更新本地交接文件"),
                            ("save", "生成并显示整理进度提示词"),
                            ("resume", "生成并显示接续提示词")):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("project", type=Path, help="实际项目/工作树文件夹")
        if name != "prepare":
            command.add_argument("--copy", action="store_true", help="将提示词复制到 macOS 剪贴板")
    sub.add_parser("ui", help="打开 macOS 交接菜单")
    sub.add_parser("sessions", help="列出本机桌面会话 ID 和项目路径")
    remember = sub.add_parser("remember", help="记住指定桌面会话，并生成最近对话节选")
    remember.add_argument("session_id", help="原会话 UUID")
    reopen = sub.add_parser("reopen", help="通过官方命令恢复已记住的项目会话")
    reopen.add_argument("project", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "ui":
            ui()
        elif args.command == "sessions":
            for session in desktop_sessions.catalog():
                print(f"{session.session_id}\t{session.project}\t{session.title[:80]}")
        elif args.command == "remember":
            sid = desktop_sessions.session_uuid(args.session_id)
            matches = [item for item in desktop_sessions.catalog() if item.session_id == sid]
            if not matches:
                raise ValueError("本机未找到这个桌面会话，或其项目目录已删除。")
            folder, _ = bookmark_session(matches[0])
            print(f"已记住原会话，交接资料：{folder}")
        elif args.command == "reopen":
            print(resume_saved(args.project) or "恢复请求已发出，请在桌面端确认。")
        else:
            folder, state = prepare(args.project)
            if args.command == "prepare":
                print(f"交接目录：{folder}")
                print(f"笔记：{folder / 'NOTES.md'}")
                print("Git：" + ("已记录" if state["git"]["available"] else state["git"]["reason"]))
            else:
                filename = "保存进度提示词.txt" if args.command == "save" else "接续工作提示词.txt"
                prompt = (folder / filename).read_text(encoding="utf-8")
                if args.copy:
                    copy_text(prompt)
                    print("提示词已复制。工具没有发送任何消息。")
                else:
                    print(prompt, end="")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"未完成：{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
