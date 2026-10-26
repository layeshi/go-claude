#!/usr/bin/env python3
"""Build and install the app, preserving an existing install on failure."""

import argparse
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile

from build_macos_app import APP, BUNDLE_ID, build, run


def install(directory, replace=False, claude_path=None):
    directory = Path(directory).expanduser().resolve(strict=True)
    if not directory.is_dir():
        raise SystemExit("安装位置需要是现有目录。")
    target = directory / APP.name
    if target.is_symlink():
        raise SystemExit("安装位置存在符号链接，未覆盖。")
    if target.exists():
        info = target / "Contents/Info.plist"
        if not info.is_file() or plistlib.loads(info.read_bytes()).get("CFBundleIdentifier") != BUNDLE_ID:
            raise SystemExit("同名应用不属于本工具，未覆盖。")
        if not replace:
            raise SystemExit("应用已安装。退出应用后，加 --replace 更新。")
        processes = subprocess.run(["ps", "-A", "-o", "args="], check=True,
                                   capture_output=True, text=True, errors="replace").stdout
        executable = str(target / "Contents/MacOS/ClaudeHandoff")
        if any(line.strip() == executable or line.strip().startswith(executable + " ")
               for line in processes.splitlines()):
            raise SystemExit("请先退出 Claude 接续助手，再更新。")
    app = build(claude_path)
    with tempfile.TemporaryDirectory(prefix=".go-claude-install-", dir=directory) as staging:
        staging = Path(staging)
        candidate = staging / APP.name
        backup = staging / "previous.app"
        shutil.copytree(app, candidate, symlinks=True)
        run("codesign", "--verify", "--deep", "--strict", candidate)
        had_previous = target.exists()
        if had_previous:
            target.rename(backup)
        try:
            candidate.rename(target)
            run("codesign", "--verify", "--deep", "--strict", target)
        except BaseException:
            if target.exists():
                shutil.rmtree(target)
            if had_previous:
                backup.rename(target)
            raise
    register = Path("/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister")
    run(register, "-f", target)
    run("mdimport", target)
    print(f"Installed: {target}")
    print("按 ⌘ 空格，搜索“Claude 接续助手”即可打开。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="构建并安装 Claude 接续助手")
    parser.add_argument("--install-dir", default="/Applications", help="已有的安装目录")
    parser.add_argument("--replace", action="store_true", help="更新已退出的同名助手应用")
    parser.add_argument("--claude", type=Path, help="指定 Claude Code CLI 可执行文件")
    options = parser.parse_args()
    install(options.install_dir, options.replace, options.claude)
