# jupyter-mcp-server（Linux）

> 2026-10-02 由 Windows / conda 迁至 Linux / uv venv。

## 启动 / 停止

```bash
./start_jupyter.sh start [工作目录]   # 默认项目根；后台运行
./start_jupyter.sh status
./start_jupyter.sh stop
```
demo@ubuntu:~$ cd /home/demo/桌面/ai4/mcp使用注意事项
demo@ubuntu:~/桌面/ai4/mcp使用注意事项$ ./start_jupyter.sh start /home/demo/桌面/ai4

如果要切换实际执行的内核，可以参考下面的写法：
jupyter kernelspec list        # 看现有内核
jupyter nbconvert --execute --ExecutePreprocessor.kernel_name=ros_py38 目标.ipynb

访问：http://127.0.0.1:8889/lab?token=mcpjup

> 登录页写的是 “Password or token”，填 `mcpjup`；留空提交会失败，看起来像要密码。

## 环境

| 项 | 值 |
|---|---|
| venv | `/home/demo/.venvs/mcpjup`（Python 3.12.15） |
| JupyterLab | 4.6.4 + collaboration |
| kernel | `mcpjup`（唯一且为默认） |
| token / 端口 | `mcpjup` / `127.0.0.1:8889` |
| 日志 | `/tmp/mcpjup-jupyter.log` |

加包：`/home/demo/.venvs/mcpjup/bin/pip install <pkg>`，装完需重启服务。

MCP 侧见 `.mcp.json` 的 `jupyter` 条目，变量为 `CODE_SANDBOX_URL` / `CODE_SANDBOX_TOKEN`
（旧名 `JUPYTER_URL` / `JUPYTER_TOKEN` 已废弃）。

## 两个易踩的坑

1. **必须用 `jupyter lab` 启动、必须装 `jupyter-collaboration`**：新版 MCP 走
   collaboration API（ydoc），不再是老的 server 接口。
2. **默认 kernel 会变成 `python3`**：分别由 `MultiKernelManager.default_kernel_name`
   （不是 `KernelSpecManager`）和 `KernelSpecManager.ensure_native_kernel`（默认 True，
   会运行时合成一个 spec）决定，脚本里已用两个参数关掉。**写错类名不报错，只静默失效。**

验证要看运行中的服务（`jupyter kernelspec list` 是独立进程，会误导）：

```bash
curl -sS "http://127.0.0.1:8889/api/kernelspecs?token=mcpjup"   # 期望只有 mcpjup
```

## 使用规范

- **kernel 是活的**：变量跨调用累积。先 `import pandas as pd`，下一个 cell 直接用 `pd` 即可（注意状态污染）。
- **JupyterLab 需一直开着**：关掉就连不上了。
- 用**插入 cell** 跑代码，而不是命令行，便于我查看和修改（环境检查类除外）。
- 长耗时任务把输出打印到文档里监控（MCP 有请求时长限制）。
