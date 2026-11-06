# MoTrack 本地部署报告

日期：2026-11-06。范围仅为 `/home/ht/motrack/tiqu1`；未使用 sudo、APT、Docker、系统 Python、CUDA 或 DeepSeek API。

## FFmpeg

- 来源：BtbN/FFmpeg-Builds GitHub 固定 Release `autobuild-2026-11-05-12-48`。
- URL：`https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-11-05-12-48/ffmpeg-n8.1.3-34-ga35157abb9-linux64-gpl-8.1.tar.xz`
- Release 校验文件：同一 Release 的 `checksums.sha256`。
- 归档 SHA-256：`1bbd8ff31a24ecbe0714f21e47cc0c4382cc51340c32d5d35fc6fda44e168ab5`（通过）。
- 版本：`n8.1.3-34-ga35157abb9-20261105`；x86_64 ELF，最低 GNU/Linux 4.18.20，在 Ubuntu 20.04 / kernel 5.15 实测可运行。
- 二进制：`tools/ffmpeg/bin/ffmpeg`、`tools/ffmpeg/bin/ffprobe`。启动脚本仅向当前进程与子进程追加该目录至 PATH。
- 占用：`tools/ffmpeg/` 当前约 1.5 GB，含已验证归档、一次失败归档和完整上游解压资料；未清理任何文件。

第一次使用移动的 `latest` URL 的归档校验失败，文件被保留在 `tools/ffmpeg/downloads/` 且从未执行。固定 Release 的首次续传也因执行环境中断而损坏；新文件名的首次自动重试通过校验后才解压。

## 本地验证

| 检查 | 结果 |
|---|---|
| `ffmpeg -version` / `ffprobe -version` | 通过 |
| libx264 编码器 | 通过 |
| HypeCut `profiles --json` | 通过，7 个配置，含 `sports-broadcast` |
| 合成样片生成 | 通过：`inputs/synthetic_test.mp4`，15.0 秒，640×360 H.264 + AAC |
| 输入 FFprobe | 通过，含视频和音频流 |
| HypeCut 分析 | 通过：`outputs/clips/candidate_highlights.json`，1 个候选 |
| HypeCut 导出 | 通过：`outputs/highlights/highlights.mp4`，12.421 秒 H.264 + AAC |
| 输出 FFprobe | 通过；另带章节/数据流是 HypeCut 章节元数据 |
| MoTrack 离线单元测试 | 3/3 通过 |

输出：`outputs/diagnostics/` 中有两个 contact sheet 与基线日志；`outputs/highlights/` 中有 MP4、`highlight_plan.json`、HypeCut JSON 侧车和 EDL。

HypeCut 上游 `contact-sheet` CLI 在此 commit 中会引用未定义的 `args.quiet`。MoTrack 未修改上游源码，而是通过同一上游的公开 Python `contact_sheet` API 生成 contact sheet。

## DeepSeek Agent

已具备环境变量配置、OpenAI 兼容请求封装、超时/重试、使用量记录、图片 data URL 组装、预定义工具 schema，以及本地工具白名单与时间边界校验。当前 CLI 只在 `--allow-api` 和密钥存在时才可能发出请求；本次没有调用 API。实际 Function Calling 循环、视觉判定、复盘 HTML、真实计费和真实篮球素材评估仍未完成验证。

## 运行

```bash
cd /home/ht/motrack/tiqu1
./run_motrack.sh baseline inputs/your_authorized_game.mp4
```

```bash
cd /home/ht/motrack/tiqu1
./run_htadc_agent.sh inputs/your_authorized_game.mp4 --allow-api
```

第二条会触发外部 API，仅在获得单独计费授权后使用。真实篮球验证需要一段已授权、含转播音频的 MP4；合成样片不能证明篮球高光识别能力。
