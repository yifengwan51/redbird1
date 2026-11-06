# 篮球语义验证

## 根因（以实际记录为准）

真实 `tool_trace.json` 记录了六次 `get_evidence_frames`，每次只把本地 JPEG 路径、时间戳和“UNVERIFIED”文本作为 tool result 返回。`FunctionLoop` 随后把该 JSON 文本回传模型；没有任何 message 的 content 包含 `image_url` / `input_image`，也没有 base64 图像。因此 DeepSeek 没有实际看到视频图像。`basketball_events.json` 和 `match_recap.json` 的全部 UNVERIFIED 由这个事实导致，不是阈值过滤丢弃了模型识别结果；轨迹中也不存在模型输出的具体篮球事件。

## 连续帧正例候选

已生成 `outputs/semantic_validation/doug_sequence.jpg`（8–16s）与 `cbf_sequence.jpg`（75–83s）及各五张原帧。前者可见球场动作与后段反应；后者在约 79 秒可见腾起球员和篮球。它们只记录为 `SIGNAL_ONLY` 审核候选，不能从中断言命中、抢断、快攻、身份或比分。

`semantic_candidates.json` 明确保存时间、帧证据、空身份和 UNVERIFIED 状态。待密钥可用时，应将同一序列以 OpenAI-compatible Chat Completions 的 `image_url` data URL content 发送给 `deepseek-v4.1-flash`，并把有证据的结果写为 `MODEL_PREDICTED`；绝不自动升为 `HUMAN_VERIFIED`。

## 检索与链

当前“投篮”“抢断”检索正确返回空：没有 MODEL_PREDICTED 或 HUMAN_VERIFIED 数据。链仍为 POSSIBLE_CHAIN，因为只有时间邻近性，没有球权证据。人工在审核页确认后，才能计算 Precision、Recall、F1、Coverage。

## API

本轮未新增 API 消耗：当前会话未设置 `MOTRACK_API_KEY`。既有 HTADC usage 不包含图片请求，故不能将其称为多模态语义测试。
