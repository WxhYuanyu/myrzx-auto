# myrzx-auto

牧羊人之心（Shepherd's Heart / myrzx）日常自动化骨架。

这是一份**新写的** Windows 桌面自动化项目，只看画面、用鼠标点击，不读取游戏内存，也不绕过反作弊。设计上借鉴了「先找窗口 → 稳定截图 → 识别页面 → 点击并确认画面变化 → 失败回到安全页 → 日志可读」的分层思路，但代码全部原创，不依赖 ok-script，也不是 YES-BD2 的分支。

游戏本身是约 9:16 的竖屏手游，没有官方 PC 客户端。默认按 **MuMu 安卓模拟器** 查找窗口（标题和类名可配置）。

## 当前范围

做「每日委托 · 喳喳布林入侵」这条已实走验证的完整链路：

1. 阿格莱恩大地图（若停在南赛拉姆则先下滑）→ 点击 **王城莉莉托斯**
2. 城内节点图 → 点击 **协会**
3. 协会室内 → 点击右下角 **委托**
4. 驯养师协会委托中心 → 点击 **喳喳布林入侵**
5. 任务详情 → 点击 **接收**，再用卡片右上返回关闭详情和列表（等关窗动画），然后 **离开** 协会
6. 回到城内 → 点击右下 **探险**
7. 关卡选择图 → 点击带 **1-3** 字样的旗帜
8. 莉莉托斯近郊 1-3 → 点击左下角 **小孩** 头像（不要点边缘气泡）
9. 剧情对话 → 右上 **跳过剧情**（会直接进入战斗）
10. 战斗中 **不点击**，轮询直到 **战斗胜利**，再点 **触摸继续**；若有战后剧情再跳过
11. 回到 1-3 后点右上带绿勾的 **任务卷轴** → 在任务日志点该委托标题 → 在详情中下部点 **完成** → 在 **获得物品** 上点继续

接取之后如果出现尚未收录的中间页，会先跳过，等到能识别的画面再继续。任何阶段都不会点「扫荡」。

尚无图形界面，也没有安装包或模拟器自动安装。

## 环境

- Python 3.11+
- 依赖：`opencv-python-headless`、`numpy`、`pillow`
- Windows 上枚举窗口 / 截图 / 真实点击额外需要 `pywin32`

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate
pip install -r requirements.txt
# Windows 额外：
pip install -r requirements-windows.txt
pip install pytest
```

## 运行测试（Linux 与 Windows 均可）

视觉函数都是纯函数：输入图片，输出框和标签。测试使用 `tests/fixtures/screens` 里的早期裁切图，以及 `tests/fixtures/walkthrough` 里的 1080x1920 实走截图，不依赖 Windows API。

```bash
python -m pytest
```

## Dry-run（默认，不会点击）

对实走截图按顺序规划完整路径：

```bash
python main.py --dry-run
```

也可以只分析一张图或另一个文件夹（例如旧的 01–09 裁切图）：

```bash
python main.py --dry-run tests/fixtures/walkthrough/13_stage_1_3_npc.png
python main.py --dry-run tests/fixtures/screens
```

## 在 Windows 上对接 MuMu

默认查找逻辑：

- 顶层窗口标题优先包含 **MuMu模拟器** 或 **MuMu安卓设备**（覆盖「MuMu模拟器12」、旧版「MuMu模拟器」、以及 MuMu 5.0 的「MuMu安卓设备」等）。
- 类名参考：`Qt5156QWindowIcon`、`Qt5QWindowIcon`（只作提示，不作为唯一条件）。
- 找到可见主窗口后，对**渲染子窗口**截图和点击，而不是带工具栏的完整外壳：
  - MuMu 12：`MuMuPlayer`
  - 旧版 MuMu：`NemuPlayer`
  - MuMu 5.0：`MuMuNxDevice`
- 如果同时出现更新器等类似 Qt 窗口，会优先标题匹配上述关键词、客户区更大的那个。

请先列出实际窗口，以便锁定精确标题和类名：

```bash
python main.py --list-windows
```

真实点击**默认关闭**。只有在 Windows 上并且显式加上 `--live` 时才会发送输入。当前版本的 `--live` 仍需先用 `--list-windows` 核对窗口；状态机已覆盖本条委托全程，完整点击循环要等窗口标题确认后再接上。

标题或类名若有出入，可改 `src/config.py` 里的关键词。其他模拟器（雷电、夜神等）也可以改同一处配置，文件里留有标题示例。

## 项目结构

```
myrzx-auto/
  main.py
  src/config.py             # 窗口标题提示、超时、比例、路径
  src/window.py             # Windows 下查找 MuMu 窗口；其他系统明确报错
  src/capture.py            # 客户区截图；测试可注入静态图
  src/interaction.py        # 点击 + 确认回调；非 Windows 安全桩
  src/vision/               # 多尺度模板匹配、场景分类、气泡对应、可选 OCR 接口
  src/tasks/daily_commission.py
  assets/templates/         # 从用户截图裁切的局部模板 + manifest.json
  tests/fixtures/screens/   # 早期已知页面（01–09 等裁切图）
  tests/fixtures/walkthrough/  # 1080x1920 实走全程
  docs/daily_commission_flow.md
```

OCR 目前是可插拔接口（默认空实现），后续可以接入中文 OCR，与模板匹配并列使用。

## 还需要你提供的信息

详见 [docs/daily_commission_flow.md](docs/daily_commission_flow.md)。简要：

- 在 Windows 上运行 `python main.py --list-windows` 的完整输出（锁定你这台 MuMu 的标题/类名）
