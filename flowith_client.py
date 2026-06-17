import json
import uuid
import httpx
import asyncio
import time
import logging
from typing import AsyncGenerator, Optional

logger = logging.getLogger("flowith")

BASE_URL = "https://edge.flowith.io"
SUPABASE_URL = "https://aibdxsebwhalbnugsqel.supabase.co"
SUPABASE_ANON_KEY = "sb_publishable_qPCinc8LE8ChpdT7Pf79tQ_eryz5udr"


SUPABASE_HEADERS = {
    "apikey": SUPABASE_ANON_KEY,
    "Content-Type": "application/json",
    "x-client-info": "supabase-js-web/2.91.0",
    "x-supabase-api-version": "2024-01-01",
}


def refresh_access_token_sync(refresh_token: str, proxy: Optional[str] = None) -> dict:
    """同步刷新 access_token（用于管理后台快速获取邮箱/AT）"""
    import httpx as _httpx
    kwargs = {
        "headers": dict(SUPABASE_HEADERS),
        "timeout": 30.0,
    }
    if proxy:
        kwargs["proxy"] = proxy
    client = _httpx.Client(**kwargs)
    try:
        resp = client.post(
            f"{SUPABASE_URL}/auth/v1/token?grant_type=refresh_token",
            json={"refresh_token": refresh_token},
        )
        if resp.status_code != 200:
            raise Exception(f"Supabase {resp.status_code}: {resp.text[:300]}")
        return resp.json()
    finally:
        client.close()


class FlowithClient:
    def __init__(
        self,
        authorization: Optional[str] = None,
        refresh_token: Optional[str] = None,
        proxy: Optional[str] = None,
    ):
        self._authorization = authorization or ""
        self._refresh_token = refresh_token or ""
        self._proxy = proxy
        self._client = None
        self._expires_at = 0

    @property
    def authorization(self) -> str:
        return self._authorization

    @property
    def refresh_token(self) -> str:
        return self._refresh_token

    async def refresh_at(self) -> dict:
        """用 RT 刷新 AT，返回完整 Supabase token 响应"""
        if not self._refresh_token:
            raise ValueError("没有 refresh_token")
        client = httpx.AsyncClient(
            headers=dict(SUPABASE_HEADERS),
            timeout=30.0,
        )
        if self._proxy:
            client = httpx.AsyncClient(
                headers=dict(SUPABASE_HEADERS),
                proxy=self._proxy,
                timeout=30.0,
            )
        try:
            resp = await client.post(
                f"{SUPABASE_URL}/auth/v1/token?grant_type=refresh_token",
                json={"refresh_token": self._refresh_token},
            )
            if resp.status_code != 200:
                raise Exception(f"Supabase {resp.status_code}: {resp.text[:300]}")
            data = resp.json()
            self._authorization = f"Bearer {data['access_token']}"
            self._refresh_token = data.get("refresh_token", self._refresh_token)
            self._expires_at = time.time() + data.get("expires_in", 3600) - 60
            if self._client:
                await self._client.aclose()
                self._client = None
            return data
        finally:
            await client.aclose()

    async def _get_client(self) -> httpx.AsyncClient:
        # auto-refresh only if AT is missing or actually expired
        if not self._authorization or "Bearer " not in self._authorization:
            if self._refresh_token:
                try:
                    await self.refresh_at()
                except Exception:
                    pass
        elif self._expires_at > 0 and time.time() >= self._expires_at:
            if self._refresh_token:
                try:
                    await self.refresh_at()
                except Exception:
                    pass
        if self._client is None:
            kwargs = {
                "headers": {
                    "accept": "*/*",
                    "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
                    "authorization": self._authorization,
                    "origin": "https://flowith.io",
                    "referer": "https://flowith.io/",
                    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
                    "sec-ch-ua": '"Microsoft Edge";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": '"Windows"',
                    "sec-fetch-dest": "empty",
                    "sec-fetch-mode": "cors",
                    "sec-fetch-site": "same-site",
                },
                "timeout": 300.0,
            }
            if self._proxy:
                kwargs["proxy"] = self._proxy
            self._client = httpx.AsyncClient(**kwargs)
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get_credits(self) -> list:
        client = await self._get_client()
        resp = await client.get(f"{BASE_URL}/user/credits")
        resp.raise_for_status()
        return resp.json()

    async def get_models(self) -> dict:
        client = await self._get_client()
        resp = await client.get(f"{BASE_URL}/models?logo=1&desc=1")
        resp.raise_for_status()
        return resp.json()

    async def get_user_info(self) -> dict:
        client = httpx.AsyncClient(
            headers={
                "accept": "*/*",
                "apikey": SUPABASE_ANON_KEY,
                "authorization": self._authorization,
                "x-client-info": "supabase-js-web/2.91.0",
                "x-supabase-api-version": "2024-01-01",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            },
            timeout=30.0,
        )
        if self._proxy:
            client = httpx.AsyncClient(
                headers={
                    "accept": "*/*",
                    "apikey": SUPABASE_ANON_KEY,
                    "authorization": self._authorization,
                    "x-client-info": "supabase-js-web/2.91.0",
                    "x-supabase-api-version": "2024-01-01",
                    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                },
                proxy=self._proxy,
                timeout=30.0,
            )
        try:
            resp = await client.get(f"{SUPABASE_URL}/auth/v1/user")
            resp.raise_for_status()
            return resp.json()
        finally:
            await client.aclose()

    async def get_models_with_tier(self) -> dict:
        models_raw, credits, user_info = await asyncio.gather(
            self.get_models(),
            self.get_credits(),
            self.get_user_info(),
            return_exceptions=True,
        )
        allowed_tiers = set()
        if isinstance(credits, list):
            for c in credits:
                policy = c.get("credit_policy_snapshot") or c.get("policy_summary") or {}
                for t in policy.get("allowed_model_tiers", []):
                    allowed_tiers.add(t)

        email = ""
        if isinstance(user_info, dict):
            email = user_info.get("email", user_info.get("user_metadata", {}).get("email", ""))

        models = []
        if isinstance(models_raw, dict):
            for mid, m in models_raw.items():
                m["id"] = mid
                models.append(m)

        if allowed_tiers:
            filtered = [m for m in models if m.get("tier") in allowed_tiers or not m.get("tier")]
        else:
            filtered = models

        return {
            "models": filtered,
            "allowed_tiers": list(allowed_tiers),
            "email": email,
            "credits": credits if isinstance(credits, list) else [],
        }

    async def chat_stream(
        self,
        messages: list,
        model: str = "deepseek-v4-flash",
        node_id: Optional[str] = None,
        conv_id: Optional[str] = None,
        websearch: bool = False,
    ) -> AsyncGenerator[tuple, None]:
        client = await self._get_client()
        node_id = node_id or str(uuid.uuid4())
        conv_id = conv_id or str(uuid.uuid4())

        payload = {
            "target_feature": "text_completion",
            "model": model,
            "messages": messages,
            "nodeId": node_id,
            "convId": conv_id,
            "stream": True,
        }
        if websearch:
            payload["websearch"] = True

        async with client.stream(
            "POST",
            f"{BASE_URL}/completion",
            json=payload,
        ) as resp:
            resp.raise_for_status()
            buffer = ""
            in_think = False
            prev_value_end = 0
            prev_reasoning_end = 0

            async for chunk in resp.aiter_text():
                if not chunk:
                    continue
                buffer += chunk

                # parse think tags from buffer
                ts = buffer.find("<think>")
                te = buffer.find("</think>")
                has_open = ts != -1
                has_close = te != -1

                if has_open and has_close and te > ts and ts >= prev_value_end:
                    # complete think block (not yet processed)
                    if prev_value_end < ts:
                        yield (buffer[prev_value_end:ts], "")
                    if not in_think:
                        yield ("", buffer[ts + 7:te])
                    prev_value_end = te + 8
                    prev_reasoning_end = te + 8
                    in_think = False
                elif has_open and not has_close and ts >= prev_value_end:
                    # in think block
                    if not in_think:
                        in_think = True
                        prev_reasoning_end = ts + 7
                        if prev_value_end < ts:
                            yield (buffer[prev_value_end:ts], "")
                    new_r = buffer[prev_reasoning_end:]
                    if new_r:
                        yield ("", new_r)
                        prev_reasoning_end = len(buffer)
                elif has_open and ts < prev_value_end and te > ts:
                    # already processed this think block, treat rest as value
                    new_v = buffer[prev_value_end:]
                    if new_v:
                        yield (new_v, "")
                        prev_value_end = len(buffer)
                elif not has_open and not in_think:
                    # pure value text
                    new_v = buffer[prev_value_end:]
                    if new_v:
                        yield (new_v, "")
                        prev_value_end = len(buffer)
                elif not has_open and in_think:
                    # still accumulating think content, no close yet
                    new_r = buffer[prev_reasoning_end:]
                    if new_r:
                        yield ("", new_r)
                        prev_reasoning_end = len(buffer)

                # trim buffer occasionally
                if len(buffer) > 100000:
                    trim = max(prev_value_end, prev_reasoning_end)
                    if trim > 50000:
                        buffer = buffer[trim:]
                        prev_value_end -= trim
                        prev_reasoning_end -= trim

            # flush remaining after stream ends
            remaining = buffer[prev_value_end:]
            if remaining:
                yield (remaining, "")

    async def upload_file(self, file_data: bytes, filename: str = "image.png") -> str:
        """Upload a file to /file/store, returns URL."""
        client = await self._get_client()
        files = {"file": (filename, file_data, "image/png")}
        resp = await client.post(f"{BASE_URL}/file/store", files=files)
        resp.raise_for_status()
        data = resp.json()
        return data.get("url", "")

    async def generate_image(
        self,
        messages: list,
        model: str,
        node_id: Optional[str] = None,
        conv_id: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
        image_size: Optional[str] = None,
        quality: Optional[str] = None,
        websearch: bool = False,
        style: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """Stream image generation via /image_gen, yields SSE events."""
        client = await self._get_client()
        node_id = node_id or str(uuid.uuid4())
        conv_id = conv_id or str(uuid.uuid4())

        payload = {
            "target_feature": "image_generation",
            "model": model,
            "messages": messages,
            "nodeId": node_id,
            "convId": conv_id,
            "stream": True,
        }
        if aspect_ratio:
            payload["aspect_ratio"] = aspect_ratio
        if image_size:
            payload["image_size"] = image_size
        if quality:
            payload["quality"] = quality
        if websearch:
            payload["websearch"] = True
        if style:
            payload["style"] = style

        async with client.stream(
            "POST",
            f"{BASE_URL}/image_gen",
            json=payload,
        ) as resp:
            resp.raise_for_status()
            buffer = ""
            async for chunk in resp.aiter_text():
                buffer += chunk
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        yield data
                    except json.JSONDecodeError:
                        pass

    async def generate_video(
        self,
        messages: list,
        model: str,
        node_id: Optional[str] = None,
        conv_id: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
        duration: Optional[str] = None,
        websearch: bool = False,
    ) -> AsyncGenerator[dict, None]:
        client = await self._get_client()
        node_id = node_id or str(uuid.uuid4())
        conv_id = conv_id or str(uuid.uuid4())

        payload = {
            "target_feature": "video_generation",
            "model": model,
            "messages": messages,
            "nodeId": node_id,
            "convId": conv_id,
            "stream": True,
        }
        if aspect_ratio:
            payload["aspect_ratio"] = aspect_ratio
        if duration:
            payload["duration"] = duration
        if websearch:
            payload["websearch"] = True

        async with client.stream(
            "POST",
            f"{BASE_URL}/image_gen",
            json=payload,
        ) as resp:
            resp.raise_for_status()
            buffer = ""
            async for chunk in resp.aiter_text():
                buffer += chunk
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        yield data
                    except json.JSONDecodeError:
                        pass

    async def chat(
        self,
        messages: list,
        model: str = "deepseek-v4-flash",
    ) -> str:
        full = ""
        async for value, reasoning in self.chat_stream(messages, model):
            full += value
        return full
