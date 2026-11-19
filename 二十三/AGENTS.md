# 二十三（演示版）

一座黄昏小岛，把这几年的经历和「今日小物」每天打印的摆件放在一起。支持本机工作台联动和独立的公网只读演示。

## 目录
- `serve.py`：本机服务，只绑 127.0.0.1。`/data/world.json` 和 `/models/<展品 id>`。
- `demo/`：已脱敏的世界快照和展品模型。人名、群名、学校、公司和账号 ID 均已替换。存在快照时服务直接展示它。
- `tools/build_world_data.py`：从私有的经历汇总和今日小物任务生成 `world.json`（设置 `BIRTHDAY_WORLD_DATA` 时启用）。
- `web/`：无构建的静态页面，`vendor/three/` 是本地 three.js r169（MIT）。
- `assets/`：代码生成的场景小物（GLB）。

## 运行
```
PORT=5232 WORKBENCH_PORT=17868 python3 -I serve.py
```
打开 http://127.0.0.1:5232/ 。「今日小物」按钮会嵌入同级目录的工作台（端口 17868）。

公网发布从仓库根目录运行 `node build-site.mjs`，服务目录为 `public/`。公网卡片只读，本机启动方式见上。

## 边界
- 往 Aholo 只发造型描述，不发人名、原话或聊天内容。
- 卡片编辑只写本机 `data/edits.json`。
