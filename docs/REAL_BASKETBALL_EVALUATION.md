# 真实篮球素材离线评测（未调用 API）

## 素材与授权

| 素材 | 原始文件 | 来源/作者 | 许可证 |
|---|---|---|---|
| Doug McDermott | `inputs/original/Doug_McDermott.ogv` | Wikimedia Commons；Nick Lokamas；2014-01-28 | CC BY 3.0 |
| ČBF 3x3 Tour | `inputs/original/CBF_3x3_Tour_Usti_nad_Labem.webm` | Wikimedia Commons；Honza Nový；2013-06-28 | CC BY 3.0 |

原始文件均保留；转换版本为 `inputs/doug_mcdermott.mp4` 与 `inputs/cbf_3x3_tour.mp4`。两者的探测 JSON 位于 `outputs/diagnostics/`。原始页面明确将前者描述为 game-winning shot，将后者描述为 3x3 basketball game；详细来源与许可链接见请求中的 Wikimedia 页面。

## HypeCut 结果

| 视频（时长） | 配置 | 候选数 | 候选时间（秒） | 主触发信号 |
|---|---:|---:|---|---|
| Doug（20.5s） | sports-broadcast | 0 | — | 无突出信号 |
| Doug（20.5s） | sports-field | 1 | 10–20 | audio_transient |
| Doug（20.5s） | default | 1 | 10–20 | roi_activity |
| ČBF（156.4s） | sports-broadcast | 3 | 43–61, 71–99, 106–122 | scene_change |
| ČBF（156.4s） | sports-field | 5 | 24–38, 49–63, 71–95, 106–122, 141–155 | motion |
| ČBF（156.4s） | default | 6 | 29–35, 53–61, 74–83, 89–99, 110–117, 146–153 | scene_change |

`outputs/real/cbf/default_highlights.mp4` 已由 FFprobe 验证为 45.056 秒 H.264/AAC MP4。所有 JSON 均保存于 `outputs/real/`。

## 结论与局限

这证明真实篮球文件可被分析、候选可生成且可导出 MP4；不证明高光语义识别成功。短 Doug 片段的 `sports-broadcast` 空结果与另两配置的候选，均不足以确定检出质量。ČBF 的候选以镜头切换/运动为主，尚未逐帧人工标注为“精彩进攻”。因此 Precision、Recall、F1 和 Clip Coverage 全部标记 **UNVERIFIED**，不伪造人工真值。素材太短，也不能代表完整比赛。

## Agent 状态

本轮未调用 DeepSeek。现有离线测试覆盖工具白名单、调用上限与时间边界；真正的 Mock Function Calling 端到端循环仍待实现，不能声称已验收。
