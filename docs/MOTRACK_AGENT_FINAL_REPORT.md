# MoTrack 智能复盘 Agent 验收

## 已核查的真实成果

`outputs/agent_deepseek/` 包含 7 次 `deepseek-v4.1-flash` 请求的 usage、带真实 `tool_call_id` 的轨迹、3 段真实渲染素材和 ffprobe 验证结果。模型实际调用了候选检索、视频信息、候选详情、证据帧、计划、渲染、验证与复盘工具。它没有把运动/转场称为篮球事实：三个选中事件均为 `UNVERIFIED`。

## 本轮交付

- `integrations/recap_agent.py`：证据约束的事件索引、自然语言关键词保护、时间筛选、事件链和关键回合说明。
- `motrack_recap_demo.py`：无需服务即可演示的 CLI。
- `outputs/agent_deepseek/basketball_events.json`：可检索事件。
- `outputs/agent_deepseek/match_recap.json`：事件链与关键回合结果。
- `outputs/agent_deepseek/human_review.json`：人工标注模板。
- `outputs/agent_deepseek/review.html`：本地可打开的审核页，可播放 Agent 导出的 MP4。

## 实际测试（ČBF 3x3 Tour）

| 请求 | 实际结果 |
|---|---|
| 找出所有投篮事件 | `[]`：没有经证据确认的投篮 |
| 找出抢断后的进攻 | `[]`：没有经证据确认的抢断或球权关系 |
| 分析最精彩的一个回合 | 74.567–83.600 秒候选窗口，`POSSIBLE_CHAIN` |
| 关键回合集锦 | 已存在真实 DeepSeek 选择的 `plan-9542430a.mp4`；不重新渲染以避免重复处理 |

Precision、Recall、F1 与 Coverage 为 **UNVERIFIED**，直到人工在 `human_review.json` 中完成标注。当前没有球员/球队身份数据，查询球员会明确为 UNKNOWN，绝不生成姓名。

## 演示

```bash
cd /home/ht/motrack/tiqu1
./motrack_recap_demo.py --build-review
./motrack_recap_demo.py '找出所有投篮事件'
./motrack_recap_demo.py '分析最精彩的一个回合'
xdg-open outputs/agent_deepseek/review.html
```

局限：事件链只按已选候选窗的时间连续性建立；无球权、传球、得分或球员身份的视觉确认，故所有链均为 `POSSIBLE_CHAIN` 而非官方回合重建。
