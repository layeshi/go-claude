# 验证范围

自动化测试使用 Python 标准库 unittest，测试项目与会话数据均为临时夹具。

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py' -v
```

23 项测试涵盖：源文件和已有笔记保护、Git 索引与配置保护、目录冲突和符号链接、异常路径、缺失或超时的 Git、Git worktree、会话发现、对话文字节选及长度限制、恢复命令参数、取消流程、AppleScript 菜单编译，以及无关应用保护、运行中应用保护和安装校验失败回滚。

macOS 构建时还执行应用签名完整性检查，以及原生 AppleScript 参数桥接自测。非 macOS 系统会跳过原生菜单编译测试；构建与安装脚本仅支持 macOS。

开发验证已实际打开原生主菜单与目录选择窗口。真实账号切换、向 Claude 发送任务、跨账号完整原会话恢复未完成自动化验证。
