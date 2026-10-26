# go-claude · Claude 接续助手

在一台 Mac 上为两个 Claude 订阅账号接续本地 Code 工作：记住原会话，在官方客户端手动登录另一个账号，然后尝试恢复原会话。恢复失败时，通过最近对话节选和项目交接笔记继续。

应用名称为 **Claude 接续助手**，可以安装到“应用程序”，通过 Spotlight 搜索打开。

## 功能

- 从本机 Claude Desktop 的本地会话中选择原会话，记录会话 ID、实际项目目录和工作树。
- 引导用户在官方客户端手动切换 A/B 账号，再调用官方恢复命令。
- 从本地记录提取最近对话文字；原账号已达到用量限制时也能准备接续资料。
- 在同一个项目目录中维护进度笔记和 Git 状态，复用项目文件、依赖及本地配置。
- 提供原生 macOS 应用菜单，以及独立 Python 命令行入口。

账号登录由 Claude 官方客户端完成。工具不管理登录凭证、不判断订阅剩余额度、不执行无人值守的自动轮换；账号使用应遵循 Anthropic 的适用规则和官方说明。

## 本机安装

要求：macOS 13 或更新版本、Python 3.10+、Apple Command Line Tools、Claude Desktop，以及已经完成订阅登录的 Claude Code CLI 2.1.285+。如缺少开发工具，可手动运行 `xcode-select --install`。

```sh
git clone https://github.com/layeshi/go-claude.git
cd go-claude
python3 scripts/install_macos_app.py
```

安装后按 **⌘ 空格**，搜索 **Claude 接续助手**。应用包内包含程序文件，并在构建时记录本机 Python 与 Claude CLI 路径；不是包含 Python 解释器的独立运行时安装包。

构建前请用 `python3 --version` 和 `claude --version` 确认依赖版本。若系统里有多份 CLI，可加 `--claude "/新版 Claude CLI 的绝对路径"` 指定实际使用的版本；该参数同时适用于构建和安装脚本。

已有同名应用时，先退出应用，再执行：

```sh
python3 scripts/install_macos_app.py --replace
```

只构建应用：

```sh
python3 scripts/build_macos_app.py
```

输出位于 `dist/Claude 接续助手.app`，构建过程会进行本地签名校验和原生参数桥接自测。应用仅在本机签名，未提供 Apple 开发者签名或公证发布包。

## 使用

1. 打开应用，选择“切换账号并接续原会话”。
2. 选择需要继续的会话和目标账号标记。
3. 让原任务停止，在 Claude 官方客户端退出原账号、登录另一个账号，核对实际邮箱。
4. 回到助手点击“已登录，继续”，随后在 Claude 中确认账号、项目与原会话，再发送下一条任务。

官方恢复命令成功退出只表示请求已发出；跨账号能否直接显示完整原会话，仍需在实际客户端验证。若未恢复，选择同一项目创建新 Code 会话，粘贴助手生成的接续提示词。

详细流程、数据文件及后备方式见 [使用说明](docs/usage.md)。

## 命令行

```sh
python3 src/handoff.py ui
python3 src/handoff.py sessions
python3 src/handoff.py remember "原会话UUID"
python3 src/handoff.py reopen "/实际项目路径"
python3 src/handoff.py save "/实际项目路径" --copy
python3 src/handoff.py resume "/实际项目路径" --copy
```

## 验证

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 scripts/build_macos_app.py
```

现有 23 项测试覆盖笔记保留、Git 状态、路径与目录冲突、工作树、会话发现、对话节选、恢复命令、取消流程、原生菜单脚本编译，以及安装更新保护与失败回滚。非 macOS 环境会跳过原生菜单编译检查。

真实账号切换及跨账号完整会话恢复尚未完成自动化验证。参见 [验证范围](docs/verification.md)。

## 项目结构

```text
src/       本地会话与项目交接逻辑
macos/     AppKit 原生启动器与图标源代码
scripts/   本机应用构建与安装
tests/     标准库 unittest 测试
docs/      使用说明与验证范围
```

构建产物、本机运行路径、账号资料和项目对话资料均不纳入版本控制。
