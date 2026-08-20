# Warframe 赋能组合包收益计算器

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

获取 Warframe Market 的 PC Cross Play 满级赋能近 48 小时成交数据，按洛德赋能组合包分类，计算包含“分解为荧尘后继续投入原组合包”的长期收益，并生成 Excel。

## 使用 Windows ZIP

从 GitHub Releases 下载 `Warframe-Arcane-Return-Updater-Windows-x64.zip`，完整解压后双击 `Warframe赋能收益表更新器.exe`，不需要安装 Python。不要只把 EXE 单独移出解压目录。

1. 打开程序；程序不会自动联网。
2. 点击“更新并生成表格”。
3. 等待价格抓取、收益计算和工作簿检查完成。

默认输出文件为：

```text
解压目录\Warframe-Arcane-Return-Updater-Windows-x64\outputs\daily_arcane_return\赋能收益表_最新.xlsx
```

也可以在程序中点击“更改…”选择其他目录。缓存、CSV、JSON和错误日志保存在：

```text
%LOCALAPPDATA%\WarframeArcaneReturnCalculator
```

## 源码文件

仓库只保留运行和重新构建 Windows 文件夹版 ZIP 必须的文件：

- `arcane_updater.py`：Windows 图形界面和完整更新流程。
- `warframe_arcane_prices.py`：市场抓取、成交量筛选、组合包概率及无限回收计算。
- `build_arcane_workbook.py`：生成并检查 Excel 工作簿。
- `requirements.txt`：运行源码所需依赖。
- `requirements-build.txt`：构建 EXE 所需依赖。
- `arcane_updater.spec`：PyInstaller 文件夹模式打包配置。
- `build_exe.ps1`：Windows 一键构建脚本。
- `.gitignore`：排除缓存、输出、虚拟环境和构建产物。
- `README.md`：使用、构建和计算方法说明。
- `LICENSE`：MIT 开源许可证。

## 从源码运行

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe .\arcane_updater.py
```

## 构建 Windows 文件夹版 ZIP

在 Windows PowerShell 中运行：

```powershell
.\build_exe.ps1
```

构建结果：

```text
dist\Warframe-Arcane-Return-Updater-Windows-x64.zip
```

构建脚本使用独立的 `.build-venv`，不会修改日常运行环境。ZIP 内保留完整运行时目录，避免单文件版每次启动时自解压。构建产物默认没有代码签名。

## 计算口径

### 近 48 小时平均价

读取 `/v1/items/{slug}/statistics` 的 `statistics_closed.48hours` 满级记录：

```text
48h 加权均价 = Σ(小时 wa_price × 小时 volume) / Σ(小时 volume)
```

该数值是历史成交量加权平均价，不是当前最低挂单价。

### 市场计价筛选

满足下列任一条件时改按分解荧尘循环再投资计价：

- 最近一个已结算自然日的满级成交量低于 10；
- 日成交量在 10–20（含边界），且满级 48 小时均价低于 80 白金；
- 近 48 小时没有有效满级成交记录。

市场可售赋能的未升级等价单价为“满级均价 ÷ 升满所需数量”；R5 需要 21 个，R3 需要 10 个。

### 同包无限回收

每包使用 200 荧尘并产出 3 个未升级赋能。分解所得荧尘只继续购买产生它的同一组合包。

若直接市场期望为 `A`，每包平均回收量相当于 `B` 个新包，则：

```text
V = A + BA + B²A + … = A / (1 - B)
```

## 数据来源

- [Warframe Market API](https://docs.warframe.market/docs/api/overview/)
- [Warframe Wiki Module:Arcane/data](https://warframe.fandom.com/wiki/Module:Arcane/data)

组合包奖池与权重维护在 `warframe_arcane_prices.py` 的 `PACKS` 常量中。本项目与 Digital Extremes、Warframe Market 无隶属关系。

## 许可证

[MIT License](LICENSE)
