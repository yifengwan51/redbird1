# MoTrack Lightweight 本地 Agent 报告

## 范围与复用

本轮是对既有 MoTrack 的增量扩展。未重新克隆或修改 `hypecut_upstream/`；其当前提交为 `7dafc9d`，继续提供 `scene_change`、`motion`、音频/ROI 信号、候选区间及导出能力。项目内 FFmpeg/FFprobe 继续负责实际渲染和验证。已有 DeepSeek、真实视觉缓存、历史结果及网页未被覆盖。

项目根目录本身没有 `.git`，因此无法在该目录创建本轮 Git 提交；`hypecut_upstream/` 仍是独立上游 Git 工作树。工作区的既有未提交内容保持原状。

## 本地模型与隔离

- 模型：PyTorchVideo **X3D-XS**，Kinetics-400 预训练。
- 官方模型入口：[PyTorch Hub X3D 文档](https://github.com/pytorch/hub/blob/master/facebookresearch_pytorchvideo_x3d.md)，代码：[facebookresearch/pytorchvideo](https://github.com/facebookresearch/pytorchvideo)。PyTorchVideo 许可证为 Apache-2.0。
- 权重：官方 `https://dl.fbaipublicfiles.com/pytorchvideo/model_zoo/kinetics/X3D_XS.pyth`；SHA-256 `6dafc96144c88f800b190d2cb179ff69b8fd48c40afd4deca6c1e61f76fdfe86`，29.4 MB。
- 类别表：官方 SlowFast Kinetics 映射；SHA-256 `00c6a6afcc5a121287419e8ae4075bd591b0bb816d04fb7720d526f04024e1a2`。
- 环境：项目内 `.venv_lightweight`（`--system-site-packages`，仅安装 `pytorchvideo==0.1.5` 及其依赖）；复用现有 `torch 2.13.0+cu130`，未改动 Conda、CUDA、Docker 或系统 PATH。
- 缓存：`.cache/torch/` 与 `.cache/lightweight/`，均在项目内且应保持不提交。

X3D-XS 是通用 Kinetics 分类器。它没有被训练或校准为本项目的投篮命中/未命中、抢断、篮板、球员、球队或球权识别器，因此本实现绝不把其输出升级为人工真值。

## 新增处理流程

`integrations/lightweight.py` 实现统一事件 Schema、X3D 推理、融合以及确定性 Agent：

1. 读取已有 HypeCut sports-broadcast JSON。
2. 每 8 秒全片采样一个 1.6 秒连续帧窗口；对 HypeCut 区间额外按 2 秒密集采样。
3. X3D-XS 对 4 帧输入作 Kinetics-400 Top-5 分类。
4. 命中篮球相关标签后写出候选；`shooting basketball` 只写为 `shot_attempt` + `MODEL_PREDICTED`，其余写为 `basketball_action_candidate`。
5. 保留 Top-5、原始 softmax、帧时间戳、HypeCut 原因、模型/版本与定位方法；原始分数明确标记为**未校准**。
6. 轻量 Agent 采用规则解析与状态机：`INTENT_PARSED → EVENTS_RETRIEVED → PLAN_CREATED → RENDER_COMPLETED → OUTPUT_VERIFIED → TASK_COMPLETED`。它复用本项目 FFmpeg 和 FFprobe，而不调用在线模型。

支持的工具轨迹名称为 `get_video_info`、`search_events`、`create_highlight_plan`、`update_highlight_plan`、`render_highlights`、`verify_render`、`generate_recap`。所有 Lightweight 轨迹的 `initiator` 都是 `CONTROLLER`，不会伪装成 LLM Function Calling。

## 统一接口与网页

保留既有 FastAPI 与单一网页，新增 `mode=lightweight`：

- `GET /api/v1/capabilities`：报告两种模式及 Local X3D 限制。
- `GET /api/v1/videos/{id}/events?mode=lightweight`：统一事件 Schema。
- `POST /api/v1/highlights`、`POST /api/v1/chat`：相同 API，根据 `mode` 选择 LLM 或本地 Agent。
- `GET /api/v1/artifact`：仅允许 `outputs/lightweight*`、`outputs/web_jobs`、`outputs/web_chat` 下的 `.mp4/.json`，拒绝路径遍历。

网页 `http://127.0.0.1:8765/app/index.html` 只有一套播放器、事件时间轴、聊天框和运行面板；模式选择不传递 API key。Lightweight 面板显示本地模型/无云端 Token 的实际语义，LLM 原有接口仍存在。

## 真实运行结果（无云端 API）

| 视频 | 时长 | HypeCut-only 段数 | X3D 窗口 | 合并候选 | 模型加载 | 推理总耗时 | 每视频分钟 | GPU 模型增量 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ČBF 3x3 Tour | 156.423s | 3 | 52 | 31（23 个 `shot_attempt` 候选、8 个普通篮球动作候选） | 1.079s | 15.349s | 5.888s | 15,442,944 bytes |
| Doug McDermott | 20.48s | 0 | 3 | 3（均为 `shot_attempt` 候选） | 1.071s | 1.535s | 4.497s | 15,442,944 bytes |

ČBF 的可复现缓存为 `outputs/lightweight/latest_cbf.json`，Doug 为 `outputs/lightweight/latest_doug.json`；每次真实扫描还保留带时间戳的独立 JSON，不覆盖历史运行。HypeCut-only 与融合版仅可比较候选数、时间分布和计算成本，不能据此声称准确率提升。

轻量 Agent 多轮真实验证（ČBF）：

- “生成投篮高光 20秒”→ 建立计划、实际 H.264 MP4 FFmpeg 输出、FFprobe 验证，首次输出 17.8178s。ČBF 当前本地 MP4 的 ffprobe 只有视频流，因此导出也不虚构 AAC 音频流。
- 在同一会话中“缩短到15秒”→ 更新原计划、重新实际渲染，输出 `outputs/lightweight_agent/58774c6a3ae2/highlights.mp4`，FFprobe 时长 **15.015s**、视频编码 H.264。
- “解释这段视频”→ 生成证据边界明确的复盘；不宣称投篮命中。

Doug 也完成本地 Agent 的实际渲染：`outputs/lightweight_agent/validation-doug/highlights.mp4`，3.603604s。它较短是因为可用的连续候选窗口本身只有约 3.6 秒，并非虚构填充。

## 验收与安全

- A/B：ČBF 与 Doug 均实际加载 X3D、分析真实本地视频，结果如上。
- C/D/E/G：ČBF 在同一 Lightweight 会话完成检索、计划、渲染、缩短和 FFprobe 验证。
- F：Web API 实测返回 31 条 ČBF Lightweight 事件，并通过网页同一接口提供本地模式。
- 页面验证证据：`GET /app/index.html` 返回 HTTP 200；本地输出通过受限 `/api/v1/artifact` 下载返回 HTTP 200（8,576,014 bytes），下载文件再次经项目 FFprobe 读到 15.015000s H.264 视频流。当前执行环境没有可用浏览器自动化/Node 运行时，因此记录 HTTP 与 FFprobe 证据，未伪造浏览器截图。
- H：`run_summary.json` 写入 `cloud_api_calls: 0`；此路线不读取 HTADC 密钥、不开 HTTP 模型请求、没有云端 Token。
- I：LLM mode 的 `/capabilities` 和缓存事件端点在本轮修改后仍可用；为遵守“本轮只开发轻量路线”，没有再次发起付费 DeepSeek 请求。此前的 LLM 成功产物保持不变。
- J：两模式均通过同一视频、事件、聊天、高光、计划和工具轨迹接口返回；Lightweight 明确没有虚假 API usage。
- 安全：`/api/v1/artifact?path=../.secrets/htadc_api_key` 实测返回 HTTP 403；前端不含密钥；不提供任意 shell 或任意路径读取入口。

## 当前限制与后续评测

`shooting basketball` 是通用数据集类别的模型预测，不是视频中确定发生的投篮。所有输出都为 `MODEL_PREDICTED`，没有 `HUMAN_VERIFIED`；因此 Precision、Recall、F1、Coverage 和“优于 HypeCut”的结论均为 **UNVERIFIED**。尤其不得把高分 `dunking basketball` 视为真实扣篮。

后续可接入 [PL-NBA](https://github.com/holhouse/PL-NBA-Dataset)：其仓库提供 JSON 标注，说明视频需要自行取得或通过作者给出的受限渠道取得；资料声明 CC BY-NC 4.0、仅限科研，且原比赛视频另受权利限制。本轮未下载任何 NBA 视频或数据集。只有将它的对应视频与标注按本项目 `source_video_id/event_type/start_time/end_time/verification_status` 接口导入后，才能做有效的时间容差匹配与 Precision、Recall、F1 评测。
