# 明朝大臣史实完善与审查工作流

## 1. 准备文件
- 大臣基础数据：`backend/data/ministers.json`
- 来源目录：`backend/data/minister_source_catalog.json`
- 审校主文件：`backend/data/ministers_review.json`
- 审查报告：`backend/data/ministers_review_report.md`

## 2. 初始化审校底稿
在 `backend` 目录执行：

```bash
python -m quality.ministers_review init --force
```

说明：
- 会按 `ministers.json` 自动生成每位大臣一条审校记录。
- 初始 `review.status` 为 `pending`，等待人工核查。

## 3. 按条目完善信息
每条建议至少补齐以下字段：
- `birth_year` / `death_year`
- `major_contributions`（至少1条）
- `related_events`（至少1条）
- `project_role_background`
- `sources`（至少2条，且至少1条 `A_PRIMARY`）

来源填写格式：

```json
{
  "title": "《明史/卷72》",
  "url": "https://zh.wikisource.org/wiki/明史/卷72",
  "tier": "A_PRIMARY",
  "locator": "卷72·职官一"
}
```

## 4. 常规审查（不阻断）
```bash
python -m quality.ministers_review audit
```

用途：
- 检查名称对应、字段类型、来源 tier 合法性等基础质量。
- 输出 `ministers_review_report.md`，用于审阅问题清单。

## 5. 严格审查（发布门禁）
```bash
python -m quality.ministers_review audit --strict
```

严格模式额外要求：
- `project_role_background` 必填
- `major_contributions` 至少1条
- `related_events` 至少1条
- `sources` 至少2条
- `sources` 至少1条 `A_PRIMARY`

命令返回值：
- `0`：通过
- `1`：存在错误（需修复后再发布）

## 6. 审核状态建议
- `pending`：未审
- `in_review`：正在核查
- `verified`：已通过
- `rejected`：退回修改
