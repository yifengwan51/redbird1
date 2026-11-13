# 本地素材、模型与密钥准备

MoTrack 仓库只包含代码、配置和文档；密钥、模型权重、媒体文件、运行输出和虚拟环境均不进入 Git。这样克隆仓库不会意外取得付费 API 凭据，也不会把受来源/许可约束的数据传播给每位克隆者。

## 一键准备

```bash
git clone git@github.com:yifengwan51/redbird1.git motrack
cd motrack
./bootstrap_motrack.sh --check
./bootstrap_motrack.sh --samples       # 可选：下载两个公开演示素材
./bootstrap_motrack.sh --setup-key     # 可选：只在需要实时 LLM 时配置
./run_motrack_web.sh
```

脚本不会安装系统软件、改动系统 PATH，也不会覆盖已有媒体或密钥。`--samples` 需要已可用的 FFmpeg；优先使用项目内 `tools/ffmpeg/bin/ffmpeg`。

## 可再分发的演示素材

`--samples` 仅下载以下两个 Wikimedia Commons 原始文件，并转码到网页使用的 MP4 路径。下载者须保留出处和署名：

| 文件 | 作者 | 许可 | 官方页面 |
|---|---|---|---|
| Doug McDermott.ogv | Nick Lokamas | CC BY 3.0 | [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Doug_McDermott.ogv) |
| ČBF 3x3 Tour 22.6. Ústí nad Labem.webm | Honza Nový | CC BY 3.0 | [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:%C4%8CBF_3x3_Tour_22.6._%C3%9Ast%C3%AD_nad_Labem.webm) |

其余 `inputs/eval/`、上传素材和历史生成视频不自动下载或发布：它们的来源、许可证或再分发条件不同。BARD、NBA 等评测数据尤其不能混入一般演示下载。

## 模型权重

模型参数不提交到普通 Git：本地缓存约 237 MiB，其中 RF-DETR 权重约 123.5 MiB，超过 GitHub 普通 Git 的 100 MiB 单文件上限。项目会从已记录的官方来源按需下载并在项目内缓存：

- X3D-XS：PyTorchVideo 官方 Hub；首次本地 X3D 分析时下载。
- RF-DETR 篮球检测器：`python -c "from integrations.shots import download_model; download_model()"`，脚本校验 SHA-256。
- OSNet ReID：仅在对应功能启用时由 `integrations/reid.py` 从其记录的官方来源下载。

若项目需要完全离线部署，应由维护者在确认权重许可、Git LFS 配额和分发义务后创建独立的受控模型包；不要将其混入普通代码仓库。

## API 密钥

实时 LLM/VIP 功能读取优先级为：进程环境变量 `MOTRACK_API_KEY`，其次 `.secrets/htadc_api_key`。后者权限为目录 `700`、文件 `600`，并由 `.gitignore` 排除。密钥绝不能放进示例配置、提交历史、网页代码、日志或 GitHub Actions。
