# MoTrack：篮球高光提取与复盘适配层

此项目以未改动的 `hypecut_upstream/` 为上游，MoTrack 代码仅在 `integrations/` 和根目录编排。上游版本：`7dafc9d538548225b36d826cb445caf825ca3833`，许可证 Apache-2.0。

## 状态与限制

项目内 FFmpeg/FFprobe 已部署，HypeCut 已对本地合成 MP4 完成候选分析与 MP4 导出。真实篮球比赛素材尚未提供，因此篮球事件识别质量、真实比赛集锦和复盘均未验证。DeepSeek 不会在未显式加入 `--allow-api` 时发出请求；本项目尚未发起任何 API 调用。

## 运行

将已获授权的 MP4 放入 `inputs/` 后：

```bash
./run_motrack.sh baseline inputs/game.mp4
```

完整 Agent 模式（首次真实计费请求前必须明确取得许可；密钥只经环境变量读取）：

```bash
DEEPSEEK_API_KEY='...' ./run_motrack.sh agent inputs/game.mp4 --allow-api
```

可选环境变量：`DEEPSEEK_BASE_URL`（默认 `https://api.deepseek.com`）、`DEEPSEEK_MODEL`（默认 `deepseek-flash`）、`MOTRACK_PYTHON`。启动脚本仅为当前进程注入 `tools/ffmpeg/bin`，不会修改系统或用户级 PATH。密钥未写入文件、日志或输出。

## 输出约定

- `outputs/clips/candidate_highlights.json`：HypeCut 候选时间线
- `outputs/diagnostics/`：contact sheet、Agent 调用记录
- `outputs/highlights/highlights.mp4`、`highlight_plan.json`
- `outputs/recaps/recap.json`、`recap.html`

执行前会拒绝 tiqu1 以外的输入路径。模型只能看候选抽帧；不得上传整段视频。事件只能在证据支持时分类，未证实情况保持 `unknown`。

## 测试

```bash
/home/ht/miniforge3/envs/vlm/bin/python3.12 -m unittest tests/test_offline.py
```

测试覆盖 schema、源视频边界、允许工具名单和工具调用上限；不等同于真实 API 或真实篮球比赛验收。

## 复盘演示

在已有 DeepSeek 运行结果上创建审核产物并进行无计费检索：

```bash
./motrack_recap_demo.py --build-review
./motrack_recap_demo.py '找出所有投篮事件'
```

审核页是 `outputs/agent_deepseek/review.html`。没有人工或视觉语义证据的事件始终显示为 `UNVERIFIED`。

## 本地 Web MVP

```bash
./run_motrack_web.sh
```

打开 `http://127.0.0.1:8765/app/index.html`。浏览历史结果和使用缓存视觉生成高光不调用模型；点击聊天发送才会调用项目内 HTADC Agent。

## Lightweight 本地 Agent（X3D）

轻量路线是对 HypeCut 的补充，不替换上游 HypeCut：它先复用已有的 `scene_change`、`motion` 等候选时间段，再以低频全片扫描补充候选盲区，并在 HypeCut 区域加密抽取连续帧。模型为官方 PyTorchVideo X3D-XS（Kinetics-400），首次安装/权重都只缓存到项目内的 `.venv_lightweight/` 和 `.cache/torch/`；之后推理不调用 HTADC 或任何在线 LLM。

```bash
# 仅执行或复用本地 ČBF X3D 分析
.venv_lightweight/bin/python run_lightweight_agent.py cbf --analyze

# 确定性本地 Agent：分析缓存 → 计划 → FFmpeg 渲染 → FFprobe 验证
.venv_lightweight/bin/python run_lightweight_agent.py cbf '生成投篮高光 20秒'
```

运行 `./run_motrack_web.sh` 后，在网页顶部将模式切换为 **Lightweight Agent（本地 X3D）**。它和 LLM 模式共享视频、事件、计划、播放器、下载和工具轨迹接口；Lightweight 支持“生成投篮高光”“找出疑似投篮”“缩短到15秒”“查看关键事件”“解释这段视频”“导出视频”等确定性中文命令。

重要限制：Kinetics-400 的 `shooting basketball` 仅产生 `MODEL_PREDICTED` 的**疑似**投篮候选，原始 softmax 不等于校准置信度，也不验证进球/未进、抢断、篮板、球员、球队或完整回合。没有人工标注时 Precision、Recall、F1 均为 `UNVERIFIED`。详见 [轻量模型报告](docs/MOTRACK_LIGHTWEIGHT_AGENT_REPORT.md)。

网页 Lightweight 生成、下载、会话缩短与浏览器验收的修复记录见 [交互修复报告](docs/MOTRACK_LIGHTWEIGHT_WEB_FIX.md)。

Lightweight V2 提供完整 X3D 窗口审计、保守时序合并和 HypeCut/V1/V2 对照；它不是默认版本，也不代表已验证的篮球事件检测准确率。详见 [V2 质量审计报告](docs/MOTRACK_LIGHTWEIGHT_QUALITY_V2.md)。
