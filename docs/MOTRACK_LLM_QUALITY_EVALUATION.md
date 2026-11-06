# MoTrack 大模型高光质量评测准备

## 现状

真实工程已验证：HypeCut 候选、HTADC DeepSeek 多模态视觉、事件缓存、Function Calling、FFmpeg 输出和 ffprobe 验证均已完成。视觉事件仅为 `MODEL_PREDICTED`；没有人工真值，因此不能报告准确率。

## 人工审核

运行 `python3 quality_review.py` 后打开 `outputs/quality_review/review.html`。页面并列 ČBF 原视频与最新 15 秒高光，另有 Doug 原视频；每个模型事件显示视频 ID、时间、置信度和状态。可选择 correct/incorrect/type_error/boundary_issue，录入遗漏事件，然后保存到浏览器或下载 `human_review.json`。浏览器安全模型不允许网页直接覆写项目文件；将下载的 JSON 放入审核归档即可复现评测。

## 评测规则

人工事件和预测事件须同类型且时间区间在 2 秒容差内才匹配。Precision=正确预测/预测数；Recall=正确预测/(正确预测+遗漏)；F1 为调和均值；Coverage=人工事件被高光时间线覆盖的比例。另统计错误、遗漏、重复、平均起止时间误差、高光时长和人工填写的无意义时长比例。任一人工标注未完成时所有指标为 **UNVERIFIED**。

## 统一接口

审核包 `events.json` 的每项保留 `source_video_id,event_type,start_time,end_time,confidence,verification_status,evidence,source_model`；不同视频独立标识。这可作为后续大模型与轻量模型公平比较的共同输入，且 Ground Truth 只来自 `human_review.json`，绝不使用 DeepSeek 预测。
