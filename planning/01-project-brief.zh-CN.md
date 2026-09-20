# 第一步：项目定义与 MVP 范围

状态：启动草案，已对照提供的资料；不是已完成的应用或提交材料。项目名暂定 **ShipCheck — 航运邮件核对工作台**，团队可更名。

## 可以直接发给队友的产品描述

我们开发一个云端航运邮件核对工作台。系统用 AI 将邮件分成五类，只对文件核对请求读取 Shipping Instruction（SI）和 draft Bill of Lading（BL），以 SI 为基准核对七个字段，并列显示两份文件的值、差异与来源。缺少附件、字段不完整或无法可靠读取时，系统交给工作人员复核；工作人员可以修正并重新核对。第一轮先用 JSON 邮件和 TXT 附件跑通完整流程，再扩展复杂文档。

## 要解决谁的问题

用户是处理航运单证的运营人员。他们需要先从混合收件箱找出核对请求，再逐项检查 SI 与 BL。我们的价值是减少漏处理、重复阅读及错误放行，并让每个结论可追溯到文件原文。暂不承诺节省时间百分比或准确率，后续用实际测试测量。

## 来源与约束：不要把聊天建议当成官方要求

| 类型 | 已确认内容 | 依据 |
|---|---|---|
| 官方要求 | AI 是关键组成部分，且实质性使用云基础设施；技术栈自由 | Rules and Regulations，第 1–2 页 |
| 官方业务范围 | 五类邮件；仅核对请求继续提取和比较；SI 为参考；不能判断时交给人 | Use Case，第 1 页 |
| 官方字段 | shipper、consignee、notify_party、port_of_loading、port_of_discharge、container_count、gross_weight_kg | Use Case，第 2 页 |
| 官方进阶方向 | PDF／Word、扫描件、复杂输入、人工修正、报告更新及失败重试 | Use Case，第 2 页 |
| 官方交付 | 项目描述、演示视频、GitHub 源码及安装 README、公开可访问原型、slides／文档链接 | Rules，第 6–7 页；截图 1–3 |
| 官方时间（所给文件版本） | 初赛截止 2026-09-22 中午 12:00；视频最多 5 分钟，每超 30 秒扣 1 分 | Rules，第 6 页；Infopack，第 4 页 |
| 官方开发约束 | 工作应在正式比赛期间完成；作品应为团队原创 | Rules，第 1 页 |
| 先前聊天建议 | React、Python、TF-IDF＋Logistic Regression、不依赖付费 API、先跑通一封邮件 | HTML 中最后两段助手回复 |
| 本次规划决定 | 采用上述基线作为启动草案；首轮 TXT；云端实际运行后端和模型；记录证据与复核过程 | 本文提出的实现方案，不是主办方指定 |

以上时间来自你提供的文件，未核对后续公告；PDF 未明确标出时区，团队提交时应以官方平台显示为准。规则允许 2–5 人；聊天中的“五人分工”不是已确认的团队人数。

## MVP 做到什么

1. 导入官方 JSON 邮件及其引用的附件；每封邮件保留 email_id、主题和正文。
2. 模型根据主题和正文分类：`BL_COMPARISON`、`SI_REQUEST`、`INVOICE_QUERY`、`GENERAL`、`SPAM`。
3. 只有 `BL_COMPARISON` 进入核对。其余邮件显示“已分类／无需核对”，不显示“七字段一致”。
4. 第一轮读取 TXT；识别 SI／BL 类型、字段别名与多行值，保存来源文字。
5. 七字段全部可读取且一致才显示 `OK` 和 “No mismatch detected.”；有确定差异显示 `MISMATCH`，仅列出实际不同的字段。
6. 缺附件、错误文件、不可读或缺字段显示 `NEEDS_REVIEW`，附原因与上下文。尚未支持的文件格式也应进入复核，不能跳过后宣布成功。
7. 工作台提供邮件列表、SI／BL 并排详情、人工复核入口。修正保留原值和记录，重新计算报告。
8. 云端运行分类及核对后端，持久保存结果并提供可访问网页；支持导出自测格式。

首个开发切片只需先串通一封邮件和三个结果分支。以上完整 MVP 仍需逐项开发，不能把本文件当成实现完成。

首轮不做真实邮箱 OAuth、自动发信、生成新 SI、处理发票业务、复杂权限或训练大型语言模型。其他邮件类别只要求分类。PDF／Word／Excel 和 OCR 在 TXT 流程完成后按实际数据覆盖情况推进。

## AI 与 Cloud 分别做什么

| 环节 | 启动设计 | 向评委提供的证据 |
|---|---|---|
| AI | 自行训练轻量邮件分类器，由后端实际加载并决定处理分流 | 训练流程、独立验证结果、模型版本、真实预测及路由 |
| 提取与比较 | 文档读取、字段别名、明确格式标准化、确定性比较 | 原文、提取值、标准化值、差异理由；如实说明这些是规则处理 |
| Cloud | 网页调用云端后端；云端执行模型及核对；结果持久保存 | 公开网址、云端执行记录、刷新后结果仍在、部署说明 |
| 后续扩展 | OCR 或模型辅助处理困难文件 | 独立记录覆盖率、错误及复核结果，不混入未实现能力 |

轻量分类器是机器学习方案；规则中没有指定必须使用 LLM 或付费 API。是否获得高分取决于实际集成和效果，不能仅靠写上“AI”证明。具体云供应商、额度及部署配置留到部署阶段核实，本步骤不预设免费额度。

训练先使用人工标注或自行编写的样本，按相似模板分组划分训练和验证。不要把测试答案放进预测流程。官方材料描述参考答案用于自测，未明确授权用其训练。

## 与评分对齐

初赛评分，来自 Rules 第 4 页图表：

| 评分项 | 分数 | 我们应展示的成果 |
|---|---:|---|
| System Design & Architecture | 15 | 分类、提取、比较、人工复核、云端存储之间的数据流 |
| Working Core Prototype | 25 | 一封邮件从导入到真实核对结果的现场演示 |
| Technology Integration | 15 | 模型实际参与业务，云端实际执行流程 |
| Technical Feasibility & Validation | 15 | 测试集、错误案例、可复现步骤和限制 |
| Problem Statement Understanding | 10 | SI 为基准，五类邮件，七字段，仅核对请求继续 |
| Innovation & Solution Approach | 10 | 有来源依据的核对与可追溯人工修正 |
| Practical Value & Potential | 10 | 有依据的时间／准确性指标及实际使用流程 |

决赛图表（Rules 第 5 页）：端到端功能 25、架构与扩展性 15、技术集成 15、工程质量与稳健性 15、方案有效性与用户价值 10、用户体验与差异化 10、影响与未来潜力 10。

数据包的 `50% end-to-end + 30% classification macro-F1 + 20% defect-F1` 只是自测公式。Use Case 第 4 页明确说明自测不是最终评审。人工复核表现也需要独立验证。

## 实际数据盘点

已检查本地 `sdoc-hackathon-bundle`：520 封 JSON 邮件，250 个附件（192 TXT、22 XLSX、8 DOCX、28 PDF）；邮件列出的附件路径均能找到。这只证明现有引用有效，不代表每封核对请求都有完整 SI 和 BL，也不代表文件内容可读。

`sample_submission.json` 中的 GENERAL／OK 是占位模板，不是标注答案。

Docker 包 README 自称组织方分发包，并说明其中含评分答案；这与 Use Case 对参与者数据访问的说明有差异。本步骤只检查了 README 和文件清单，没有读取答案，也没有用它生成结果。开发输入使用 participant bundle；评分包的分发背景及答案使用范围留作主办方澄清事项，不妨碍先做原型。

## 首轮验收

| 场景 | 预期 |
|---|---|
| 原始 email_001 及 TXT 附件 | 根据已人工阅读的文件，七字段一致；分类应为核对请求 |
| 自制副本把 BL 的 container count 从 1 改为 2 | 只报告 container_count 差异，显示 SI=1、BL=2 |
| 自制副本移除 BL | NEEDS_REVIEW / missing_attachment，不显示无差异 |
| 自制副本删除一个必需字段 | NEEDS_REVIEW / missing_value，定位缺失字段 |
| 仅字段标签、大小写、明确数字格式不同 | 不因表面格式不同制造差异 |
| 非核对邮件 | 仅显示类别，不运行文档比较 |
| 无法读取的文件或处理异常 | 可见失败／复核原因，并可重试 |

修改样本均使用副本和 `demo_` ID，原始比赛数据保持原样。真实模型尚未训练，因此上表是验收期望，不是已取得的测试成绩。

## 队内任务卡

| 工作流 | 第一份交付 | 负责人 |
|---|---|---|
| A：AI 分类 | 标注规范、独立验证样本、可加载的五分类模型 | 待填 |
| B：提取与比较 | TXT 七字段、证据、三种结果分支 | 待填 |
| C：前端 | 邮件列表、并排核对、人工复核页面 | 待填 |
| D：后端与云端 | 导入接口、模型调用、结果保存、部署 | 待填 |
| E：验证与交付 | 验收样本、评估报告、README、slides 与视频 | 待填 |

这是五条工作流，不要求五个人；人数较少可合并。下一步实现目标：导入 email_001 → 分类 → 提取七字段 → 比较 → 页面显示实际结果。共同使用 [结果契约](02-result-contract.md)，避免各模块自行定义不兼容的格式。

## 英文项目简介草稿

ShipCheck is a proposed cloud-based workspace for shipping document verification. It uses a machine-learning classifier to identify document-comparison requests in a mixed inbox, extracts seven shipment fields from Shipping Instructions and draft Bills of Lading, and compares them against the SI reference. Operators can inspect differences alongside source evidence and review incomplete or unreadable cases. The initial implementation targets JSON emails and plain-text attachments, with richer document formats planned next. The project aims to reduce repetitive checking and missed discrepancies; performance and time savings will be measured during validation.

提交前按实际实现改写该段，补团队名、真实链接、测试指标和仍未支持的能力。

## 本步骤产物与后续边界

已完成：资料核对、范围草案、评分对齐、数据盘点、结果契约、验收清单与工作流拆分。

尚未完成：队内负责人分配、训练模型、应用开发、GitHub 仓库、云端部署、测试成绩及最终提交。团队可以直接以本目录作为启动会议材料。
