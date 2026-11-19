# 今日小物：把每一天打印出来，摆进我的人生小岛

[打开「二十三」小岛](https://life3d.agichuang.com/)

每天从自己的待办和与 Agent 的对话里，选一个值得留下的念头。用 Aholo 做成三维模型，经 Blender 检查、Bambu Studio 切片，再把它打印成一件桌面摆件。小物做完后，会出现在「二十三」岛的展台上，和一路遇到的人、经历过的事摆在一起。

公网演示可以走进岛上、沿时间线飞行、查看展品的 3D 模型和实物照片。小屋、信箱和卡片可浏览。这个仓库包含本机工作台源码和经过脱敏的演示快照。

## 目录

- `二十三/` — Three.js 小岛、演示快照和模型。
- `今日小物/` — 本机工作台，负责记录、构思、模型生成、切片、打印确认和实物照片归档。
- `build-site.mjs` — 生成比赛演示使用的只读网站。

## 运行演示网站

需要 Node.js 和 Python 3。在仓库根目录运行：

```sh
node build-site.mjs
python3 -m http.server 5233 --bind 127.0.0.1 --directory public
```

打开 <http://127.0.0.1:5233/>。Vercel 构建运行同一条 Node.js 命令，发布 `public/`。

## 运行本机工作台

需要 macOS 和 Python 3.11+。在仓库根目录运行：

```sh
cd 今日小物
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
MOODPRINT_DATA="$PWD/demo-data" .venv/bin/python -B app.py --port 17868
```

打开 <http://127.0.0.1:17868/>。工作台提供本机离线样品入口。模型生成、切片和打印的本机配置见 [使用与接入](今日小物/使用与接入.html)。

如需在本机小岛里打开工作台，另开终端，在仓库根目录运行：

```sh
cd 二十三
PORT=5232 WORKBENCH_PORT=17868 python3 -I serve.py
```

打开 <http://127.0.0.1:5232/>。

## 离线测试

```sh
cd 今日小物
.venv/bin/python -B -m unittest discover -s tests
```
