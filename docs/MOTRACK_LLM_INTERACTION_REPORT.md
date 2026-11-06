# LLM 自然语言交互验收

## 实际运行

使用 `deepseek-v4.1-flash` 对 ČBF 视觉缓存执行了四轮自然语言会话：生成投篮集锦、缩短到 15 秒、解释片段、询问是否命中。会话历史、真实 tool trace 和 usage 均在 `outputs/agent_chat/`。模型正确检索到两个 `MODEL_PREDICTED shot_attempt`，并在最后一轮明确拒绝把它们写成命中：现有证据不能确认结果。

## 结果与重要限制

真实模型创建/修改了计划（最终为两个 vision 事件、2 秒前后文、15 秒上限）。模型在该会话没有自行调用 render/verify；这是 Function Calling 规划缺口，不能宣称完整闭环。随后同一已批准本地工具以模型计划实际渲染并 ffprobe 验证 `highlights.mp4`，时长 10.018 秒（可用两事件上下文只有约 10 秒，少于上限并非失败）。

模型会话发出 15 个请求、共 69,386 tokens，远超成本目标；未再发起请求。原因是每轮最多 8 次 tool-loop 与模型多次无效 search（例如 `shot` 而非 `shot_attempt`）。后续必须将每轮上限降到 2、把事件类型枚举返回给模型，并在有计划后强制 render/verify 工具步骤。

缓存命中正常：没有新增视觉图片上传或视觉 API 调用。事件仍为 MODEL_PREDICTED，不存在 HUMAN_VERIFIED 或已命中结论。

## 运行入口

```bash
./run_motrack_chat.sh inputs/cbf_3x3_tour.mp4
```

输入 `exit` 退出。该脚本自动使用项目密钥文件；真实调用仍应先检查预算。
