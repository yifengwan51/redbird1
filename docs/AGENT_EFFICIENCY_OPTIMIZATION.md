# Agent 效率优化回归

## 对比

| 指标 | 原会话 | 优化后真实会话 |
|---|---:|---:|
| HTADC 请求 | 15 | 4 |
| total tokens | 69,386 | 13,553 |
| 无效检索 | 3（shot/made_basket/score） | 0（类型归一化后使用 shot_attempt） |
| 视觉图片重传 | 无 | 无（均使用缓存） |
| 输出 | 10.018s | 15.000s |

优化后保留了真实 `deepseek-v4.1-flash` 决策。LLM 发起 `search_events` 与 `create_plan`；控制器在计划合法后自动调用 `render_highlights`、`verify_render`，二者在 `tool_trace.json` 中明确为 `initiator=CONTROLLER`，不伪装为模型 function call。

## 状态机

计划创建后自动进入 `PLAN_CREATED → RENDER_COMPLETED → OUTPUT_VERIFIED → TASK_COMPLETED`；只有 ffprobe 成功后才写入完成状态。最终 MP4 为 `outputs/agent_chat_optimized/highlights.mp4`，时长 15 秒 H.264。

## 对话正确性

四轮真实输入均保持同一视频和视觉缓存上下文。模型解释为两个 `MODEL_PREDICTED shot_attempt`，并在“是否命中”问题中明确称结果 unknown，没有生成得分、球员或球队事实。

## 局限

代理未返回可验证单价，无法精确换算美元费用。`reasoning_effort=low` 被作为兼容请求参数传递，实际是否生效不能仅从 token 数确认；但总 token 已显著下降。控制器自动完成渲染确保可靠性，但模型仍不直接发起 render/verify，这一点通过轨迹透明记录。
