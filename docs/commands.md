# 怎么运行

所有真实点击的命令都要在项目根目录执行，并用项目里的虚拟环境，不要用系统 Python。

```powershell
cd E:\myrzx-auto\myrzx-auto-main
.\.venv\Scripts\python.exe main.py <参数>
```

不写 `--live` 时默认只识别画面、打印计划，不会点击。`--shop`、`--claim` 都必须和 `--live` 一起用，不能单独使用，也不能互相搭配。

查看全部参数：`.\.venv\Scripts\python.exe main.py -h`

## 常用命令

| 要做的事 | 命令 |
| --- | --- |
| 买金币商店里的目标商品 | `.\.venv\Scripts\python.exe main.py --live --shop` |
| 按高 / 中 / 低扫城做每日委托 | `.\.venv\Scripts\python.exe main.py --live` |
| 查看扫城顺序（不点击） | `.\.venv\Scripts\python.exe main.py --list-quests` |
| 六次委托都做完后一起领奖 | `.\.venv\Scripts\python.exe main.py --live --claim` |
| 只做一条指定委托 | `.\.venv\Scripts\python.exe main.py --live --quest 换换口味` |
| 只识别、不点击 | `.\.venv\Scripts\python.exe main.py --dry-run` |
| 列出 MuMu 窗口标题和类名 | `.\.venv\Scripts\python.exe main.py --list-windows` |

加 `-v` 或 `--verbose` 会打印更详细的日志。

## `--live --shop` 金币商店

在任意一座能看见「商店」的城里运行即可，不必锁定北赛拉姆；已经停在金币商店页面也可以直接跑。

程序会点城里地图上的「商店」（不是右上背包），再点右下「金币」，在清单里找目标商品，只点同一行的「购买」。确认弹窗里的商品名对上才点「是」。买空是指可购数量变为 `0/n`（不一定是 `0/2`，只有 1 份就是 `0/1`）或「购买」变灰。清单翻完还没有的会跳过并说明。

当前目标：

- 可疑的果汁
- 翡翠之梦
- 魔铁矿

不会点「购买全部」「兑换」「时装」「氪金」。

## `--live` 每日委托扫城

不写 `--quest` 时，从图 1 起按地区顺序：先做完所有高级，再从头扫一遍做中级，最后同样再扫一遍做低级。一天最多 6 次。跑完单条先不点「完成」。

缺裁切或还没走通的委托会停住并说明，不会瞎点。任何阶段都不点「扫荡」。

「换换口味」接取前会先打开背包「道具」页检查是否有「可疑的果汁」：有才接收，没有就不接。单独用 `--quest` 跑这一条时，没有果汁会停下说明；扫城时会跳过这条，不占用每日次数。

## `--live --claim` 一起领奖

六次每日委托都出现绿勾之后再跑。打开带绿勾的任务卷轴，点每条带绿色完成印章那一行的**标题**（不要点印章本身），再在详情页中下部点米色「完成」，获得物品后触摸继续，直到没有印章。

## `--live --quest 标题` 只做一条

标题写成游戏里的名字，例如：

```powershell
.\.venv\Scripts\python.exe main.py --live --quest 换换口味
.\.venv\Scripts\python.exe main.py --live --quest 仇恨会令我成长
.\.venv\Scripts\python.exe main.py --live --quest “热情”的冒险者
```

两个「保证商路畅通」按地图区分（浪人岬 / 南赛拉姆）。表里的「仇恨令我成长」「热情的冒险者」也会认成游戏标题。未知名称会直接停止，不会编造路线。

已经接取之后如果要从某个阶段接着跑，可以加 `--phase`，例如 `GO_STAGE`。一般不必用。

## `--dry-run` 只规划不点击

对一张图或一个文件夹做识别和路径规划。省略路径时使用 `tests/fixtures/walkthrough` 下的实走截图。

```powershell
.\.venv\Scripts\python.exe main.py --dry-run
.\.venv\Scripts\python.exe main.py --dry-run tests/fixtures/turn_in --quest 仇恨会令我成长
```
