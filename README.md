# Warframe 赋能组合包收益计算器

[![tests](https://github.com/sliuhaob/warframe-arcane-return-calculator/actions/workflows/tests.yml/badge.svg)](https://github.com/sliuhaob/warframe-arcane-return-calculator/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

从 [Warframe Market](https://warframe.market/) 获取 PC Cross Play 市场中所有可升级赋能的满级近 48 小时成交数据，按洛德出售的赋能组合包分类，并计算包含“分解为荧尘后继续投入原组合包”的长期收益。

## 输出内容

程序生成 `outputs/daily_arcane_return/赋能收益表_最新.xlsx`，包含：

- `满级赋能近48小时平均价`：组合包、概率池、日成交量、计价方式、满级均价、分解荧尘、未升级等价单价和单包期望贡献。
- `计算参数`：成交量筛选条件、组合包成本、同包无限回收模型、每个组合包的直接市场期望与最终期望。

同时在系统临时目录保留 CSV 和 JSON 中间数据，便于审计或二次分析。

## 快速使用

### Windows

1. 安装 [Python 3.10+](https://www.python.org/downloads/)，安装时勾选 `Add Python to PATH`。
2. 下载或克隆本仓库。
3. 双击 `更新赋能收益表.bat`。

首次运行会在仓库内创建 `.venv` 并自动安装 `openpyxl`。后续运行直接更新数据，通常需要 2–4 分钟；完成后自动打开 Excel。

### macOS / Linux

```bash
git clone https://github.com/sliuhaob/warframe-arcane-return-calculator.git
cd warframe-arcane-return-calculator
chmod +x update_arcane_report.sh
./update_arcane_report.sh
```

### 命令行

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

python warframe_arcane_prices.py \
  --output arcane_prices.csv \
  --summary-output pack_summary.csv \
  --json arcane_data.json

python build_arcane_workbook.py arcane_data.json report.xlsx
```

查看抓价程序的全部参数：

```bash
python warframe_arcane_prices.py --help
```

常用选项：

- `--min-volume 20`：修改第一层日成交量门槛。
- `--no-crossplay`：排除跨平台订单。
- `--platform xbox`：查询其他平台。
- `--refresh-items`：忽略 24 小时物品目录缓存。

## 计算口径

### 近 48 小时平均价

读取 `/v1/items/{slug}/statistics` 的 `statistics_closed.48hours` 满级记录，将每个小时的 `wa_price` 乘以该小时 `volume` 后求和，再除以总成交量：

```text
48h 加权均价 = Σ(小时 wa_price × 小时 volume) / Σ(小时 volume)
```

这不是当前最低挂单价。

### 市场计价筛选

默认满足下列任一条件时，不按市场价格出售，而按分解荧尘的循环再投资价值计价：

- 最近一个已结算自然日的满级成交量低于 10；
- 最近日成交量在 10–20（含边界），且满级 48 小时加权均价低于 80 白金；
- 近 48 小时没有有效满级成交记录。

市场可售赋能的未升级等价单价为：

```text
满级 48h 加权均价 / 升满所需数量
```

R5 需要 21 个，R3 需要 10 个。

### 同包无限回收

每个组合包使用 200 荧尘、50,000 信用点并产出 3 个未升级赋能。低流动性赋能被分解后，荧尘只继续购买产生它的同一个组合包，后续抽到的低流动性赋能也继续分解。

若某包直接市场期望为 `A`，一包产出的可回收荧尘相当于 `B` 包，则长期价值为：

```text
V = A + BA + B²A + … = A / (1 - B)
```

信用点不折算成白金；每次回收购买仍需要额外支付 50,000 信用点。

## 数据来源与限制

- 商品与成交统计：[Warframe Market API](https://docs.warframe.market/docs/api/overview/)
- 赋能分解荧尘数据：[Warframe Wiki Module:Arcane/data](https://warframe.fandom.com/wiki/Module:Arcane/data)
- 组合包奖池与权重目前维护在 `warframe_arcane_prices.py` 的 `PACKS` 常量中；游戏更新组合包时需要同步修改。
- 本项目与 Digital Extremes、Warframe Market 无隶属关系。
- 程序遵守公开接口的请求速率限制，并在限流或临时错误时退避重试。

## 开发与测试

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
```

GitHub Actions 会在 Python 3.10、3.12 和 3.13 上运行测试。

## 许可证

[MIT License](LICENSE)
