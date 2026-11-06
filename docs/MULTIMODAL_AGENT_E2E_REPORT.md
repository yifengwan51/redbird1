# 多模态 Agent 端到端验收

## 结果

**PASS（CACHED_VISION）**：`multimodal_agent.py` 将真实 HTADC 视觉缓存接入主剪辑决策，而非按 HypeCut motion 评分选片。它检索到 ČBF 的两个 `MODEL_PREDICTED shot_attempt`（77s/0.65，81–83s/0.58），构建 67–89 秒窗口以保留十秒进攻铺垫与六秒后续，实际导出 `outputs/agent_multimodal/highlights.mp4`。FFprobe 验证输出为 22.022 秒 H.264 视频。

输出：

- `basketball_events.json`：含 `source_video_id`、`source_model`、`evidence_source=CACHED_VISION` 与模型状态。
- `highlight_plan.json`：明确记录视觉事件而非 signal-only 选择依据。
- `match_recap.json`：逐事件帧时间、视觉说明及不确定性。
- `tool_trace.json`：检索、计划、渲染验证、复盘的可审计轨迹。
- `api_usage.json`：本次新增调用为 0，且保留此前视觉 usage 供追溯。

## 事实边界

视觉模块已经实际接入：选择依据来自 `outputs/semantic_vision_live/basketball_events.json`，不是新的实时视觉调用。两个预测没有人工确认，故不主张命中、得分、球员身份、球权或完整回合；链仅为 `POSSIBLE_CHAIN`。

## Token 优化

历史视觉 usage 为 28,506 tokens，其中 completion/reasoning 分别为 8,945/8,830 与 12,927/12,759，远高于输入 prompt 3,317；主要消耗是代理报告的 reasoning/completion，而不是已报告的输入文本。此次通过缓存新增 **0** tokens/API 成本。未来 live 调用应限制输出/推理预算、继续使用 5 帧 768px 序列和缓存；在没有代理价目时不能精确换算美元。

自然语言交互具备继续开发条件：现有工具轨迹与统一事件 JSON 已可用。下一步应在不覆盖缓存的前提下让 live Agent 仅对未缓存片段调用视觉服务，并把图片 content blocks 纳入会话上下文。
