---
name: byted-viking-search-knowledgebase
description: 调用火山引擎Viking知识库的远程API，检索和query相关的知识库数据。使用场景包括：查询知识库内容、获取相关文档数据、检索特定信息等。当需要搜索数据回答用户问题时使用此skill。
metadata:
  version: "1.0.0"
---

# Byted Viking Search Knowledgebase

该 Skill 用于通过APIG网关调用火山引擎 Viking 知识库的 API：

- `/api/knowledge/collection/info`：查看知识库详情，获取 `collection_name` 和 `description`，用于辅助路由决策
- `/api/knowledge/collection/search_knowledge`：语义检索，支持根据用户的查询文本从知识库中获取相关的内容切片，返回检索结果列表、相关度分数、文档信息等

## 能力说明

### 场景一：意图明确 + 已知目标知识库

用户问题中**直接指定了**某个具体的知识库，或者模型通过上下文已经确定目标库。

模型直接调用 `search` 动作，传入 `resource_id` 或 `name`+ `project`，获取精准检索结果。

### 场景二：意图明确 + 未知目标知识库（需推理路由）

用户有一个明确的问题，但**没有直接指定**用哪个知识库。

模型分两步走：
1. 先调用 `info` 动作，获取所有有权限知识库的 `collection_name` 和 `description`
2. 根据 description 推理出最相关的知识库
3. 再调用 `search` 动作，传入对应的 `resource_id`，获取精准检索结果

### 场景三：意图不明确：多库并行检索（auto 模式）

用户的问题**无法判断具体目标**，或者推理后仍不确定。

模型调用 `auto` 模式，脚本对所有有权限库并发执行轻量级search且合并检索结果，按返回的score进行排序后（score越高，对应的检索结果越置信），直接返回各库的检索结果列表，供模型做最终决策。

## 使用方式

脚本：`scripts/viking_search.py`

### info - 查看知识库详情

获取指定知识库的 `collection_name` 和 `description`，用于路由决策。

```bash
# 方式一：通过 resource_id 查询
python viking_search.py --action info --resource-id <collection_resource_id>

# 方式二：通过 name + project 查询（需设置 DATABASE_VIKING_PROJECT）
python viking_search.py --action info --name "XXX知识库" --project "default"
```

### search - 单库检索

对指定知识库执行语义检索。

```bash
# 方式一：通过 resource_id（推荐）
python viking_search.py --action search --resource-id <resource_id> --query "用户问题" --limit 10

# 方式二：通过 name + project（需设置 DATABASE_VIKING_PROJECT）
python viking_search.py --action search --name "XXX知识库" --project "default" --query "用户问题"
```

### auto - 多库并行检索

对所有有权限知识库并发执行轻量级检索。

```bash
export DATABASE_VIKING_COLLECTION="rid1,rid2,rid3"
python viking_search.py --action auto --query "用户问题"
```

## 返回说明

### info 返回示例

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "resource_id": "rid_xxx",
    "collection_name": "电商知识库",
    "description": "包含商品信息、订单数据、用户评价等电商相关文档。",
    "project": "default"
  }
}
```

### search 返回示例

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "result_list": [
      {
        "score": 0.892,
        "rerank_score": 0.912,
        "content": "Mac 配置 Python 开发环境的步骤：首先安装 Homebrew，然后通过 brew install pyenv 来管理 Python 版本...",
        "chunk_title": "Python 环境配置",
        "chunk_id": "chunk_101",
        "doc_info": {
          "doc_id": "doc_001",
          "doc_name": "Mac 开发环境配置大全.md",
          "doc_type": "markdown"
        }
      }
    ]
  }
}
```

### auto 返回示例

```json
{
  "mode": "multi",
  "query": "Mac 上怎么配 Python 环境？",
  "collections": [
    {
      "resource_id": "rid1_mac_guide",
      "search": {
        "code": 0,
        "data": {
          "result_list": [
            {
              "score": 0.892,
              "rerank_score": 0.912,
              "content": "Mac 配置 Python 开发环境的步骤：首先安装 Homebrew，然后通过 brew install pyenv...",
              "chunk_title": "Python 环境配置",
              "chunk_id": "chunk_101",
              "doc_info": { "doc_id": "doc_001", "doc_name": "Mac 开发环境配置大全.md", "doc_type": "markdown" }
            }
          ]
        }
      },
      "top_chunks": [
        {
          "score": 0.892,
          "rerank_score": 0.912,
          "content": "Mac 配置 Python 开发环境的步骤：首先安装 Homebrew，然后通过 brew install pyenv...",
          "chunk_title": "Python 环境配置",
          "chunk_id": "chunk_101",
          "doc_id": "doc_001",
          "doc_name": "Mac 开发环境配置大全.md",
          "doc_type": "markdown"
        }
      ]
    },
    {
      "resource_id": "rid2_hr_policy",
      "search": { "code": 0, "data": { "result_list": [...] } },
      "top_chunks": [...]
    }
  ]
}
```

## Configuration

### 环境要求

- Python 3.7+
- requests库（用于HTTP请求）

### 必需环境变量

- **DATABASE\_VIKING\_APIG\_URL**: 代理网关 URL，用于构造请求URL
- **DATABASE\_VIKING\_APIG\_KEY**: 代理网关 API Key，用于鉴权访问

### 可选环境变量

- **DATABASE_VIKING_PROJECT**: 知识库所属项目名称，默认值为 `default`。用于按名称查询/检索知识库时的辅助定位。
- **DATABASE_VIKING_COLLECTION**: 逗号分隔的 knowledge collection `resource_id` 列表。用于 `auto` 模式指定有权限的知识库范围。

## 注意事项

- 安全：妥善保管 `DATABASE_VIKING_APIG_KEY`，避免泄露
- 并发：auto 模式默认并发 8，可通过 `--max-workers` 调整
- 性能：`auto` 模式的轻量检索默认 limit=5，若需更完整结果可调大 `--limit`

## Resources

### scripts/

- `viking_search.py` - Viking 知识库检索脚本（支持 info / search / auto 三种动作）

### references/

- `search_knowledge_api.md` - 火山引擎 Viking 知识库 搜索API 文档（原始接口说明）
- `collection_info_api.md` - 火山引擎 Viking 知识库 查看知识库详情 API 文档（原始接口说明）
