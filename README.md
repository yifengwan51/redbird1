# MoTrack：篮球高光与智能复盘

MoTrack 是一个**给普通用户使用**的本地篮球视频工具：选一段比赛视频，选择想要的时长和内容，它会自动找出精彩片段，生成可播放、可下载的集锦，并给出一段中文复盘。

所有处理默认在本机完成，素材不需要上传到外部服务。界面和提示均为中文，不需要了解模型、FFmpeg 或命令行。

## 快速开始（推荐）

```bash
./run_motrack_web.sh
```

然后用浏览器打开 `http://127.0.0.1:8765/app/index.html`。

页面是一屏布局：左边是视频，右边是剪辑设置和对话框（屏幕宽度 1360px 以上时并排显示，窄一些时切换成标签页，手机上“开始剪辑”按钮和输入框固定在屏幕底部）。

1. **选比赛**：点顶部的视频卡片。
2. **选风格**：从 6 个预设里选一个，比如燃炸快剪、电影大片、街头嘻哈、复古胶片、黑白经典、原汁原味；配乐、转场、调色会一起设好。需要单独调的放在“细节调整”里。
3. 选时长、画幅（横屏 / 竖屏）和内容，点 **开始剪辑**。剪辑过程中，视频上方会显示进度：看比赛 → AI 看画面 → 剪辑渲染 → 写解说。
4. 剪完可以播放、下载，点剪辑结构条跳到某一段，或者在对话框里继续修改。

服务只绑定本机回环地址，没有登录认证，请勿直接暴露到公网。

## 在手机上用（任何网络）

```bash
./run_motrack_web.sh --remote
```

1. 在电脑上的 MoTrack 页面点右上角 **📱 手机用**，用手机相机扫二维码，就能直接打开并登录。手机用 4G/5G 或其他 Wi-Fi 都可以。**二维码长期有效，可以反复扫**，一直有效到在弹窗里点“重置二维码”为止；重置后，所有已登录的手机都要重新扫码。二维码等于一把钥匙，请不要发给别人。
2. 也可以手动打开弹窗里的网址，输入 8 位**访问口令**（保存在 `.secrets/remote_code`，删除这个文件会生成新口令）。登录状态保留 30 天。
3. 打开后点右上角 **📲 安装**，按页面上的步骤把 MoTrack 放到桌面。添加后有图标，打开时全屏显示。只有 Android 的 Chrome 和 Edge 能一键弹出系统安装框；iPhone、微信、各品牌手机自带的浏览器都要手动添加，页面会按你当前用的浏览器显示具体步骤。**在微信或 QQ 里打开的页面不能安装**，要先点右上角“···”换到浏览器。
4. 手机上能用全部功能：
   - **从相册上传比赛视频**：分片上传，断网后会接着传。服务器会把视频统一转成 H.264、30 fps、长边 1280，并根据手机拍摄方向自动转正，然后自动找出精彩镜头，完成后就能剪。
   - 剪辑、在对话里修改。
   - **分享 / 存相册**：调出手机的分享面板，可以选“存储视频”或发到微信。

原理：服务仍然只监听 127.0.0.1。`tools/cloudflared/cloudflared`（官方版本，已校验 SHA-256）会从这台电脑主动连到 Cloudflare，建立一条临时 HTTPS 隧道，所以不需要在防火墙上开端口。通过隧道进来的请求都要先登录。cloudflared 独立于 MoTrack 服务运行，状态记在 `outputs/cloudflared.json`；**重启 MoTrack 服务时会继续用同一条隧道，网址和二维码都不变**。只有电脑重启、cloudflared 断开或点了“关闭手机访问”之后，网址才会变，到时重新扫一次即可。如果需要永远固定的网址，要用 Cloudflare 账号加自己的域名建一条命名隧道。没加 `--remote` 时，也可以在电脑上的弹窗里点“开启手机访问”。

安全：
- 口令登录每个 IP 每分钟最多尝试 8 次，所有来源合计每分钟最多 30 次。服务端只保存会话令牌的 SHA-256。
- 跨站发起的写请求会被拒绝。
- 二维码、口令和“开启/关闭手机访问”只在这台电脑自己的浏览器里显示和操作。
- 开发模式下所有登录的人都是 VIP，可以用你的 AI 额度。不需要时请在弹窗里点“关闭手机访问”。

## 两种剪辑方式

### 基础剪辑（免费）

- 完全在本机运行（PyTorchVideo X3D-XS / Kinetics-400），视频和文字都不会离开电脑。
- 对话由本地规则理解，支持改时长、改风格、只保留 N 段、找投篮镜头等常用说法。
- 第一次处理某段视频需要扫描，页面会显示进度；之后复用缓存。

### AI 剪辑师（VIP）

- 由真实大模型（默认 `deepseek-v4.1-flash`）理解用户的话、决定怎么剪，剪辑和渲染仍由本地完成，所以时长和风格与基础剪辑一样精确。
- 能听懂更自由的说法：“去掉第 2 段”“只要后半段”“1:17 那球一定要有”“恢复原样”，也会回答问题，做不到的事会直接说明。
- 每次点“开始剪辑”都会附一段 AI 解说。
- **会看画面挑镜头**：点“开始剪辑”时，AI 会先查看得分最高的 8 个候选时刻。每个时刻取前、中、后 3 帧拼成一行，4 个时刻拼成一张图，分两张并行发给视觉模型，判断是什么动作、精彩度 1–5。观众、广告、回放和没有看点的镜头会被跳过，真正精彩的镜头排在前面。对话里说“把没看点的去掉”“哪一球最精彩”时，AI 会先看图再剪。看过的结果缓存在 `outputs/ai_inspect/`，同一个时刻不会重复付费。
- 发给模型的内容：候选时刻列表、当前剪辑结构、最近几轮对话，以及上面这些截图拼图（每张约 768×576）。不会上传整段视频。
- 一次带看画面的 AI 剪辑约 30–60 秒、约 0.5–1 credit。看画面用 `reasoning_effort=minimal`：设成 `none` 时模型几乎不看图，会把所有镜头都判成没看点；设成 `low` 结果正确，但要慢大约 4 倍。
- 成本控制：每轮对话最多 3 轮工具调用（先看后改），只保留最近 4 轮对话，每个会话最多 80 次请求。实测每次请求约 0.05–0.18 credits。模型连不上时会自动改用基础剪辑处理，并告诉用户。

#### 开通 VIP

**开发阶段默认所有人都是 VIP**（`MOTRACK_VIP_MODE` 未设置或为 `dev`）。页面右上角显示“VIP · 开发模式”，打开页面就是 AI 剪辑师。上线前设置 `MOTRACK_VIP_MODE=prod` 关闭这个模式，改为需要兑换码。

`prod` 模式下没有接入支付，VIP 用本地兑换码开通：

- 第一次启动服务时会生成 `.secrets/vip_codes`（权限 600，已在 `.gitignore` 中），里面有一个兑换码。每行一个码，可以自己增删；也可以用环境变量 `MOTRACK_VIP_CODES=码1,码2` 覆盖。
- 用户在页面上点“开通 VIP”，输入兑换码后，浏览器会拿到一个随机令牌，之后的请求都带上它。服务端只在 `.secrets/vip_tokens.json` 里保存令牌的 SHA-256 哈希。删除这个文件即可让所有已开通的浏览器失效。
- 兑换接口限制每分钟最多尝试 8 次。

## 配乐与特效

| 选项 | 取值 | 效果 |
|---|---|---|
| 配乐 | 原声 / 热血（128 BPM 电子）/ 律动（94 BPM 嘻哈）/ 轻快（110 BPM）/ 上传的音乐 | 音乐垫在下面，原声调低到约 30%，开头淡入、结尾淡出 |
| 卡点 | 选内置配乐时自动开启 | 每个剪辑点都落在鼓点上，总时长不变 |
| 转场 | 柔和 / 硬切 / 闪白 | 闪白：切点处短暂白闪 |
| 调色 | 鲜艳 / 电影感 / 复古 / 黑白 | 电影感会加宽银幕黑边，字幕自动上移 |
| 推镜特效 | 开 / 关 | 每段镜头缓缓推进；慢动作回放始终带更强的推镜 |
| 片头标题 | 最多 20 字 | 替换默认的“MoTrack 高光” |
| 画幅 | 横屏 16:9 / 竖屏 9:16 | 竖屏输出 720×1280，裁切位置跟着画面里的动作移动，字幕位置避开短视频 App 底部的界面 |

**剪辑连贯性**：
- 片段之间用真正的交叉溶解（闪白风格用白场过渡），过渡点正好落在剪辑点上，总时长不变。原来每次切换都会先黑一下，黑场占成片的 16–25%，现在接近 0。
- 同一个镜头里相隔很近的两段会合并成一段，避免画面跳一下。
- 精彩的片段分到的时长更长，节奏不会每段都一样。
- 片段的开头或结尾如果只夹带了另一个镜头的几帧，会把这几帧裁掉。镜头切换点用 ffmpeg 场景检测得到，缓存在 `outputs/lightweight/shots_<视频>.json`。

- 内置配乐由 `integrations/music.py` 在本地用 numpy 合成（鼓、贝斯、和弦），没有版权问题，首次使用时生成并缓存到 `outputs/music/`。
- 上传音乐支持 MP3 / M4A / AAC / WAV / OGG / FLAC，单个最大 30MB、时长 3 秒到 15 分钟，会先用 ffprobe 校验。上传的音乐不做卡点，因为不知道它的节拍。
- 对话里可以说“加热血配乐”“换一首”“去掉音乐”“做成电影感”“复古一点”“加特效”“标题改成‘街球之夜’”。

## 高光时长与剪辑方式

生成时选择的目标时长会真正作用到输出视频上：

- 成片不再取“一段连续长窗口”，而是按候选强度挑选多个精彩片段，重新组接成真正的多片段集锦。
- 只要原片够长，请求 20 秒就会输出 20.0 秒；请求 60 秒就输出 60.0 秒。渲染完成后还会做一次精确时长校正，避免编码取整造成明显偏差。
- 如果目标时长超过原片长度，页面会禁用超长的时长按钮并把输入框上限设为原片长度；通过聊天或 API 请求更长时长时，会返回 `duration_clamped` 状态和中文说明，例如“原片只有 20.5 秒，无法生成 30 秒；已按全片时长生成 20.5 秒的精华版。”
- 每一个片段都记录来源时间（`start_time`/`end_time`）和成片时长（`output_duration`），网页下方的“本次剪辑结构”胶片条会按比例展示，点击即可跳到成片对应位置。

可选的剪辑风格：

| 选项 | 取值 | 效果 |
|---|---|---|
| 节奏 | `tight` / `standard` / `relaxed` | 紧凑快剪用更多短片段；标准节奏兼顾动作完整度；舒缓节奏给进攻留出铺垫和余韵 |
| 转场 | `fade` / `cut` | 淡入淡出在切口处做短黑场；硬切保持节奏干脆 |
| 动作字幕 | `captions` | 左下角显示动作名称与来源时间，片头显示标题 |
| 慢放回看 | `slow_motion` | 重播评分最高的片段，0.55× 慢放，约占用 3–5 秒成片时长 |

本地 Agent 也理解这些说法，例如“做一个 15 秒紧凑集锦，加慢放回看”“改成硬切、不要字幕”。已有集锦时，只改风格（“改成硬切”“不要慢放”）会保持时长不变并重新渲染；“保留 3 段”会在后续改风格、改时长时继续生效。慢放回看是对已有片段的重播，不计入片段数。

## HypeCut-only

HypeCut 候选来自 `outputs/real/<video>/default.json`，这是正常流程生成的主计划。旧版本读取 `sports-broadcast.json`，在 Doug 素材上会得到空结果；现在已经修复，并会在主计划缺失时回退到该视频可用的最完整计划。

HypeCut 只表示“画面/音频变化明显”，不代表识别出了投篮或进球，结果需要回看确认。

## 运行产物

- `outputs/lightweight/latest_<video>.json`：本地轻量分析缓存
- `outputs/lightweight_agent/<session>/highlight_plan.json`：本地 Agent 剪辑计划
- `outputs/lightweight_agent/<session>/highlights.mp4`：生成的集锦
- `outputs/lightweight_agent/<session>/tool_trace.json`：工具调用轨迹
- `outputs/web_jobs/<job>/highlights.mp4`：智能 Agent 生成的任务视频
- `outputs/real/<video>/default.json`：HypeCut 主候选计划

网页中的“技术详情”可以查看候选分数、验证状态和原始运行信息；普通使用不需要展开。

## 命令行（进阶）

```bash
# HypeCut 基线
./run_motrack.sh baseline inputs/cbf_3x3_tour.mp4

# 本地轻量：分析 + 生成 20 秒投篮高光
.venv_lightweight/bin/python run_lightweight_agent.py cbf '生成投篮高光 20秒'

# 只运行或复用本地分析
.venv_lightweight/bin/python run_lightweight_agent.py cbf --analyze
```

完整 LLM Agent 会发起真实计费请求，必须显式批准；密钥只经环境变量或项目内 `.secrets/htadc_api_key` 读取：

```bash
./run_htadc_agent.sh inputs/game.mp4 --allow-api
```

API 配置：

- `MOTRACK_API_BASE_URL`：OpenAI 兼容端点，默认内网 `http://sub2api.adc-ingress.aeroht.net/v1`
- `MOTRACK_API_MODEL`：默认 `deepseek-v4.1-flash`
- `MOTRACK_API_KEY`：优先环境变量，否则读取 `.secrets/htadc_api_key`
- `MOTRACK_ALLOW_INSECURE_HTTP=1`：仅限可信内网；非回环 `http://` 默认被拒绝
- `DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL`、`MOTRACK_PYTHON`：可选覆盖

启动脚本只为当前进程注入 `tools/ffmpeg/bin`，不会修改系统 PATH。密钥不会写入文件或日志。

## 安全与边界

- 输入路径必须位于项目目录内。
- 上传接口仅接受 MP4/WebM，单文件上限 200MB。
- 所有事件都是模型推测，不能当作已确认的比赛事实。
- 没有人工标注时，Precision、Recall、F1 均为 `UNVERIFIED`。
- Kinetics-400 的原始 softmax 不是校准后的篮球事件概率，也不验证进球/未进、抢断、篮板、球员或回合。

## 测试

```bash
/home/ht/miniforge3/envs/vlm/bin/python3.12 -m unittest discover -s tests -v
```

测试覆盖事件 schema、源视频边界、允许工具名单、工具调用上限、session/path 防穿越、明文 HTTP 端点拦截、视觉模型输出校验，多片段集锦的时长、来源边界、慢放回看和剪辑风格校验，聊天指令解析与多轮再剪辑（`tests/test_intent.py`）。`tests/test_render_e2e.py` 用 FFmpeg 合成一段 40 秒视频做真实渲染，校验成片时长误差不超过 0.05 秒；缺少项目内 FFmpeg 时自动跳过。`tests/test_vip_ai.py` 覆盖兑换码、令牌、限流，以及 AI 剪辑师的参数处理（去掉第几段、保留、撤销、非法值）。AI 剪辑师的真实模型测试需要显式开启，会产生少量计费请求：`MOTRACK_LIVE_TESTS=1 MOTRACK_API_BASE_URL=... MOTRACK_ALLOW_INSECURE_HTTP=1 python -m unittest tests.test_vip_ai`。

## 项目结构

- `web/backend/app.py`：本地 Web API
- `web/frontend/index.html`、`app.css`、`app.js`：中文用户界面（纯 HTML/CSS/JS，无外部依赖；旧版页面备份在 `outputs/backup/`）
- `integrations/llm_agent.py`：VIP AI 剪辑师（大模型决策，本地执行）
- `integrations/vip.py`：VIP 兑换码与令牌（开发模式默认全员 VIP）
- `integrations/music.py`：内置配乐合成、上传音乐校验、混音
- `integrations/remote.py`：手机访问（口令、会话、一次性二维码、cloudflared 隧道）
- `integrations/uploads.py`：上传视频（分片、转码、分析）
- `web/frontend/manifest.json`、`sw.js`、`login.html`、`icons/`：添加到主屏幕和手机登录
- `integrations/lightweight.py`：本地 X3D 分析、计划、渲染和轻量 Agent
- `integrations/lightweight_v2.py`：V2 审计视图与 HypeCut/V1/V2 对照
- `integrations/motrack_agent.py`：视觉事件 schema 校验
- `motrack_chat_optimized.py`：LLM Agent 对话入口
- `hypecut_upstream/`：未修改的 HypeCut 上游
- `tests/`：离线测试

更多报告：

- [轻量模型报告](docs/MOTRACK_LIGHTWEIGHT_AGENT_REPORT.md)
- [Lightweight V2 质量审计](docs/MOTRACK_LIGHTWEIGHT_QUALITY_V2.md)
- [Web 交互修复记录](docs/MOTRACK_LIGHTWEIGHT_WEB_FIX.md)
