# MoTrack Web MVP

## 技术栈与结构

本地 FastAPI + 原生 HTML/CSS/JavaScript，无新增依赖。后端位于 `web/backend/app.py`，前端位于 `web/frontend/index.html`，只监听 `127.0.0.1:8765`。统一接口提供 VideoInfo、视觉事件、复盘、后台剪辑 job、受控媒体资源、能力信息及 Agent chat；`lightweight` 明确为未实现。

## 已验收

- `GET /api/v1/health` 和网页均返回 HTTP 200。
- ČBF 原视频、已有 15 秒高光均由受限媒体接口提供；路径遍历请求返回 404，不能读取密钥。
- 时间轴读取真实 ČBF 两个 `MODEL_PREDICTED shot_attempt`（77s/0.65、81–83s/0.58），点击会跳转原视频。
- 网页触发 `POST /highlights` 后台任务 `job-662dd0fb`，生成独立目录 `outputs/web_jobs/job-662dd0fb/`，FFprobe 验证为 10.018 秒 H.264。
- 网页真实 chat 已调用 HTADC，并返回“没有 made/missed 证据、无法确认命中”的模型文本；会话产物独立存于 `outputs/web_chat/`。

## 安全和边界

前端不含密钥。后端只读项目内 `.secrets/htadc_api_key` 并仅在用户点击发送时调用模型；打开页面、查看历史或生成缓存高光均不调用 API。上传仅允许 MP4/WebM、200MB 以内、保存到 `inputs/uploads/`，且明确说明未自动接入完整分析。所有媒体路径均使用白名单目录与名称校验。

## 启动/停止

```bash
cd /home/ht/motrack/tiqu1
./run_motrack_web.sh
# 浏览器打开 http://127.0.0.1:8765/app/index.html
```

按终端 Ctrl+C 停止。当前限制：聊天每次仍可能产生 HTADC 费用；上传后的完整 HypeCut/视觉流水线未启用；lightweight 模式只是预留接口，未实现。
