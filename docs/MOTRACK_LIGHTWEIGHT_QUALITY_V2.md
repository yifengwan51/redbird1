# MoTrack Lightweight Agent V2：候选质量与排序审计

## 结论先行

V2 已完成本地真实运行、三路对照、FFmpeg 导出和网页候选可视化，但**没有证据表明它的篮球事件准确率高于 V1**。它的价值是让 X3D 的原始输出、时序处理和排序依据可审计，并把明显过宽的 V1 `shot_attempt` 映射收紧为更保守的 `MODEL_PREDICTED` 候选。

X3D-XS 是 Kinetics-400 通用动作分类器，不是投篮检测/命中判定模型。所有结果仍不是人工真值；Precision、Recall、F1、Coverage 均为 **UNVERIFIED**。因此 V2 没有替换网页默认 Lightweight V1，网页高级选项中显式提供 V1、V2、HypeCut-only 对照。

## X3D 推理审查

审查对象：`integrations/lightweight.py` 与新增 `integrations/lightweight_v2.py`。

| 核查项 | 结果 |
|---|---|
| 权重 | 项目缓存内官方 PyTorchVideo Hub `X3D_XS.pyth`；V2 实际成功加载。 |
| 模式 | `.eval()` + `torch.inference_mode()`。 |
| 图像通道 | OpenCV BGR 明确转换为 RGB。 |
| 空间预处理 | `/255`、mean `[.45,.45,.45]`、std `[.225,.225,.225]`、short-side 182、center crop 182。 |
| 时间输入 | V2 使用 4 个均匀位置，覆盖 X3D-XS 的 `4×12/30fps=1.6s` nominal clip；审计保存实际 frame timestamp、输入帧数及 tensor shape。V1 保持旧抽帧，保证历史对照不变。 |
| 类别映射 | 使用官方 Kinetics class-name JSON；`logit` 和 `softmax_score` 分开保存。 |
| 分数含义 | V1 的 `raw_model_score` 历史字段实际是 softmax 概率；V2 明确标为 `softmax(logits)`，不称作校准置信度。 |

ČBF 的全部 52 个窗口已经写入：[raw_window_predictions.json](/home/ht/motrack/tiqu1/outputs/lightweight_quality_v2/raw_window_predictions.json)。每行包含窗口、四帧时间戳、Top-5 label/logit/softmax、X3D 输入、单窗推理耗时、HypeCut 关联、V2 初始类型及最终合并 ID。

## 为什么 V1 有 23 个 `shot_attempt`

V1 将**只要出现在 Top-5 的** `shooting basketball` 标签映射成 `shot_attempt`。它没有区分这个标签是 Top-1 还是极低分 Top-5，也没有单独记录 logit/softmax。ČBF 23 个 V1 shot 分数范围为 **0.007075–0.332924**；其中很多只是一般篮球画面中的低分通用类别。

此外，52 个扫描窗口由 8 秒全片扫描和 HypeCut 候选段内 2 秒密集扫描构成。V1 在不同时间相邻候选间只按较窄规则合并，因此同一连续比赛活动能留下多个候选。这不等于 23 次被验证的投篮。

V1 没有把 HypeCut motion/scene signal 明确升级为语义事件；但 V1 的宽松 Top-5 映射在与高运动片段叠加时，确实容易产生过多“疑似投篮”。

## V2 时序、去重与映射

V2 配置保存在候选 JSON：

- `shooting_min_softmax=0.12`：仅达到该**明确、可配置、未校准**门槛的 `shooting basketball` 形成 `shot_attempt` 候选；不是准确率阈值，也未宣称最优。
- `basketball_min_softmax=0.08`：其它篮球类别形成更保守的 `basketball_action_candidate`。
- 同类型候选只有在 window overlap IoU ≥ 0.25 或相邻间隔 ≤ 1.0s 时合并；不同类型不强行合并。
- 每个合并事件保留 `source_window_ids`；原始窗口反向记录 `final_event_id`。

ČBF V2：52 窗口中 7 个初始 `shot_attempt` 窗口、33 个一般篮球活动、12 个 UNKNOWN；40 个原始动作候选按时序合并为 21 个事件，合并比例 47.5%。其中最终为 5 个 `shot_attempt`、16 个一般篮球动作候选。V2 没有把其他类（例如 `dunking basketball`）自动写为真实扣篮，也不产生 made/missed/steal/rebound 真值。

V2 五个保守 shot 候选是 59.8–61.368s、75.2–78.768s、89.2–92.768s、104.0–105.568s、120.401–121.969s；它们仍然只是模型候选，必须通过原视频或后续标注核验。

## 透明高光排序

V2 每个事件保存以下可见分项：

```text
final_ranking_score = 0.70 * visual_action_relevance
                    + 0.25 * hypecut_signal
                    + 0.05 * temporal_support
```

- 视觉相关性：V2 选择的 Kinetics softmax，未校准。
- HypeCut：已有 segment score，独立保存其 scene/motion 原因。
- 时序支持：同一事件的来源窗口数，封顶为 1。

这些权重是透明的工程初值，**没有真值数据时不可宣称最优**。排序贪心选择最高分候选，并拒绝上下文区间重叠，保留动作前后 2 秒上下文、每段至少 3 秒、边界均经源视频时长校验。HypeCut scene change 或 motion 只影响其自身分项，不能单独证明精彩或投篮。

## 真实三路对照（目标 15 秒）

| 视频 | 方法 | 候选数 | 最终片段数 | 推理窗口/耗时 | 峰值 GPU 记录 | 渲染状态与时长 |
|---|---|---:|---:|---|---:|---|
| ČBF | HypeCut-only | 3 | 3 | 无 X3D | 0 | PASS，15.015s H.264 |
| ČBF | Lightweight V1 | 31 | 3 | 52 / 15.349s（历史缓存） | 15,442,944 bytes（历史模型增量记录） | PASS，15.015s H.264 |
| ČBF | Lightweight V2 | 21 | 3 | 52 / 13.915s | 68,890,624 bytes（本次 PyTorch peak） | PASS，15.015s H.264 |
| Doug | HypeCut-only | 0 | 0 | 无 X3D | 0 | `NO_CANDIDATES`，不伪造视频 |
| Doug | Lightweight V1 | 3 | 3 | 3 / 1.535s（历史缓存） | 15,442,944 bytes（历史模型增量记录） | PASS，15.015015s H.264/AAC |
| Doug | Lightweight V2 | 3 | 3 | 3 / 0.419s | 68,890,624 bytes（本次 PyTorch peak） | PASS，15.015015s H.264/AAC |

注意 V1 的 GPU 字段是模型加载增量，V2 的字段是 PyTorch 峰值分配，测量口径不同，不能直接比较显存优劣。

产物根目录：[outputs/lightweight_quality_v2](/home/ht/motrack/tiqu1/outputs/lightweight_quality_v2)。其中包含 requested canonical audit、候选、V2 计划、比较汇总、比较页及 ČBF V2 MP4；各视频子目录再保留互不混用的 `hypecut/v1/v2` 结果。对比页：[comparison.html](/home/ht/motrack/tiqu1/outputs/lightweight_quality_v2/comparison.html)。

## 网页与 Agent

现有网页未复制页面；Lightweight 模式新增“候选对照”高级选择器：V1、V2、HypeCut-only。候选分析折叠面板从真实 JSON 展示候选 ID、时间、类型、X3D/HypeCut/融合分数、状态和来源窗口；点击候选跳转源视频。不同 variant 使用独立缓存，不混用事件。

本地 Agent session 保存 `candidate_version`，并把版本写入 `run_summary.json` 与工具轨迹。V2 回归实际完成：检索疑似投篮 → 生成投篮高光 → 缩短到 10 秒 → 复盘 → 导出；复用已生成 V2 JSON，不重新执行 X3D。最终导出经 FFprobe 为 H.264、5.605600 秒（目标为“最多 10 秒”，源候选上下文更短）。

Chrome 端到端验收在隔离端口运行当前代码：网页选择 Lightweight V2 后显示 21 条候选、候选面板正确显示 V2 ID/来源窗口；点击生成得到实际 MP4，播放器 `readyState=4`，Console 无 JavaScript exception、Network 无 404。全程无 HTADC/DeepSeek 请求。

## 后续客观评测接口

有效 Precision/Recall/F1 必须使用同视频同时间轴标注。后续可将 PL-NBA 的合法取得视频与标注适配为：`source_video_id/event_type/start_time/end_time/verification_status`，再按明确时间容差执行匹配。PL-NBA 仓库目前可提供标注信息，但视频获取与非商业许可需要单独遵守；本轮未下载数据集或将预测当标签。

## 是否可升级为默认版本？

**否。** V2 在可审计性、保守映射和去重方面优于 V1 的工程实现，但没有人工真值或匹配数据集证据证明事件精度、召回或高光质量更优。当前默认保持 V1；V2 作为显式高级对照/本地 Agent 选择提供，等待真实标注评测后再决定默认策略。
