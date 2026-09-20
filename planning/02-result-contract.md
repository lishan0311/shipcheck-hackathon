# 内部结果契约 v0.1（待实现）

本文件是团队内部接口建议。官方自测格式仅用于导出，不能代替前端展示所需的值和证据。

## 输入

沿用 bundle 邮件对象：`email_id`、`from`、`subject`、`body`、`attachments`（相对于数据包根目录的路径列表）。不要从文件名或 email_id 推断答案；文档类型应结合内容识别。

## 内部结果

| 属性 | 类型与含义 |
|---|---|
| email_id | string，原邮件 ID |
| processing_status | QUEUED / PROCESSING / COMPLETED / FAILED |
| category | 五个官方类别之一；未分类时 null |
| classification | model_version、confidence（可为 null）；概率不是保证正确的证据 |
| comparison_status | OK / MISMATCH / NEEDS_REVIEW；非核对或尚未完成时 null |
| fields | 七个字段，每个含 si、bl、state；state 为 MATCH / MISMATCH / UNKNOWN |
| fields.*.si / bl | raw_value、normalized_value、source；不可读取的值为 null |
| source | attachment_path、原文 quote、locator（TXT 行号／PDF 页码／表格单元格） |
| defect_fields | 已确定不同的字段名数组 |
| review_reason | wrong_doc_type / missing_attachment / unreadable / missing_value 或 null |
| review_details | 可读原因、缺失字段、待办与处理上下文；额外应用原因放这里 |
| has_defect | true / false / null；内部 null 表示尚不能确定 |
| error | 处理失败时的 code 与 message，否则 null |
| review_history | 人工修改的前后值、操作者、时间、理由；保留原始提取结果 |

七字段固定为：shipper、consignee、notify_party、port_of_loading、port_of_discharge、container_count、gross_weight_kg。数量规范为整数，重量规范为公斤十进制字符串（当前实现避免浮点误差）；缺值不得变成 0。重量按数据包约定使用逗号千位、点小数，其他不明确格式送审；不要随意设重量容差。名称及地址的多行内容保留，不能仅取首行就宣称全部相同。

当前实现进度：`--compare` 显式启动核对，category 和 classification 为 null，routing_source 为 manual_comparison；不冒充 AI 分类。已实现 TXT 字段与比较输出；review_history 目前为空，人工修正及保存尚未实现。每个提取值额外提供 issue，重复字段保留 candidates 及所有证据。

AI 路径已实现：`--process` 使用已训练模型，routing_source=ai_classifier。classification 含 predicted_category、confidence、margin、probabilities、vocabulary_coverage、needs_review、review_details、model_version 及训练来源。routing_status 为 COMPARED / CLASSIFIED_ONLY / CLASSIFICATION_REVIEW。分类不确定时 category=null、comparison_status=null、review_reason=null，原因放在 review_details；确定为非核对类别时 comparison_status=null，不能显示“无差异”。此模型目前是自编合成数据基线，概率未校准。

## 状态约束

- COMPLETED 只表示自动处理结束，NEEDS_REVIEW 仍可属于 COMPLETED。
- OK 必须七字段均为 MATCH；两边同时缺值仍为 UNKNOWN。
- 七字段都可可靠判断且至少一个不同，才将整体标为 MISMATCH。
- 任一字段无法可靠判断，整体为 NEEDS_REVIEW；已发现的确定差异仍保留供人检查。has_defect 若已有确定差异可为 true，否则为 null。
- 非核对邮件 comparison_status=null，前端显示“无需核对”。
- FAILED 不能伪装成 OK；前端显示错误并提供重试。
- 分类不确定时先请求人工确认类别，使用 review_details 记录；不能编造新的官方 review_reason。

## 官方自测导出

输出以 email_id 为 key，覆盖全部数据邮件，value 仅使用以下字段：

```json
{
  "email_001": {
    "category": "BL_COMPARISON",
    "status": "OK",
    "review_reason": null,
    "has_defect": false,
    "defect_fields": []
  }
}
```

上例是人工阅读 email_001 后得到的期望格式示例，不是模型运行结果，也不是完整 520 封提交。

| 内部情况 | 导出映射 |
|---|---|
| 核对且 OK | status=OK、has_defect=false、defect_fields=[]、review_reason=null |
| 核对且 MISMATCH | status=MISMATCH、has_defect=true、实际 defect_fields、review_reason=null |
| 核对且 NEEDS_REVIEW | status=NEEDS_REVIEW、官方 review_reason；导出适配器须核对评分器对 defect 字段的约定，内部未知值不能被解释为“确认无缺陷” |
| 非核对类别 | 沿用模板 status=OK、has_defect=false、defect_fields=[]、review_reason=null；这只是导出占位，UI 不显示为核对成功 |
| 待处理、失败、类别未确认 | 阻止完整导出并明确列出未完成邮件，不用默认 GENERAL／OK 填补 |

## 首轮验收数据的证据

email_001 的原始 SI 中 `No. of Containers or Packages: 1 x 40'HC`，BL 中 `Container Count: 1 x 40'HC`，规范数量都为 1；两份重量均为 `21,577 KG`，规范为 21577。船名、航次及货描不是本题规定的七字段，不加入 defect_fields。

其余五项人工阅读也一致：APRIL FAR EAST (M) SDN BHD（连同地址）、MOORIM SP CO., LTD（连同地址）、UAB NOVAKOPA、PORT KLANG (WESTPORT), MALAYSIA (MYPKG)、CALLAO, PERU (PECLL)。程序实现后仍应从原始附件读取，不可硬编码这些值。
