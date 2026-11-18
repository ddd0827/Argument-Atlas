# 设计笔记：这个项目是怎么来的

## 1. 起点

最初的任务是：在 GitHub 上找一个 AI 应用项目，学习它的做法，再独立做一个新项目，只学思路，不照搬。

我选择的研究对象是 [abi/screenshot-to-code](https://github.com/abi/screenshot-to-code)：一个把截图、设计稿或视频转成 HTML/Tailwind/React/Vue 代码的开源应用。根据项目 README、[DeepWiki 前后端通信](https://deepwiki.com/abi/screenshot-to-code/3.1-frontend-backend-communication) 与 [架构总览](https://opendeep.wiki/abi/screenshot-to-code/architecture/overview)，它大致是这样工作的：

- 前端 React + Vite + TypeScript，后端 FastAPI；
- 通过 WebSocket 流式生成代码，消息带类型：`chunk`、`status`、`setCode`、`variantComplete`、`variantError` 等；
- 后端用 middleware 串成 pipeline：`WebSocketSetup → ParameterExtraction → StatusBroadcast → PromptCreation → CodeGeneration → PostProcessing`，共享一个 `PipelineContext`；
- 支持一次生成多个变体（variants），可以跨模型并行；
- 有 provider 抽象，并内置 `MOCK=true` 的假流式模式，方便无 Key 开发和演示。

## 2. 学到的三个抽象原则

1. **结构化产物优先于散文**：参考项目最终交付的是可运行的代码；本项目交付的是有 schema 的论证图。两者都先定义“产物长什么样”，再让模型去填。
2. **把等待变成可理解的过程**：参考项目用 typed events 告诉前端“在调用哪个模型、哪个变体完成了”；本项目用阶段事件 + 逐字流式追问，把一次长请求拆成用户能理解的动作。
3. **模型层要可替换**：参考项目支持多家模型与 Mock；本项目也把 `DeepSeekProvider` 与 `MockProvider` 放在同一接口后面，业务代码不感知供应商。

另外两条工程习惯也值得保留：

- 密钥、模型名、模式等配置只留在服务端；
- 用 Mock 模式保证“没有 Key 也能演示、测试不依赖付费接口”。

## 3. 刻意没有照搬

| 维度 | screenshot-to-code | 论点地图 |
| --- | --- | --- |
| 解决的问题 | 截图 / 设计稿 → 代码 | 文字 → 论证结构 |
| 前端 | React + Vite 构建链 | 原生 ES Modules，无构建 |
| 传输 | WebSocket + middleware 管线 | `fetch` + NDJSON |
| 核心数据 | 代码变体、文件、版本 | 主张 / 论据 / 假设 / 反驳 / 追问 / 谬误 |
| 输出 | 可运行的页面 | 可阅读、可追问的论证地图 |
| 持久化 | 项目与版本管理 | SQLite：分析 + 按节点的对话 |
| 交互重心 | 并排比较多个生成结果 | 就某一个节点深入交锋 |
| 后端结构 | middleware pipeline | 单条 service 流程 + provider 抽象 |

本项目不是 fork，没有复制参考项目的源代码。提示词、数据模型、前端、SQLite schema、评估集都是围绕本项目需求独立写的。

## 4. 为什么做“论证地图”

常见的 AI 阅读工具会给出摘要或“这篇文章讲了什么”。但摘要解决不了更实际的问题：

- 作者到底主张什么？
- 哪些是证据，哪些只是未经说明的前提？
- 一个理性反对方会怎么反驳？
- 哪句话值得继续追问？

论证地图把这些问题映射成节点和连线，并把“追问”做成节点级动作。它不追求替用户下结论，而是让用户更容易自己判断。

## 5. 产品与工程的几个选择

- **核心主张是虚拟节点**：不放进 `nodes`，但允许用 `node_id: "thesis"` 追问；数据模型更简单，交互更自然。
- **一屏三栏**：左支撑、中主张、右阻力；这比力导向图更可读，也更适合中文长句。
- **两阶段拆解**：先拿完整 JSON，再画图；地图的 id/parent 必须整体一致，不能边生成边画。
- **节点级追问**：服务端从数据库重新装配节点上下文，客户端不能伪造；上下文包含整张地图与原文引用。
- **Mock 是正式功能**：它让离线演示、单元测试和评估不依赖外部服务；UI 明确显示“演示模式”。

## 6. 工程呈现形式的参考

在项目**呈现与交付形式**上，我参考了同目录下 `smartdesk-ai`（SmartDesk AI）的组织方式：

- README 的“问题 → 亮点 → 快速开始 → 架构 → 评估 → 测试 → 真实联调 → 部署 → 安全 → 许可”结构；
- 冻结评估集、自动生成评估报告、把失败与修复写进 README；
- `docs/architecture.md`、`docs/demo-script.md`、`docs/deployment.md`、`docs/eval-report.md` 的文档分层；
- Dockerfile / Compose / Nginx / GitHub Actions 的交付形态；
- 主动写清“已实现”与“尚未实现”的边界。

只借鉴了这些**形式**。SmartDesk 的业务（售后客服、RAG、工具调用、工单系统）与本项目的论证分析无关；本项目没有使用它的代码、提示词、数据或业务逻辑。

## 7. 评估驱动的两次修复

真实评估不是形式主义，它直接改变了实现：

1. **输出预算**：第一次 10 题 live 评估只有 6/10 成功，4 题在 4096 tokens 处被截断。把 `max_tokens` 提高到 8192，收紧节点数与 detail 长度后，10/10 成功。
2. **重复 JSON**：一次响应在一个对象后又补了一段 JSON，`json.loads` 报 `Extra data`。解析器改为取第一个可解析对象，复测通过。

这两次修复说明：评估集不需要很大，但必须可复现、能指出具体失败原因。

## 8. 参考

- [abi/screenshot-to-code · GitHub](https://github.com/abi/screenshot-to-code)
- [DeepWiki: screenshot-to-code 前后端通信](https://deepwiki.com/abi/screenshot-to-code/3.1-frontend-backend-communication)
- [DeepWiki: screenshot-to-code 架构总览](https://opendeep.wiki/abi/screenshot-to-code/architecture/overview)
- [DeepSeek API 文档](https://api-docs.deepseek.com/)
