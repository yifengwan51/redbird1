# 投篮/进球识别：公开视频验证（2026-11-09）

目的：在接近"固定机位"的公开比赛视频上，检查 `integrations/shots.py`（YOLOX-M 篮球检测模型）能不能找到篮筐、出手和进球。

## 用到的视频

| 视频 | 来源与许可 | 画面 | 结果 |
|---|---|---|---|
| ČBF 3x3 Tour（已有样例） | 项目自带 | 1080p，多机位转播集锦 | 篮筐在 14% 的帧里可见；21 次出手判出 3 次（2 进 1 没进），视觉大模型抽查 3/3 一致 |
| WUHS 女篮训练赛，3 分钟片段 | Internet Archive，CC BY-NC-SA 3.0 | 360p，全场，镜头跟着摇 | 篮筐最高置信度 0.31，没有一帧过线；只找到 4 次出手，全部"看不出" |
| Issaquah 9–10 年级决赛，3 分钟片段 | Internet Archive（社区电视台） | 480p，全场，镜头摇摄/变焦 | 篮筐最高 0.59 但只零星出现；1 次出手，"看不出" |
| TrackID3x3 Indoor（4 段，共约 30 秒） | [open-starlab/trackid3x3](https://github.com/open-starlab/trackid3x3)，Apache-2.0 | 720p，**固定机位**，高处斜俯视 | 球识别很好（最高 0.88）；篮筐几乎为 0（最高 0.006）；投篮姿势几乎为 0 |

测试视频放在 `inputs/eval/`（不进 git）。TrackID3x3 室外长视频约 0.1 GB/分钟，下载速度太慢，未完成。

## 结论

1. **检测模型只在转播画面上可靠。** 它是用 NBA 转播截图训练的。业余比赛、高处固定机位下，篮筐只有十几个像素，形状也和转播里不同，模型认不出来；投篮姿势同理。
2. **球仍然认得很好**（固定机位 0.88），这是后面能用的基础。
3. **把篮筐附近裁出来放大也没用**：720p 画面里篮筐只有约 15 像素，放大不增加细节（测试过 480/320/240 像素裁切，篮筐分数都低于 0.12）。

## 对固定机位的改进方向（未实现）

固定机位下篮筐位置不变，所以不需要每帧去"认"篮筐：

- **篮筐定位只做一次**：用户在画面上点一下篮筐，或者让视觉大模型在一帧上标出来。
- **进球判断改用球的轨迹**：球从篮筐上方进入、从下方离开 = 进球；进入篮筐区域后向上或向侧面弹出 = 没进。球识别已经可靠，这条路可行。
- **出手判断也改用球的轨迹**：球离开球员、向篮筐方向抛物线飞行。

需要一段真实的固定机位比赛视频（有多次出手）来调规则。TrackID3x3 的室内片段太短，基本没有完整的投篮。

## 2026-11-09 更新：换成 OpenHoopVision 的检测模型

调研了约 40 个开源项目后，选用 [OpenHoopVision-core](https://github.com/feifeifei85/OpenHoopVision-core) 的 RF-DETR 篮球检测模型（README 写 Apache-2.0；面向业余和青少年比赛；类别含 ball、rim、ball-in-basket、scorer）。权重核对过 SHA-256 并扫描过 pickle 内容，放在 `models/ohv/`（不进 git）。

**找篮筐和球（篮筐出现在多少帧里，阈值 0.3）**

| 视频 | 新模型 | 旧模型 |
|---|---|---|
| TrackID3x3 固定机位 ×3 | 100% | 0% |
| Internet Archive 高中女篮 | 95% | 0% |
| Internet Archive 青少年联赛 | 96% | 1% |
| ČBF 样例 | 97% | 15% |

**判断进没进**：用常见的单机位做法（锁定篮筐、跟踪连续的球、球从篮筐上方区域落到下方时，看轨迹在篮筐高度处是否穿过篮筐；或连续 2 帧 ball-in-basket）。在 NUS 40 段上，规则和"把篮筐放大后让视觉大模型看"两种方法都只有约 60%，因为：

- 两种独立方法一致认为"进了"、但 NUS 标成"没进"的有 8 段，其中 3 段放大画面已确认确实进了（多半是片段后面的补篮）。NUS 的"没进"标签不可靠，不能当作准确率标准。
- NUS 是转播画面，有镜头切换和慢动作回放，不是我们的场景。

ČBF 样例上，之前人工/视觉大模型确认过的 2 个进球（1:35、2:28 附近）新版本都判为进球；出手从 21 次（18 次看不出）变成 33 次（全部判出结果）。

**速度**：两遍扫描（每秒 5 帧粗扫 + 篮筐附近逐帧细扫）。CPU 约为视频时长的 5 倍；显卡有 2.5GB 空闲时自动用显卡，约快 4 倍。

**还缺**：一段有人工标注的固定机位比赛（几十次出手），才能给出可信的准确率。

## 2026-11-10：用 NBA 官方逐回合记录做的评测

数据：Hugging Face [saveerjain/basketball-events](https://huggingface.co/datasets/saveerjain/basketball-events)（仅限研究使用），勇士 vs 马刺（2016-01-25）这一场。只取片段里恰好有一次投篮的 132 段（进 65、没进 67），每段约 7 秒、720p。标签来自 NBA 官方逐回合记录。评测脚本 `/tmp/eval_bbevents.py`，调参脚本 `/tmp/tune_bbevents.py`，结果在 `inputs/eval/bbevents/`。

**调参方法**：按"投篮方式 × 进/没进"分层，交替分成调参用的一半（69 段）和只打分的一半（63 段）。只在调参那一半上选参数，选好后在另一半上测一次。

| | 找到投篮 | 进没进判对 | 判"进了"时的准确率 | 真正进球的召回率 |
|---|---|---|---|---|
| 原规则（测试那一半） | 61/63 | 77.0% | 29/42 | 94% |
| 新规则（测试那一半） | 61/63 | **80.3%** | 28/38 | 90% |
| 新规则（全部 132 段） | 129/132 | **86.0%** | 61/76 | 94% |

**新规则**：连续 3 帧"球在筐里"且置信度 ≥0.7 才算进；球穿过篮筐高度后，还要继续落到篮筐下方至少 1 个篮筐宽度才算进。

**剩下的错误**：15 个"没进被判成进"。抽查其中 6 个，把篮筐附近放大后让视觉大模型看，6 个都判断为"球穿网而下"。其中 6/15 的片段前后 12 秒内正好有一个进球。所以有一部分很可能是标签和片段错位（片段里拍到的是相邻的进球，或回放镜头），不是检测错误。要确认需要人工看这几段，截图在 `inputs/eval/bbevents/check/`。

**对 ČBF 样例的影响**：命中率从 88%（29/33）变为 70%（23/33）。

### 更正（同日）
上面的"新规则"里，"球穿过篮筐后必须继续落到篮筐下方 1 个篮筐宽度（0.8 秒内）"这一条**有问题**：在 ČBF 样例上把 6 个进球改判成了没进，其中包括之前确认过的 1:35 进球。原因是业余/多机位画面里球进网后常被网和人挡住，0.8 秒内落不到那么低。NBA 测试那一半上它并没有带来额外提升（单独收紧"球在筐里"就能达到同样的 80%）。

**现在的规则**：只保留"连续 3 帧、置信度 ≥0.7 的球在筐里才算进"，下落检查关闭（`DROP_W = 0`）。

| 规则 | NBA 调参那一半 | NBA 测试那一半 | ČBF 进球数 |
|---|---|---|---|
| 原规则 | 87% | 77% | 29/33 |
| 有问题的版本 | 91% | 80% | 23/33（误杀 6 个进球） |
| **现在** | 91% | **80%** | 29/33 |

已加回归测试 `test_slow_or_hidden_drop_after_rim_is_still_made`。

## 2026-11-10 · Evidence + "待确认" flag (calls unchanged)

Inspired by S2M (evidence accumulation, re-check only the uncertain ones). Each
attempt now records evidence: `cross` (crossing offset / rim width), `drop`,
`track` (ball rows from up-zone entry to crossing), `bib` (sum of
ball-in-basket confidences). No outcome changes, so accuracy is identical
(ČBF 29/33, doug 1/2, NBA unchanged).

A through-rim make with `track >= 19` and `cross >= 0.15` is flagged 待确认.
On the 78 NBA clips we call made:

| | truly made | truly missed | wrong rate |
|---|---|---|---|
| flagged | 14 | 10 | 42% |
| not flagged | 48 | 6 | 11% |

The flag catches 10 of the 16 false makes. On ČBF it flags 3 makes (1:11, 1:34, 2:18);
1:34 is the verified make, so flagged shots must stay "made" until a person says otherwise.
Hard-flipping flagged shots was rejected: it would turn 14 real makes into misses.
An automatic VLM re-check was also not adopted: the earlier vision check called
6 of 6 sampled NBA false makes "made", so it would not have fixed them.

Users never judge calls (product decision 2026-11-10); the flag and overrides are internal. An admin-only API (POST /review/correct) writes overrides to in outputs/corrections/<video>.json
outputs/corrections/<video>.json, applied when events are read; use it to build labels, not as a user feature.

## 2026-11-10 · Player numbering (built, not enabled)

Scan v3 keeps player / holder / referee boxes with a torso colour. Shot calls
are byte-identical to v2 on ČBF (33 attempts) and doug (2).
`integrations/players.py` tracks people (overlap + distance + jersey colour,
Hungarian matching, gap stitching), splits teams by 2-means colour, and gives
each attempt to the scorer / holder / nearest person before release.

| clip | people in view | tracks | median track | distinct "shooters" / attempts |
|---|---|---|---|---|
| ČBF (edited reel, cuts) | 6.3 | 146 | short | 24 / 33 |
| wuhs (fixed camera) | 7.9 | 89 | 14 s | 7 / 7 |
| issaquah (fixed camera) | 8.0 | 77 | 11 s | 10 / 11 |

Identity does not hold: one player becomes 8-9 tracks in 3 minutes, so the
same shooter gets different numbers. `players.ENABLED = False` hides the
roster, the 复盘 players row and "只看 N 号" from users. Needed before enabling:
an appearance re-ID model to join tracks across occlusions, then a check of
>= 80% correct attribution with repeat shooters on a fixed-camera game.

## 2026-11-10 · Appearance re-ID (OSNet x1.0 MSMT17) — not enough

Model: OSNet x1.0 / MSMT17 (deep-person-reid, MIT), vendored in
`integrations/vendor/osnet.py`, weights `models/reid/` (sha256 48df972f…,
pickle globals: OrderedDict + tensor storage only). ~17 ms/crop on CPU.
Code: `integrations/reid.py`, `players.merge_identities`.

Split test (truth by construction): 71 long tracks on wuhs + issaquah were cut in
two with a 2 s gap. For each first half, is its own second half the best match
among tracks that start later?

| cue | right |
|---|---|
| appearance only | 17% |
| appearance, same team only | 21% |
| appearance + jersey colour | 45% |
| position continuity + colour | 32% |

Bar was 80%. Cause: people are small (median height 78 px on wuhs, 121 px on
issaquah) and teammates wear the same kit; the street-pedestrian model cannot
tell them apart. Feature stays off (`players.ENABLED = False`).
What could work: higher-resolution fixed camera (1080p+), jersey-number
reading on large crops, or a re-ID model fine-tuned on basketball players.

## Highlight ranking (analysis 3.6)

`integrations/highlight.py` orders made shots by crowd noise (35%), shot distance (30%), scoring streak (20%) and layup (15%). Made shots score 1.25 to 1.75; missed (0.45), unknown (0.5) and X3D moments (at most 1.0) keep their old scores, so the same groups of plays are picked as before. Uncertain makes get no bonus.

Crowd signal: the loudness rise just after the shot compared with the 4 s before it. Percentile of makes against random moments: issaquah 0.63 to 0.89, doug 0.91, wuhs 0.11 and 0.61. With only 6 makes this is weak evidence, so the crowd signal only reorders makes and never decides make vs miss. ČBF has no audio track and is ranked on distance, streak and type only. Re-analysing ČBF gave identical events and outcomes, and the top 5, 8 and 12 picks are all makes, as before.
