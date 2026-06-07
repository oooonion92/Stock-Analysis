# Chanlun Sandbox

这是 Stock Analysis 项目的缠论互动沙盘子项目。

## 当前状态

- 本目录已经清理为最小运行包。
- 当前沙盘已验证可运行，访问地址是 `http://127.0.0.1:8765/`。
- 行情数据默认读取 `D:\OneDrive\Stock\details`。
- 当前启动脚本优先使用本目录 `.pydeps`，如果不存在则使用 Codex 自带 Python。

## 核心文件

- `chanlun_sandbox_app.py`: 网页、交互、接口、数据读取和在线同步入口。
- `chanlun_v10_20_core.py`: 缠论底层结构和信号计算核心。
- `启动缠论沙盒.bat`: 双击启动入口，调用保活脚本。
- `停止缠论沙盒.bat`: 按端口 `8765` 停止沙盘服务。
- `start_chanlun_sandbox_keepalive.ps1`: 长驻启动脚本，服务退出后自动重启。
- `start_chanlun_sandbox.ps1`: 单次启动脚本，适合调试。
- `chanlun_sandbox_requirements.txt`: 最小 Python 依赖，目前是 `numpy` 和 `pandas`。

## 常用操作

从项目根目录启动：

```powershell
cd "D:\Projects\Stock Analysis"
.\启动缠论沙盒.bat
```

从本目录调试启动：

```powershell
cd "D:\Projects\Stock Analysis\01_chanlun_sandbox"
.\start_chanlun_sandbox.ps1
```

停止：

```powershell
cd "D:\Projects\Stock Analysis"
.\停止缠论沙盒.bat
```

## 修改指引

- 改界面、控件、API、股票列表、在线同步：优先看 `chanlun_sandbox_app.py`。
- 改笔、中枢、背驰、动量、买卖点判断：优先看 `chanlun_v10_20_core.py`。
- 不要把旧快照、便携版脚本、历史实验引擎重新塞回本目录；需要参考旧资料时看项目 `docs/` 或旧仓库。
- 修改后至少验证首页和股票列表：

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8765/
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8765/api/stocks
```

## 新对话接力提示

如果在新 Codex 对话中继续沙盘，请先阅读：

```text
D:\Projects\Stock Analysis\README.md
D:\Projects\Stock Analysis\01_chanlun_sandbox\README.md
```

然后再根据目标修改沙盘。
