# MoTrack：篮球高光与智能复盘

MoTrack 是一个**给普通用户使用**的本地篮球视频工具：选一段比赛视频，选择想要的时长和内容，它会自动找出精彩片段，生成可播放、可下载的集锦，并给出一段中文复盘。

所有处理默认在本机完成，素材不需要上传到外部服务。界面和提示均为中文，不需要了解模型、FFmpeg 或命令行。

## 快速开始（推荐）

```bash
./run_motrack_web.sh
```

然后用浏览器打开：

```text
http://127.0.0.1:8765/app/index.html
```

页面里可以：

1. 选择视频（ČBF 3x3 Tour 或 Doug McDermott）。
2. 选择分析方式：**智能 Agent** 或 **本地轻量**。
3. 选择想要的时长（10/15/20/30/45/60 秒，也可以自己输入 5–60 秒）。
4. 选择内容：**投篮 / 扣篮** 或 **全部精彩动作**。
5. 点击“生成高光”，完成后直接播放或下载。
6. 也可以直接和 AI 助手聊天，例如：
   - 生成 20 秒投篮高光
   - 做一个 30 秒精彩集锦
   - 找出所有疑似投篮
   - 缩短到 10 秒
   - 解释这段视频

服务只绑定本机回环地址，并且没有登录认证，请勿直接暴露到公网。

## 两种分析方式

### 智能 Agent

- 使用项目内已缓存的视觉事件来挑选片段。
- 只有点击聊天发送时才会调用已配置的模型。
- 依赖 `outputs/semantic_vision_live/basketball_events.json`；缓存缺失时页面会提示改用本地轻量模式。

### 本地轻量（推荐离线使用）

- 完全在本机运行 PyTorchVideo X3D-XS（Kinetics-400），不调用云端。
- 首次分析需要扫描视频，可能要等一两分钟；之后会复用缓存。
- 三种识别方式：
  - **本地动作识别（推荐）**：识别扣篮、投篮、运球、通用篮球动作。
  - **本地识别 + 审计视图**：保留更完整的候选和评分信息。
  - **HypeCut 画面信号**：只使用画面/音频变化信号，适合快速找精彩镜头。
- 本地模型只给出“疑似”动作候选，不确认是否进球、球员、球队或回合归属。

## 高光时长

生成时选择的目标时长会真正作用到输出视频上：

- 只要原片够长，请求 20 秒就会生成约 20 秒的视频，不再被候选片段跨度压短。
- 如果目标时长超过原片长度，会自动截断到原片长度。
- 本地轻量模式会优先挑选一段连续的精彩区间，再按目标时长取窗口，避免把相隔很远的片段硬拼成一段包含大量无关内容的视频。

## HypeCut-only

HypeCut 候选来自 `outputs/real/<video>/default.json`，这是正常流程生成的主计划。旧版本读取 `sports-broadcast.json`，在 Doug 素材上会得到空结果；现在已经修复，并会在主计划缺失时回退到该视频可用的最完整计划。

HypeCut 只表示“画面/音频变化明显”，不代表识别出了投篮或进球，结果需要回看确认。

## 运行产物

- `outputs/lightweight/latest_<video>.json`：本地轻量分析缓存
- `outputs/lightweight_agent/<session>/highlight_plan.json`：本地 Agent 剪辑计划
- `outputs/lightweight_agent/<session>/highlights.mp4`：生成的集锦
- `outputs/lightweight_agent/<session>/tool_trace.json`：工具调用轨迹
- `outputs/web_jobs/<job>/highlights.mp4`：智能 Agent 生成的任务视频
- `outputs/real/<video>/default.json`：HypeCut 主候选计划

网页中的“技术详情”可以查看候选分数、验证状态和原始运行信息；普通使用不需要展开。

## 命令行（进阶）

```bash
# HypeCut 基线
./run_motrack.sh baseline inputs/cbf_3x3_tour.mp4

# 本地轻量：分析 + 生成 20 秒投篮高光
.venv_lightweight/bin/python run_lightweight_agent.py cbf '生成投篮高光 20秒'

# 只运行或复用本地分析
.venv_lightweight/bin/python run_lightweight_agent.py cbf --analyze
```

完整 LLM Agent 会发起真实计费请求，必须显式批准；密钥只经环境变量或项目内 `.secrets/htadc_api_key` 读取：

```bash
./run_htadc_agent.sh inputs/game.mp4 --allow-api
```

API 配置：

- `MOTRACK_API_BASE_URL`：OpenAI 兼容端点，默认内网 `http://sub2api.adc-ingress.aeroht.net/v1`
- `MOTRACK_API_MODEL`：默认 `deepseek-v4.1-flash`
- `MOTRACK_API_KEY`：优先环境变量，否则读取 `.secrets/htadc_api_key`
- `MOTRACK_ALLOW_INSECURE_HTTP=1`：仅限可信内网；非回环 `http://` 默认被拒绝
- `DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL`、`MOTRACK_PYTHON`：可选覆盖

启动脚本只为当前进程注入 `tools/ffmpeg/bin`，不会修改系统 PATH。密钥不会写入文件或日志。

## 安全与边界

- 输入路径必须位于项目目录内。
- 上传接口仅接受 MP4/WebM，单文件上限 200MB。
- 所有事件都是模型推测，不能当作已确认的比赛事实。
- 没有人工标注时，Precision、Recall、F1 均为 `UNVERIFIED`。
- Kinetics-400 的原始 softmax 不是校准后的篮球事件概率，也不验证进球/未进、抢断、篮板、球员或回合。

## 测试

```bash
/home/ht/miniforge3/envs/vlm/bin/python3.12 -m unittest discover -s tests -v
```

测试覆盖事件 schema、源视频边界、允许工具名单、工具调用上限、session/path 防穿越、明文 HTTP 端点拦截、视觉模型输出校验，以及高光计划与连续渲染窗口的时长适配。

## 项目结构

- `web/backend/app.py`：本地 Web API
- `web/frontend/index.html`：中文用户界面（纯 HTML/CSS/JS，无外部前端依赖）
- `integrations/lightweight.py`：本地 X3D 分析、计划、渲染和轻量 Agent
- `integrations/lightweight_v2.py`：V2 审计视图与 HypeCut/V1/V2 对照
- `integrations/motrack_agent.py`：视觉事件 schema 校验
- `motrack_chat_optimized.py`：LLM Agent 对话入口
- `hypecut_upstream/`：未修改的 HypeCut 上游
- `tests/`：离线测试

更多报告：

- [轻量模型报告](docs/MOTRACK_LIGHTWEIGHT_AGENT_REPORT.md)
- [Lightweight V2 质量审计](docs/MOTRACK_LIGHTWEIGHT_QUALITY_V2.md)
- [Web 交互修复记录](docs/MOTRACK_LIGHTWEIGHT_WEB_FIX.md)
