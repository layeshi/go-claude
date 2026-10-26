#!/usr/bin/env python3
"""Build the native app using this checkout and this machine's runtimes."""

import argparse
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build/macos"
APP = ROOT / "dist/Claude 接续助手.app"
BUNDLE_ID = "local.codex.claude-handoff"
VERSION = "1.2.0"


def run(*args):
    subprocess.run(list(map(str, args)), check=True)


def build(claude_path=None):
    if sys.platform != "darwin":
        raise SystemExit("macOS 应用构建需要在 Mac 上运行。")
    if sys.version_info < (3, 10):
        raise SystemExit("需要 Python 3.10 或更新版本。")
    claude = str(Path(claude_path).expanduser().absolute()) if claude_path else shutil.which("claude")
    if not claude:
        raise SystemExit("未找到 Claude Code CLI，请先安装并登录。")
    environment = os.environ.copy()
    environment["PATH"] = str(Path(claude).parent) + os.pathsep + environment.get("PATH", "/usr/bin:/bin")
    result = subprocess.run([claude, "--version"], check=True, capture_output=True,
                            text=True, env=environment, timeout=20)
    version = re.search(r"\b(\d+)\.(\d+)\.(\d+)\b", result.stdout)
    if not version or tuple(map(int, version.groups())) < (2, 1, 285):
        raise SystemExit("需要 Claude Code CLI 2.1.285+；可通过 --claude 指定新版 CLI 的可执行文件路径。")
    if not shutil.which("xcrun"):
        raise SystemExit("需要 Apple Command Line Tools。")
    if APP.is_symlink():
        raise SystemExit("输出路径是符号链接，未覆盖。")
    if APP.exists():
        info = APP / "Contents/Info.plist"
        if not info.is_file() or plistlib.loads(info.read_bytes()).get("CFBundleIdentifier") != BUNDLE_ID:
            raise SystemExit("同名输出应用不属于本工具，未覆盖。")
        shutil.rmtree(APP)
    BUILD.mkdir(parents=True, exist_ok=True)
    macos = APP / "Contents/MacOS"
    resources = APP / "Contents/Resources"
    macos.mkdir(parents=True)
    resources.mkdir(parents=True)
    info_path = APP / "Contents/Info.plist"
    info_path.write_bytes(plistlib.dumps({"CFBundleIdentifier": BUNDLE_ID}))
    tool = resources / "tool"
    tool.mkdir()
    for name in ("handoff.py", "desktop_sessions.py"):
        shutil.copy2(ROOT / "src" / name, tool / name)
    shutil.copytree(ROOT / "docs", tool / "docs")
    (resources / "runtime.json").write_text(json.dumps({
        "python": sys.executable, "claude_bin": str(Path(claude).parent),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    run("xcrun", "clang", "-fobjc-arc", "-O2", "-mmacosx-version-min=13.0",
        "-framework", "Cocoa", "-framework", "Carbon",
        ROOT / "macos/Launcher.m", "-o", macos / "ClaudeHandoff")
    run("xcrun", "clang", "-fobjc-arc", "-O2", "-mmacosx-version-min=13.0",
        "-framework", "Cocoa", ROOT / "macos/MakeIcon.m", "-o", BUILD / "MakeIcon")
    icon = BUILD / "icon-1024.png"
    run(BUILD / "MakeIcon", icon)
    iconset = BUILD / "AppIcon.iconset"
    iconset.mkdir(exist_ok=True)
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            suffix = "@2x" if scale == 2 else ""
            run("sips", "-z", size * scale, size * scale, icon,
                "--out", iconset / f"icon_{size}x{size}{suffix}.png")
    run("iconutil", "-c", "icns", iconset, "-o", resources / "AppIcon.icns")
    info_path.write_bytes(plistlib.dumps({
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleName": "Claude 接续助手",
        "CFBundleDisplayName": "Claude 接续助手",
        "CFBundleExecutable": "ClaudeHandoff",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "CFBundleIconFile": "AppIcon",
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
        "NSAppleEventsUsageDescription": "显示本机项目接续菜单与目录选择窗口。",
    }))
    run("codesign", "--force", "--sign", "-", "--timestamp=none", APP)
    run("codesign", "--verify", "--deep", "--strict", APP)
    run(macos / "ClaudeHandoff", "--self-test")
    print(f"Built and verified: {APP}")
    return APP


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="构建本机 Claude 接续助手应用")
    parser.add_argument("--claude", type=Path, help="指定 Claude Code CLI 可执行文件")
    options = parser.parse_args()
    build(options.claude)
