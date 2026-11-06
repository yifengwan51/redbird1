# MoTrack Lightweight Web 交互修复报告

## 范围

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
