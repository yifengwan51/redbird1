# MoTrack Lightweight Web 交互修复报告

## 第三轮：真实多片段集锦、精确时长与剪辑语言

第三轮围绕“看起来像成片、时长说到做到”继续改造本地渲染器和网页工作台：

| 改进 | 之前 | 现在 |
|---|---|---|
| 集锦结构 | 取一段连续源窗口，片段之间的无关画面也会被收进 MP4 | 按候选强度选取多个片段，逐段裁剪、统一画幅、重新组接成多片段 montage |
| 时长准确性 | 依赖单个窗口，请求 20 秒可能只有 10 秒，或受编码取整影响 | 规划阶段按目标时长分配每段输出时长，渲染后再做一次精确校正；实测 5/10/20/60 秒均精确命中 |
| 超出原片 | 静默截断，用户不知道为什么 | 页面按原片长度禁用超长按钮并限制输入；聊天/API 返回 `duration_clamped` 与中文说明 |
| 剪辑语言 | 只有“时长 + 内容” | 新增节奏（紧凑/标准/舒缓）、转场（淡入淡出/硬切）、动作字幕、慢放回看 |
| 可解释性 | 只有一张事件列表 | 新增“本次剪辑结构”胶片条：每段的顺序、来源时间、成片时长、慢放标记，点击可跳转 |
| 视觉与动效 | 旧版单页、信息密度低 | 重新设计深色工作台：渐变片名、分层卡片入场、按钮扫光、评分条、分段控件、开关和响应式布局 |

关键实现：

- `integrations/lightweight.py`
  - 新增 `normalize_edit_style`、`edit_style_from_text`、`duration_meta`。
  - 新增 `build_montage`：候选去重、最短间隔筛选、按相邻事件中点划分可扩展窗口、水位分配每段时长、必要时扩展上下文、可选 0.55× 慢放回看。
  - 新增多片段 FFmpeg 渲染：逐段 trim/变速、1280×720、30 fps、色彩微调、淡入淡出或硬切、左下角动作字幕、片头标题、水印、concat、精确时长校正。
  - `render_plan` 返回 `segments`、`render_mode=multi_clip_montage`、`requested_duration`、`effective_duration`、`source_duration`、`duration_clamped`、`duration_note`、`edit_style`。
  - 本地 Agent 保存 `selected_events`，后续“改成 15 秒 / 紧凑一点”会从完整候选池重新组接，而不是把已裁剪片段当成唯一素材。
- `web/backend/app.py`
  - 缓存视频时长，`/api/v1/videos` 返回 `duration`。
  - 本地与 LLM 高光任务都使用共享的 montage 渲染器，并透传剪辑风格。
  - 聊天接口透传 `edit_style`。
- `web/frontend/index.html`
  - 按原片长度禁用超长时长按钮、限制输入上限并显示说明。
  - 新增节奏、转场、字幕、慢放控件和动态风格提示。
  - 新增胶片条与评分条，完善卡片入场、页头渐变和减少动效偏好支持。
  - 生成后用实际文件时长显示角标，不再四舍五入成整数。

验证结果：

- 时长矩阵：ČBF v1 请求 5/10/20/60 秒 → 5.0/10.0/20.0/60.0 秒；Doug v1 请求 5/10/20 秒 → 精确命中，30/45 秒 → 20.486667 秒并标记 `duration_clamped=True`；Doug HypeCut 10/20 秒 → 10.005/20.011 秒，30 秒 → 20.48 秒并说明原因。
- 对话回归：“生成 30 秒投篮高光”在 Doug 上回复 20.5 秒并解释原片上限；“改成 15 秒，紧凑一点”用完整候选池重新生成 3 个片段 / 15.0 秒。
- 网页 E2E：Doug 的 30/45/60 秒按钮禁用、输入上限 20；本地 20 秒紧凑/硬切/无字幕/慢放生成 4 个片段，胶片条可见；聊天触发时长说明 toast；切回 ČBF 后按钮恢复；Chrome Console 0 个 JavaScript exception。
- 离线测试：27/27 通过；`py_compile` 通过。

## 第二轮用户反馈修复

针对用户实际测试反馈，又完成了一轮修复：

| 用户反馈 | 根因 | 修复 |
|---|---|---|
| 指定 20 秒只生成 10 秒 | 渲染窗口被候选事件的最大结束时间 `+2s` 提前截断 | 新增目标时长窗口选择；本地渲染和 LLM 高光都按请求时长铺满，只有原片不够长时才截断 |
| HypeCut-only 结果无效 | 读取了 `sports-broadcast.json`，Doug 上该文件没有片段；同时“投篮”命令筛掉了 HypeCut 候选 | 改为读取主计划 `outputs/real/<video>/default.json`，缺失时回退到最完整计划；HypeCut 模式不再按投篮类型过滤 |
| 网页不够好看、内容不够好 | 旧页面是开发者向的单页布局 | 重做响应式中文界面：清晰的分步操作、时长快捷按钮、进度状态、播放器、时间轴、中文复盘、对话气泡和折叠的技术详情 |
| Agent 对话格式不好看 | 回复直接塞进一行文本 | 聊天气泡、多行排版、推荐指令、输入中状态和友好的错误提示 |
| 轻量 Agent 能力偏弱 | 只识别少量关键词；旧分析总把低置信度 `shooting basketball` 当作投篮 | 扩展中文意图和时长解析；按最强篮球动作类别排序；4 秒全片扫描；新增扣篮/运球/通用动作候选和更自然的中文回复 |
| 面向专业开发者而非普通用户 | 页面暴露 JSON、模式和候选版本术语 | 默认隐藏技术细节，使用“智能 Agent / 本地轻量”“投篮 / 扣篮”“精彩动作”等用户语言 |

第二轮验证结果：

- 本地分析：ČBF 39 个候选（22 个疑似扣篮、17 个篮球动作），Doug 5 个候选（3 个疑似扣篮、2 个篮球动作），缓存版本 `2.1`。
- ČBF 本地 20 秒请求：输出 20.02 秒。
- Doug 本地 10 秒请求：输出 10.00 秒。
- Doug HypeCut-only 20 秒请求：输出 20.00 秒，不再失败。
- LLM 20 秒请求：窗口 75.0–95.0 秒，输出 20.02 秒。
- 离线测试 22/22 通过。

## 第一轮修复范围

本次仅修复现有 Lightweight Web/本地 Agent 的交互与集成缺陷。没有修改 `hypecut_upstream/`、DeepSeek 已验证的核心 Agent 逻辑、FFmpeg 部署、tiqu2 或任何公司系统环境；未发送 HTADC/DeepSeek 请求。

## 已定位故障与根因

| 故障 | 根因 | 修复 |
|---|---|---|
| 点击“生成高光”后 MP4 404 | `artifact()` 已生成 `/api/v1/artifact?path=...`，播放器刷新再拼接 `?v=timestamp`，使 `?v` 成为 `path` 的一部分 | 使用 `URL`/`URLSearchParams` 统一构造资源地址；现为 `?path=...&v=...` |
| 模式切换后偶尔仍显示 LLM 事件 | 初始 `load()` 的异步响应可能晚于 Lightweight `load()`，旧响应覆盖新 UI | 加入 `loadRevision`，过期请求不再写入 DOM |
| Lightweight 生成请求没有真实任务状态 | `/highlights` 同步阻塞到渲染结束，前端无法区分排队、运行、验证或失败 | Lightweight 改为后台 job，`/jobs/{id}` 轮询真实 `QUEUED → LOCAL_AGENT_RUNNING → OUTPUT_VERIFIED` 状态 |
| 重复点击与失败反馈不清楚 | 前端没有 busy 锁，后端异常只显示类型名 | 生成/聊天期间禁用生成按钮；Agent 返回 `stage/error_type/message/retryable` 结构化失败信息 |
| 本地 Agent 表达覆盖不足 | 仅识别少数字面关键词，且“剪成15秒”在无计划时不能作为首次生成请求 | 增加同义意图、时长/数量提取、会话状态检查、再短一点、导出、复盘和命中不确定性处理 |

## 针对任务 `181dedde9527` 的核验

`outputs/lightweight_agent/181dedde9527/highlights.mp4` 存在，大小 5,274,008 bytes。项目 FFprobe 读取到 H.264 视频流、时长 9.809800 秒。

修复前实测：

- `/api/v1/artifact?path=outputs%2Flightweight_agent%2F181dedde9527%2Fhighlights.mp4` → HTTP 200
- 同一 URL 错误拼接 `?v=1793949593905` → HTTP 404

修复后，浏览器实际生成任务 `lw-b9ddec2a16b0` 使用：

`/api/v1/artifact?path=outputs%2Flightweight_agent%2Flw-b9ddec2a16b0%2Fhighlights.mp4&v=1793950536552`

浏览器媒体 Range 请求返回 HTTP 206，显式下载 fetch 返回 HTTP 200、5,274,008 bytes，播放器 `readyState=4`。

## 修改文件

- `web/frontend/index.html`
  - 统一 `artifactUrl()` / `versionedUrl()`；不再手工拼接查询字符串。
  - 后台任务轮询、busy 锁、完成后 `video.load()`/尝试播放、真实下载地址、友好错误提示。
  - 视频/模式切换清空不属于当前上下文的高光，加入异步加载防竞态。
  - 添加空 data favicon，消除浏览器无关 404。
- `web/backend/app.py`
  - Lightweight `/api/v1/highlights` 使用后台 job；`/jobs/{id}` 和 trace 兼容轻量任务。
  - 保护同一 session 不能跨视频复用；结构化返回本地 Agent 失败信息。
- `integrations/lightweight.py`
  - 规则意图解析覆盖生成、提取、剪辑、检索、缩短、再短一点、复盘、命中询问与导出。
  - 从文本提取秒数与片段数；“缩短到 N 秒”只更新当前计划而不重新扫描视频。
  - 每个实际动作继续记录 `get_video_info`、`search_events`、`create_highlight_plan`、`update_highlight_plan`、`render_highlights`、`verify_render`、`generate_recap` 等轨迹。

## 实际浏览器验收

使用本机 Google Chrome Headless 与 Chrome DevTools Protocol，启动现有 `./run_motrack_web.sh` 后执行：

1. 打开 `/app/index.html`，切换 Lightweight、选择 ČBF：显示 **31** 条 Lightweight 事件。
2. 点击“生成高光”：后台任务完成，播放器地址正确；按钮恢复可点击。
3. 浏览器实际读取 MP4：`readyState=4`，无 `artifact` 404。
4. 点击下载对应的真实地址：HTTP 200，5,274,008 bytes。
5. 输入“缩短到15秒”：复用同一 session 的计划，重新 FFmpeg 渲染并通过 FFprobe；聊天记录明确说明未重新扫描原视频。
6. 输入“这些投篮命中了吗”：正确答复 X3D 不能确认结果，未把 `shot_attempt` 冒充命中。
7. 切换 Doug：原播放器改为 Doug 源视频、旧高光 `src=null`、显示 **3** 条 Doug 事件，未混用 ČBF 数据。
8. Chrome Console 没有 JavaScript exception；Network 没有 404。

## 回归与产物验证

- 新浏览器测试产生：[highlights.mp4](/home/ht/motrack/tiqu1/outputs/lightweight_agent/lw-b9ddec2a16b0/highlights.mp4)，FFprobe：H.264、9.809800 秒。
- Lightweight Agent 命令回归依次执行“找出所有疑似投篮 → 把视频剪成15秒 → 再短一点 → 分析刚刚生成的片段 → 这些投篮命中了吗 → 导出视频”，均产生真实工具轨迹；涉及渲染的步骤实际输出 MP4。
- 原有离线测试：3/3 通过。
- LLM 页面展示的 capabilities 与缓存事件 API 保持可用。本轮未调用付费 DeepSeek API，因此没有新增云端费用。
- 路径限制仍保留；`/api/v1/artifact` 仅暴露批准输出目录的 `.mp4/.json`。

## Lightweight 实际支持的命令

- 生成高光 / 提取精彩片段 / 帮我剪辑这场比赛
- 生成投篮高光 / 找出所有疑似投篮 / 查看关键事件
- 只保留最精彩的三个片段（也支持阿拉伯数字数量）
- 把视频剪成15秒 / 缩短到15秒 / 再短一点
- 分析刚刚生成的片段 / 解释这些事件
- 这些投篮命中了吗（返回证据不足，而不是编造成果）
- 导出视频（已有计划时重新导出并验证）

仍不支持开放式赛事问答、球员/球队身份、投篮命中判定、抢断/篮板真值或完整球权分析；这些不会由通用 X3D 的候选分数替代。
