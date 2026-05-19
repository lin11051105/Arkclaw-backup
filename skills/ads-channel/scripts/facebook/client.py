"""MetaAdsClient — facebook-business SDK 封装。

统一处理认证、错误、Rate Limit。所有上层模块通过此 client 与 Meta Graph API 交互。
"""
from __future__ import annotations

import logging
import os
from datetime import datetime

import time
from typing import Any

import requests

from facebook_business.api import FacebookAdsApi
from facebook_business.adobjects.adaccount import AdAccount
from facebook_business.adobjects.adcreative import AdCreative
from facebook_business.adobjects.page import Page
from facebook_business.adobjects.pagepost import PagePost
from facebook_business.adobjects.user import User
from facebook_business.exceptions import FacebookRequestError

from . import config

_log = logging.getLogger(__name__)

# Rate limit 重试配置
_RATE_LIMIT_MAX_RETRIES = 3
_RATE_LIMIT_BASE_DELAY = 30  # 秒


class RateLimitError(Exception):
    """Rate limit 重试耗尽，需要 agent 介入决策。"""

    def __init__(self, message: str, endpoint: str, retries_exhausted: int):
        super().__init__(message)
        self.endpoint = endpoint
        self.retries_exhausted = retries_exhausted


class MetaAdsClient:
    """Meta Ads API 客户端。"""

    def __init__(self, access_token: str | None = None, account_id: str | None = None):
        self._token = access_token or config.SOCIAL_FB_TOKEN
        self._account_id = account_id or config.META_AD_ACCOUNT_ID

        FacebookAdsApi.init(access_token=self._token, api_version=config.API_VERSION)
        self._account = AdAccount(self._account_id)

    @property
    def token(self) -> str:
        return self._token

    @property
    def account(self) -> AdAccount:
        return self._account

    @property
    def account_id(self) -> str:
        return self._account_id

    def _request_with_retry(
        self,
        url: str,
        params: dict[str, Any] | None,
        *,
        endpoint_label: str,
    ) -> dict:
        """Internal: HTTP GET with rate-limit retry. Used by graph_get and pagination.

        Centralises retry + error semantics so initial requests and pagination
        cursors behave identically (P0 fix: pagination previously bypassed retry).

        Args:
            url: Full HTTPS URL (may already contain query string from a paging cursor).
            params: Extra query params; ``access_token`` is auto-injected.
                    Pass ``None`` for paging cursors that already carry the token.
            endpoint_label: Logical name for logging and ``RateLimitError.endpoint``.

        Raises:
            RateLimitError: rate limit retries exhausted.
            MetaAdsError: other Graph API error.
        """
        merged: dict[str, Any] = dict(params or {})
        merged.setdefault("access_token", self._token)

        for attempt in range(_RATE_LIMIT_MAX_RETRIES + 1):
            resp = requests.get(url, params=merged, timeout=30)
            data = resp.json()

            if "error" not in data:
                return data

            err = data["error"]
            code = err.get("code", 0)

            if code in (4, 17, 32, 613):
                if attempt < _RATE_LIMIT_MAX_RETRIES:
                    delay = _RATE_LIMIT_BASE_DELAY * (2 ** attempt)
                    _log.warning(
                        "Rate limit on %s, retry %d/%d in %ds",
                        endpoint_label, attempt + 1, _RATE_LIMIT_MAX_RETRIES, delay,
                    )
                    time.sleep(delay)
                    continue
                raise RateLimitError(
                    f"Rate limit 重试 {_RATE_LIMIT_MAX_RETRIES} 次仍失败: {err.get('message', '')}",
                    endpoint=endpoint_label,
                    retries_exhausted=_RATE_LIMIT_MAX_RETRIES,
                )

            raise MetaAdsError(
                message=err.get("message", str(data)),
                code=code,
                subcode=err.get("error_subcode", 0),
            )

        # Loop body always returns or raises — defensive fallback only
        raise RuntimeError(
            f"_request_with_retry exited loop without return/raise on {endpoint_label}"
        )

    def graph_get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        """通用 Graph API GET 请求，统一处理认证和 rate limit 重试。

        Rate limit 策略：自动重试 3 次（30s/60s/120s），仍失败则 raise RateLimitError
        供 agent 决策（等待 / 降频 / 上报）。

        Returns:
            API 响应 JSON（含 "data" 字段）

        Raises:
            RateLimitError: rate limit 重试耗尽
            MetaAdsError: 其他 API 错误
        """
        url = f"https://graph.facebook.com/{config.API_VERSION}/{path}"
        return self._request_with_retry(url, params, endpoint_label=path)

    def graph_paginate(self, path: str, params: dict[str, Any] | None = None) -> list[dict]:
        """自动翻页获取全部结果。

        每一页都走 :meth:`_request_with_retry`：rate limit 自动重试，
        Graph API 错误直接 raise（不再静默截断结果集）。

        Raises:
            RateLimitError: 任意一页 rate limit 重试耗尽
            MetaAdsError: 任意一页返回 Graph API 错误
        """
        results: list[dict] = []
        data = self.graph_get(path, params)
        results.extend(data.get("data", []))
        page_idx = 0
        while data.get("paging", {}).get("next"):
            page_idx += 1
            time.sleep(0.3)
            next_url = data["paging"]["next"]
            # next URL 已携带 access_token + cursor，不再追加 params
            data = self._request_with_retry(
                next_url, params=None, endpoint_label=f"{path}#page{page_idx}"
            )
            results.extend(data.get("data", []))
        return results

    def get_account_info(self) -> dict:
        """返回广告账户基本信息。"""
        fields = ["id", "name", "account_status", "currency", "balance"]
        info = self._account.api_get(fields=fields)
        balance_cents = int(info["balance"])
        return {
            "id": info["id"],
            "name": info["name"],
            "account_status": _status_label(info["account_status"]),
            "currency": info["currency"],
            "balance": f"${balance_cents / 100:.2f}",
            "balance_raw": balance_cents / 100,
        }

    def fetch_ad_comments(
        self,
        *,
        start: datetime,
        end: datetime,
        limit: int = 1000,
        page_id: str | None = None,
    ) -> list[dict]:
        """Fetch comments from ad dark posts + Page organic posts.

        Three sources, in order:
        1. Ad dark posts (via Batch API, ~8s for 200 ads)
        2. Page organic posts (embedded comments, ~5s)
        3. Instagram (if linked)

        Args:
            start: window start (timezone-aware).
            end:   window end (timezone-aware).
            limit: upper bound on total comments returned.
            page_id: Facebook Page ID. If None, derived from the first ad creative.
        """
        import json as _json
        import requests as _requests

        if not page_id:
            try:
                creatives = self._account.get_ad_creatives(
                    fields=["effective_object_story_id"],
                    params={"limit": 1},
                )
                for cr in creatives:
                    sid = cr.get("effective_object_story_id", "")
                    if sid:
                        page_id = sid.split("_")[0]
                        break
            except Exception as exc:
                _log.warning("Failed to discover page_id: %s", exc)
            if not page_id:
                return []

        try:
            page_info = Page(page_id).api_get(fields=["access_token"])
            page_token = page_info.get("access_token")
        except Exception as exc:
            _log.warning("Failed to get page token for %s: %s", page_id, exc)
            return []

        if not page_token:
            return []

        start_unix = int(start.timestamp())
        results: list[dict] = []
        seen_ids: set[str] = set()

        # --- 1. Ad dark posts via Batch API ---
        ad_stories: dict[str, str] = {}
        try:
            ads = self._account.get_ads(
                fields=["name", "adcreatives{effective_object_story_id}"],
                params={"limit": 500, "effective_status": ["ACTIVE"]},
            )
            for ad in ads:
                ad_name = ad.get("name", "")
                for cr in ad.get("adcreatives", {}).get("data", []):
                    sid = cr.get("effective_object_story_id", "")
                    if sid and ad_name:
                        ad_stories[sid] = ad_name
        except Exception as exc:
            _log.info("Ad stories unavailable: %s", exc)

        if ad_stories:
            story_list = list(ad_stories.items())
            _BATCH = 50
            for i in range(0, len(story_list), _BATCH):
                if len(results) >= limit:
                    break
                batch = story_list[i : i + _BATCH]
                batch_req = [
                    {"method": "GET", "relative_url": (
                        f"{sid}/comments?fields=message,created_time,like_count,comment_count"
                        f"&order=reverse_chronological&since={start_unix}&limit=50"
                    )}
                    for sid, _ in batch
                ]
                try:
                    resp = _requests.post(
                        "https://graph.facebook.com/",
                        data={"access_token": page_token, "batch": _json.dumps(batch_req)},
                        timeout=30,
                    )
                    for j, br in enumerate(resp.json()):
                        if br.get("code") != 200:
                            continue
                        body = _json.loads(br.get("body", "{}"))
                        sid, ad_name = batch[j]
                        for c in body.get("data", []):
                            cid = c.get("id", "")
                            if cid in seen_ids:
                                continue
                            created_dt = self._parse_fb_time(c.get("created_time", ""))
                            if not created_dt or created_dt < start or created_dt > end:
                                continue
                            seen_ids.add(cid)
                            results.append({
                                "id": cid,
                                "creative_id": sid,
                                "creative_name": ad_name,
                                "language": "other",
                                "text": c.get("message", ""),
                                "likes": int(c.get("like_count", 0)),
                                "replies": int(c.get("comment_count", 0)),
                                "created_at": c.get("created_time", ""),
                                "source": "facebook_ad",
                            })
                except Exception as exc:
                    _log.warning("Batch comment fetch failed: %s", exc)

        # Page organic posts and Instagram organic posts are excluded —
        # only ad dark post comments are relevant for sentiment analysis.

        _log.info("fetch_ad_comments: %d comments (ad:%d page:%d ig:%d)",
                   len(results),
                   sum(1 for r in results if r["source"] == "facebook_ad"),
                   sum(1 for r in results if r["source"] == "facebook_page"),
                   sum(1 for r in results if r["source"] == "instagram"))
        return results

    @staticmethod
    def _parse_fb_time(raw: str) -> datetime | None:
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw.replace("+0000", "+00:00"))
        except ValueError:
            return None
        return results

    def list_ad_accounts(self, name_filter: str | None = None) -> list[dict]:
        """列出当前 token 可访问的所有广告账户。可按名称过滤。"""
        fields = ["id", "name", "account_status", "currency", "balance"]
        me = User("me")
        accounts = me.get_ad_accounts(fields=fields, params={"limit": 200})
        results = [
            {
                "id": acc["id"],
                "name": acc["name"],
                "account_status": _status_label(acc["account_status"]),
                "currency": acc.get("currency", ""),
                "balance": f"${int(acc.get('balance', 0)) / 100:.2f}",
            }
            for acc in accounts
        ]
        if name_filter:
            name_filter_lower = name_filter.lower()
            results = [a for a in results if name_filter_lower in a["name"].lower()]
        return results


class MetaAdsError(Exception):
    """Meta Ads API 错误封装。"""

    def __init__(self, message: str, code: int, subcode: int = 0):
        super().__init__(message)
        self.code = code
        self.subcode = subcode

    @classmethod
    def from_fb_error(cls, e: FacebookRequestError) -> "MetaAdsError":
        body = e.body() or {}
        err = body.get("error", {})
        return cls(
            message=err.get("message", str(e)),
            code=err.get("code", 0),
            subcode=err.get("error_subcode", 0),
        )

    @property
    def is_token_expired(self) -> bool:
        return self.code == 190

    @property
    def is_rate_limited(self) -> bool:
        return self.code in (17, 32, 613) or self.code == 429


# account_status 映射
_STATUS_MAP = {1: "Active", 2: "Disabled", 3: "Unsettled", 7: "Pending_Risk_Review", 9: "In_Grace_Period", 100: "Pending_Closure", 101: "Closed"}


def _status_label(status: int) -> str:
    return _STATUS_MAP.get(status, f"Unknown({status})")
