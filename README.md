# wallet-monitor

![Windows](https://img.shields.io/badge/Windows-10%20%7C%2011-4b8cff?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.8%2B-3776ab?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-67d8c1?style=flat-square)

一个常驻桌面的半透明毛玻璃钱包与 API 用量监视器。默认附带 **BUZZ** 适配器，但界面层并不依赖 BUZZ，可以接入其他余额、账单、配额或积分 API。

![wallet-monitor 使用效果](docs/screenshot.png)

## 功能

- 当前余额、累计消费、总额度与使用率
- 今日增量与近 7 日增量（本地采样）
- 可用模型数量与连接状态
- Windows Acrylic 毛玻璃、高 DPI 自适应
- 始终置顶、任意位置拖动
- 拖到屏幕顶边自动吸附收起，悬停触发条展开
- 多显示器与不同 DPI 坐标支持
- 单实例运行；双击刷新，右键退出

## 快速开始

要求：Windows 10/11、Python 3.8 或更高版本。

```powershell
git clone https://github.com/KyleSun725/wallet-monitor.git
cd wallet-monitor
.\Setup.cmd
notepad .env
.\Start-WalletMonitor.cmd
```

`Setup.cmd` 会创建本地 `.venv`、安装依赖，并在不存在时从 `.env.example` 创建 `.env`。随后将自己的 BUZZ 主 Key 写入 `.env`：

```dotenv
BUZZ_API_KEY=replace-with-your-key
BUZZ_BASE_URL=https://buzzai.cc
BUZZ_REFRESH_SECONDS=300
BUZZ_CURRENCY_SYMBOL=$
```

所有网络请求都直接发往配置的 API。Key 不会显示、写入历史文件或发送到其他服务。

## 不只适用于 BUZZ

窗口只消费一个标准化快照；API 供应商的差异集中在 `load_config()` 与 `fetch_snapshot()`：

```python
{
    "granted": 15.0,      # 总额度
    "used": 11.5,         # 累计用量
    "balance": 3.5,       # 当前余额
    "model_count": 2,     # 可用模型/资源数量
}
```

接入其他服务时，保留 UI 和历史逻辑，只需在 `wallet_monitor.py` 中读取对应环境变量，并让 `fetch_snapshot()` 返回上面的四个字段。例如：

```python
def fetch_snapshot(config):
    payload = get_json("https://api.example.com/v1/billing", config["api_key"])
    granted = float(payload["quota"])
    used = float(payload["spent"])
    return {
        "granted": granted,
        "used": used,
        "balance": max(0.0, granted - used),
        "model_count": len(payload.get("resources", [])),
    }
```

因此它也适合监控云服务余额、代理 API 额度、团队预算、积分池或任何能返回类似数值的 HTTP API。

## 操作

| 操作 | 效果 |
| --- | --- |
| 拖动窗口 | 移动位置 |
| 双击窗口 | 立即刷新 |
| 拖到屏幕顶部 | 吸附并自动收起 |
| 悬停顶部触发条 | 展开窗口 |
| 右键 | 刷新或退出 |

今日与近 7 日增量来自本机 `.wallet-monitor-history.json`，只覆盖开始运行后的采样数据。

## 项目文件

```text
wallet-monitor/
├─ wallet_monitor.py          # UI、历史记录与默认 BUZZ 适配器
├─ Setup.cmd                  # 创建虚拟环境并安装依赖
├─ Start-WalletMonitor.cmd    # 启动桌面组件
├─ requirements.txt
└─ .env.example               # 无真实 Key 的配置模板
```

## 安全

- `.env`、本地历史和窗口位置已加入 `.gitignore`
- 请不要在 Issue、截图或日志中粘贴真实 API Key
- 建议为监控用途创建最小权限、可撤销的只读 Key

## 依赖与许可

界面使用 [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter)，Windows 毛玻璃兼容层使用 [py-window-styles](https://github.com/Akascape/py-window-styles)。项目本身采用 [MIT License](LICENSE)。