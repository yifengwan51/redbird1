# 环境审计（2026-11-06）

- OS/kernel：Ubuntu 20.04.6 LTS，5.15.0-119-generic。
- GPU：NVIDIA GeForce RTX 5060，驱动 580.126.09，8,151 MiB（检查时空闲 7,008 MiB）。
- Python：系统 `/usr/bin/python3` 为 3.8.10（不适用）；可复用 `/home/ht/miniforge3/envs/vlm/bin/python3.12` 为 3.12.15，并已有 numpy、PyYAML、Pillow、requests、openai。未修改该环境。
- Conda：未在 PATH；uv 0.13.7 在 `/home/ht/.local/bin/uv`。未使用安装或同步命令。
- Git：2.25.1。FFmpeg/FFprobe：均不在 PATH（当前基线执行的阻塞项）。
- 空间：`/home/ht/motrack/tiqu1` 所在卷约 501G 可用。审计时 tiqu1 为空。
- 既有缓存：pip 约 201M，uv 约 15G；其中可见 openai、PyYAML、NumPy 条目。未从缓存或网络安装。

## 下载审计

唯一网络下载是获准的 `https://github.com/Yu-0312/hypecut.git`，位于 `hypecut_upstream/`；提交 `7dafc9d538548225b36d826cb445caf825ca3833`，Apache-2.0。没有下载模型、数据集、视频、Python 包或 Docker 镜像。
