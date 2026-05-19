# 一、新素材上传 & 广告搭建测试（需求 1.1）

**输入**:
- 素材文件（三种来源，任选其一）:
  1. **DAP 素材库**（最常用）→ 用 `search_materials` 或 `get_material_detail` 获取 `download_url`，传给 `--file-url`
  2. **飞书上传** → 用户发文件到群聊，提取文件 URL
  3. **指定本地路径/URL** → 直接传给 `--file-url`
- 命名: 按 `config/naming-rules.json` 规范，格式 `{项目}_{地区}_{语言}_{类型}_{版本}`
- 测试参数: `channel`（渠道）, `countries[]`（国家）, `audience`（Broad/兴趣/重定向）, `budget`（预算）

⚠️ **DAP 素材的 `is_upload_fb` 字段陷阱**：`is_upload_fb=1` 只表示 DAP 曾将素材同步到某个 FB Business Media Library，**不代表你能通过 API 找到对应的 video_id**。以下是实测踩过的坑：

1. **Business Media Library 是 Business 级别共享的**，同一 Business 下所有 ad account 看到相同的 Media Library，不随 account 切换而变化
2. **DAP `upload_fb_folder_path` 用地区层级命名**（如 `日本/ja/万国觉醒/20260126-20260201/美宣自制/视频`），但 token 能看到的 Business `creative_folders` 可能是按项目分的老文件夹（`ROK-xxx`、`AFK-xxx`），完全对不上——说明 DAP 上传到了另一个 Business 的 Media Library
3. **DAP 素材详情没有存 `fb_video_id` 字段**，只有 `encrypted_material_name`（作为 FB 视频的 title）和 `upload_fb_folder_path`
4. **FB `advideos` API 不支持 title 过滤**，只能暴力翻页搜索，效率极低
5. **BFS 遍历 `creative_folders` 会触发 Meta Application rate limit (#4)**，恢复需要 30-60+ 分钟，且恢复后配额极小（2-3 个请求可再次触发）
6. **System user 可能跨多个 Business 有 ad account 权限，但 `creative_folders` 只对其中一个 Business 有效**

**默认做法**：用 DAP 的 `download_url` 通过 `--file-url` 重新上传到目标账户。上传是幂等的（同一视频重传不会创建重复），且比跨 Business 查找 video_id 更可靠。

**备选做法 — FB Business Media Library 搜索引用**（当素材在同一 Business 下且需要避免重复上传时）：

```
# 1. 全局搜索素材（用 DAP encrypted_material_name 完整值）
GET /{biz_id}/creatives?filtering=[{"field":"name_or_id","operator":"CONTAIN","value":"加密全名"}]&fields=id,name&limit=25

# 1b. 文件夹内搜索（素材量大时全局搜可能 truncate，用 folder_id 缩小范围）
#     folder_id 通过 DAP upload_fb_folder_path 逐级导航获得：
#     GET /{biz_id}/creative_folders?limit=200 → 找根文件夹 ID（需翻页，200+ 文件夹常见）
#     GET /{folder_id}/subfolders → 逐级进入子文件夹
#     最终拿到叶子文件夹 ID，传给 folder_id 参数
GET /{biz_id}/creatives?folder_id={leaf_folder_id}&filtering=[{"field":"name_or_id","operator":"CONTAIN","value":"关键字"}]&fields=id,name&limit=25

#     ⚠️ businesscreativefolder 节点没有直接列出素材的 edge（只有 agencies/assigned_users/subfolders）
#     不要尝试 GET /{folder_id}/creatives 或 /{folder_id}/media——会报 field not found
#     必须通过 GET /{biz_id}/creatives?folder_id=xxx 间接搜索

#     ⚠️ creative_folders 列表可能很长（200+），需要翻页（limit=200 + paging.next）
#     日期段文件夹（如 20260427-20260503）排在后面，默认 limit=50 会截断

# 2. 获取 video_id（返回的是 businessvideo 对象，需取内嵌 video.id）
GET /{businessvideo_id}?fields=id,name,business{id,name},video{id,title}
# → video.id 就是可直接用于 AdCreative 的 video_id

# 3. 用 video_id 创建广告（传给 create-ads --video-id，或通过 SDK 创建 AdCreative）
```

**⚠️ Media Library 搜索的限制（实测验证）**：
- `/{biz}/creatives` 只返回该 Business 自己的素材，跨 Business 搜不到
- DAP 按账户归属路由上传目标 Business——同一创意的不同语言版本可能分散在不同 Business（例：ROK EN/DE/PT → Lilith Games Business `1589262821285499`, ROK JA → Meetsocial HK Business `630723763692369`，因为 JP 账户归属 Meetsocial）
- `creative_folders` 可见 ≠ 素材可搜——文件夹权限和 creatives 搜索是独立的
- 如果 `/{biz}/creatives` 搜不到，先确认素材上传到了哪个 Business（看 DAP 的 `upload_fb_folder_path` + 目标账户所属 Business），再在正确的 Business 下搜
- `businessvideo` 对象可用字段：`id, business, media_library_url, name, video`
- `/{biz}/creatives` 的 `folder_id` 参数等效选项：`folder_id` / `creative_folder_id` / `parent_folder_id` / `folder` 四个参数名都能用，效果相同。推荐统一用 `folder_id`
- 不带 `filtering` 直接 `GET /{biz}/creatives?folder_id=xxx&limit=10` 可以列出文件夹内素材（验证文件夹是否为空）

**搜索关键字规则**：
- **优先用 DAP `encrypted_material_name` 完整值**（不带 `.mp4` 后缀）作为 `CONTAIN` 搜索关键字，这是 FB 素材的完整 title
- FB 上的素材名 = 加密名 + `.mp4`（如 `ROK_V_EN_AI_首领号令2_CB_1_1080x1920_29s_260429_NR_1155443.mp4`），搜索时不需要带 `.mp4` 后缀
- 不要只用 DAP ID（如 `1096114`）或短名前缀（如 `ROK_V_JA`）搜——加密全名是最精确的匹配方式
- 用中文短名（如"如此经济"）搜可跨语言交叉验证同一创意在该 Business 下有哪些语言版本

**排查"搜不到"时的验证方法**：
- 不要直接断言"不在这个 Business"——先用一条**已知存在的同 Business 素材的加密全名**作为对照组，验证搜索路径本身是否可用
- 例：搜 ROK JA 素材返回 0 → 先用同项目其他语言的加密全名（如 `ROK_V_EN_AI_首领号令2_CB_1_1080x1920_29s_260429_NR_1155443`）确认 API 正常返回 → 再用中文短名搜确认该创意的其他语言版在此 Business → 确认 JA 版确实不在
- 只有对照组验证通过后，才能下"素材不在此 Business"的结论
- 如果全局搜索返回 0 但怀疑是 truncate 问题，用 `folder_id` 参数限定到具体文件夹再搜一次

**步骤**:

1. **合规预检**（调用 creative-compliance Skill，待实现）:
   - 将素材提交合规检查
   - if `risk_level == "high"` → 拦截上线，推送修改建议到飞书，**中止流程**
   - if `risk_level == "medium"` → 标记风险，推送人工复核请求，**等待确认**
   - if `risk_level == "low"` → 继续

2. **上传素材**（命名校验 + 上传文件 → creative_id）:
   ```bash
   python workspace/skills/creative-lifecycle/scripts/cli.py upload-creative \
     --name "<素材全名>" --file-url <素材文件URL或本地路径> \
     --asset-type <video|image> --os <iOS|Android> --project <project_id>
   ```
   返回 `{"status": "success", "upload": {"creative_id": "...", "asset_type": "..."}, ...}`

   if `status == "error"` → 通知飞书错误详情，**中止流程**

3. **搭建广告结构**（Campaign → AdSet → Ad，暂停状态）:
   ```bash
   python workspace/skills/creative-lifecycle/scripts/cli.py create-ads \
     --name "<素材全名>" --creative-id <上一步返回的creative_id> \
     --budget <budget> --countries <US,JP> --audience <Broad> \
     --os <iOS|Android> --project <project_id>
   ```
   返回 `{"status": "success", "entities": {"campaign_id": "...", "adset_id": "...", "ad_id": "..."}, ...}`

   if `status == "error"` → 通知飞书错误详情，**中止流程**

   > **注意**: 上传和搭建是两个独立子命令，Agent在外面串联。
   > 也可以只执行 `upload-creative` 做纯素材上传不建广告。

   **⚠️ 跨账户 Creative 陷阱**：`create-ads` 默认使用 `META_AD_ACCOUNT_ID` 环境变量指定的账户（通常是 apps.json 中的第一个）。如果 `--creative-id` 来自其他账户，Meta API 会报错 `error_subcode: 1815696`（"创意属于另一广告账户"）。

   **解法**：在命令前覆盖环境变量，指向 creative 所在的账户：
   ```bash
   META_AD_ACCOUNT_ID=<目标账户ID不带act_前缀> python3 workspace/skills/creative-lifecycle/scripts/cli.py create-ads ...
   ```

   **如何确定 creative 属于哪个账户**：用 `list-ads --account-id act_xxx` 在候选账户中搜索，哪个账户能搜到该 creative_id，就用哪个账户的 ID。

4. **记录**: 写入 `memory/YYYY-MM-DD.md`:
   ```
   [素材上传] 项目X 素材"YY" → 渠道Z 测试广告组已创建
   Campaign: <id>, AdSet: <id>, Ad: <id>
   预算: $<budget>, 国家: <countries>
   ```

5. **推送飞书通知**: 上传完成 + 测试结构概览
