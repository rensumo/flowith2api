import json
import uuid
import asyncio
import bcrypt
import uvicorn
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from config import config
from flowith_client import FlowithClient
from tool_handler import prepare_messages_with_tools, parse_tool_calls

app = FastAPI(title="Flowith API", version="1.0.0")

STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)


# ─── Auth helpers ──────────────────────────────────────────────
def verify_admin(auth: str) -> bool:
    if not auth.startswith("Bearer "):
        return False
    token = auth[7:]
    return token == config.get("admin_token", "")


async def admin_dependency(request: Request):
    auth = request.headers.get("Authorization", "")
    if not verify_admin(auth):
        raise HTTPException(status_code=401, detail="Unauthorized")


# ─── API Key auth for OpenAI-compatible ────────────────────────
async def api_key_dependency(request: Request):
    auth = request.headers.get("Authorization", "")
    api_key = config.api_key
    if auth == f"Bearer {api_key}":
        return True
    # also check x-goog-api-key
    if request.headers.get("x-goog-api-key") == api_key:
        return True
    raise HTTPException(status_code=401, detail="Invalid API Key")


# ─── OpenAI-compatible models list ────────────────────────────
@app.get("/v1/models")
async def openai_models(authorized: bool = Depends(api_key_dependency)):
    """返回 OpenAI 兼容的模型列表（按用户层级过滤）"""
    tokens = config.get("tokens", [])
    active = [t for t in tokens if t.get("enabled", True)]
    if not active:
        return {"object": "list", "data": []}

    tk = active[0]
    client = FlowithClient(
        authorization=tk.get("authorization", ""),
        refresh_token=tk.get("refresh_token", ""),
        proxy=config.get("proxy_url"),
    )
    try:
        info = await client.get_models_with_tier()
    finally:
        await client.close()

    data = []
    for m in info.get("models", []):
        data.append({
            "id": m.get("id"),
            "object": "model",
            "created": 0,
            "owned_by": "flowith",
            "permission": [],
            "root": m.get("id"),
            "parent": None,
        })

    return {"object": "list", "data": data}


# ─── Static pages ──────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def root():
    login_html = STATIC_DIR / "login.html"
    if login_html.exists():
        return HTMLResponse(login_html.read_text(encoding="utf-8"))
    return {"msg": "Flowith API Server"}


@app.get("/manage", response_class=HTMLResponse)
async def manage_page():
    manage_html = STATIC_DIR / "manage.html"
    if manage_html.exists():
        return HTMLResponse(manage_html.read_text(encoding="utf-8"))
    return {"msg": "Manage Page"}


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    root_html = STATIC_DIR / "login.html"
    if root_html.exists():
        return HTMLResponse(root_html.read_text(encoding="utf-8"))
    return {"msg": "Login Page"}


# ─── Auth API ──────────────────────────────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/api/login")
async def api_login(req: LoginRequest):
    if req.username != config.admin_username:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not bcrypt.checkpw(req.password.encode(), config.admin_password_hash.encode()):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = str(uuid.uuid4())
    config.set("admin_token", token)
    return {"success": True, "token": token}


@app.get("/api/stats")
async def api_stats(authorized: bool = Depends(admin_dependency)):
    return {
        "version": "1.0.0",
        "status": "running",
    }


# ─── Models & User Info API ────────────────────────────────────
@app.get("/api/models")
async def api_models(authorized: bool = Depends(admin_dependency)):
    """获取所有 Token 的可用模型（按用户层级过滤）"""
    tokens = config.get("tokens", [])
    active = [t for t in tokens if t.get("enabled", True)]
    if not active:
        return {"success": True, "data": [], "message": "没有可用 Token"}

    results = []
    for tk in active:
        try:
            client = FlowithClient(
                authorization=tk.get("authorization", ""),
                refresh_token=tk.get("refresh_token", ""),
                proxy=config.get("proxy_url"),
            )
            info = await client.get_models_with_tier()
            await client.close()
            results.append({
                "email": tk.get("email", info.get("email", "unknown")),
                "models": info["models"],
                "allowed_tiers": info["allowed_tiers"],
                "model_count": len(info["models"]),
            })
        except Exception as e:
            results.append({
                "email": tk.get("email", "unknown"),
                "error": str(e),
            })

    return {"success": True, "data": results}


@app.get("/api/user/info")
async def api_user_info(authorized: bool = Depends(admin_dependency)):
    """自动获取所有 Token 的用户信息（邮箱）"""
    tokens = config.get("tokens", [])
    results = []
    for tk in tokens:
        try:
            client = FlowithClient(
                authorization=tk.get("authorization", ""),
                refresh_token=tk.get("refresh_token", ""),
                proxy=config.get("proxy_url"),
            )
            info = await client.get_user_info()
            await client.close()
            results.append({
                "id": tk.get("id"),
                "stored_email": tk.get("email", ""),
                "auto_email": info.get("email", ""),
                "username": info.get("user_metadata", {}).get("preferred_username", ""),
                "avatar": info.get("user_metadata", {}).get("avatar_url", ""),
                "provider": info.get("app_metadata", {}).get("provider", ""),
            })
        except Exception as e:
            results.append({
                "id": tk.get("id"),
                "stored_email": tk.get("email", ""),
                "error": str(e),
            })
    return {"success": True, "data": results}


# ─── Credits API ───────────────────────────────────────────────
@app.get("/api/credits")
async def api_credits(authorized: bool = Depends(admin_dependency)):
    """查询 flowith 积分"""
    tokens = config.get("tokens", [])
    results = []
    for tk in tokens:
        try:
            client = FlowithClient(
                authorization=tk.get("authorization", ""),
                refresh_token=tk.get("refresh_token", ""),
                proxy=config.get("proxy_url"),
            )
            credits = await client.get_credits()
            await client.close()
            results.append({
                "email": tk.get("email", "unknown"),
                "credits": credits,
            })
        except Exception as e:
            results.append({
                "email": tk.get("email", "unknown"),
                "error": str(e),
            })
    return {"success": True, "data": results}


@app.get("/api/credits/simple")
async def api_credits_simple(authorized: bool = Depends(admin_dependency)):
    """简化版积分查询"""
    tokens = config.get("tokens", [])
    total_remain = 0.0
    total_init = 0
    details = []
    for tk in tokens:
        try:
            client = FlowithClient(
                authorization=tk.get("authorization", ""),
                refresh_token=tk.get("refresh_token", ""),
                proxy=config.get("proxy_url"),
            )
            credits = await client.get_credits()
            await client.close()
            for c in credits:
                remain = c.get("remain_quota", 0)
                init_q = c.get("init_quota", 0)
                total_remain += remain
                total_init += init_q
                details.append({
                    "email": tk.get("email", "unknown"),
                    "sub_type": c.get("sub_type", ""),
                    "remain_quota": remain,
                    "init_quota": init_q,
                    "remain_days": c.get("remain_days", 0),
                    "from_date": c.get("from_date", ""),
                    "to_date": c.get("to_date", ""),
                })
        except Exception as e:
            details.append({
                "email": tk.get("email", "unknown"),
                "error": str(e),
            })
    return {
        "success": True,
        "total_remain": round(total_remain, 2),
        "total_init": total_init,
        "token_count": len(tokens),
        "details": details,
    }


# ─── Token management ──────────────────────────────────────────
@app.get("/api/tokens")
async def get_tokens(authorized: bool = Depends(admin_dependency)):
    tokens = config.get("tokens", [])
    return {"success": True, "data": tokens}


class AutoEmailRequest(BaseModel):
    authorization: str


@app.post("/api/user/auto-email")
async def api_auto_email(req: AutoEmailRequest, authorized: bool = Depends(admin_dependency)):
    """根据 Authorization 自动获取邮箱"""
    try:
        client = FlowithClient(req.authorization, proxy=config.get("proxy_url"))
        info = await client.get_user_info()
        await client.close()
        email = info.get("email", "")
        if email:
            return {"success": True, "email": email, "username": info.get("user_metadata", {}).get("preferred_username", "")}
        return {"success": False, "message": "未能获取到邮箱"}
    except Exception as e:
        return {"success": False, "message": f"获取失败: {str(e)}"}


class RefreshAtRequest(BaseModel):
    refresh_token: str


@app.post("/api/token/refresh")
async def api_refresh_at(req: RefreshAtRequest, authorized: bool = Depends(admin_dependency)):
    """用 RT 刷新 AT"""
    try:
        from flowith_client import refresh_access_token_sync
        data = refresh_access_token_sync(req.refresh_token, proxy=config.get("proxy_url"))
        return {
            "success": True,
            "access_token": data.get("access_token", ""),
            "refresh_token": data.get("refresh_token", ""),
            "expires_in": data.get("expires_in", 0),
            "email": data.get("user", {}).get("email", ""),
        }
    except Exception as e:
        return {"success": False, "message": f"刷新失败: {str(e)}"}


@app.post("/api/token/from-rt")
async def api_token_from_rt(req: RefreshAtRequest, authorized: bool = Depends(admin_dependency)):
    """直接输入 RT，自动获取 AT + 邮箱，返回完整 token 信息"""
    try:
        from flowith_client import refresh_access_token_sync
        data = refresh_access_token_sync(req.refresh_token, proxy=config.get("proxy_url"))
        at = f"Bearer {data['access_token']}"

        # use client to get info
        client = FlowithClient(authorization=at, refresh_token=data.get("refresh_token", req.refresh_token), proxy=config.get("proxy_url"))
        info, credits = await asyncio.gather(
            client.get_user_info(),
            client.get_credits(),
            return_exceptions=True,
        )
        await client.close()

        email = ""
        user_data = {}
        if isinstance(info, dict):
            email = info.get("email", "")
            meta = info.get("user_metadata", {})
            user_data = {
                "preferred_username": meta.get("preferred_username", ""),
                "avatar_url": meta.get("avatar_url", ""),
                "provider": info.get("app_metadata", {}).get("provider", ""),
            }

        credit_info = {}
        if isinstance(credits, list) and credits:
            c = credits[0]
            credit_info = {
                "remain_quota": c.get("remain_quota", 0),
                "init_quota": c.get("init_quota", 0),
                "remain_days": c.get("remain_days", 0),
                "to_date": c.get("to_date", ""),
                "allowed_tiers": (c.get("credit_policy_snapshot") or c.get("policy_summary") or {}).get("allowed_model_tiers", []),
            }

        return {
            "success": True,
            "email": email,
            "authorization": at,
            "refresh_token": data.get("refresh_token", req.refresh_token),
            "expires_in": data.get("expires_in", 0),
            "user": user_data,
            "credits": credit_info,
        }
    except Exception as e:
        return {"success": False, "message": f"处理失败: {str(e)}"}


class TokenAddRequest(BaseModel):
    email: str
    authorization: str
    note: str = ""
    refresh_token: str = ""


@app.post("/api/tokens")
async def add_token(req: TokenAddRequest, authorized: bool = Depends(admin_dependency)):
    tokens = config.get("tokens", [])
    tokens.append({
        "id": str(uuid.uuid4()),
        "email": req.email,
        "authorization": req.authorization,
        "refresh_token": req.refresh_token or "",
        "note": req.note,
        "created_at": datetime.now().isoformat(),
        "enabled": True,
    })
    config.set("tokens", tokens)
    return {"success": True}


@app.delete("/api/tokens/{token_id}")
async def delete_token(token_id: str, authorized: bool = Depends(admin_dependency)):
    tokens = config.get("tokens", [])
    tokens = [t for t in tokens if t.get("id") != token_id]
    config.set("tokens", tokens)
    return {"success": True}


class TokenToggleRequest(BaseModel):
    enabled: bool


@app.put("/api/tokens/{token_id}/toggle")
async def toggle_token(token_id: str, req: TokenToggleRequest, authorized: bool = Depends(admin_dependency)):
    tokens = config.get("tokens", [])
    for t in tokens:
        if t.get("id") == token_id:
            t["enabled"] = req.enabled
            break
    config.set("tokens", tokens)
    return {"success": True}


class ImportTokensRequest(BaseModel):
    tokens: list


@app.post("/api/tokens/import")
async def import_tokens(req: ImportTokensRequest, authorized: bool = Depends(admin_dependency)):
    existing = config.get("tokens", [])
    for tk in req.tokens:
        existing.append({
            "id": str(uuid.uuid4()),
            "email": tk.get("email", ""),
            "authorization": tk.get("authorization", ""),
            "note": tk.get("note", ""),
            "created_at": datetime.now().isoformat(),
            "enabled": True,
        })
    config.set("tokens", existing)
    return {"success": True, "count": len(req.tokens)}


# ─── Size/ratio mapping helpers ───────────────────────────────
SIZE_TO_RATIO = {
    "256x256": "1:1", "512x512": "1:1", "1024x1024": "1:1",
    "1792x1024": "16:9", "1024x1792": "9:16",
    "1536x1024": "3:2", "1024x1536": "2:3",
    "1344x768": "16:9", "768x1344": "9:16",
}

SIZE_TO_IMG_SIZE = {
    "256x256": "512", "512x512": "512",
    "1024x1024": "1k", "1792x1024": "1k", "1024x1792": "1k",
    "1536x1024": "2k", "1024x1536": "2k",
    "2048x2048": "2k",
}

QUALITY_MAP = {"standard": None, "hd": "high", "high": "high"}


# ─── OpenAI-compatible Images API ────────────────────────────
class ImageRequest(BaseModel):
    model: str = "gemini-3.1-flash-image"
    prompt: str
    n: int = 1
    size: str | None = None
    quality: str | None = None
    style: str | None = None


@app.post("/v1/images/generations")
async def images_generations(req: ImageRequest, authorized: bool = Depends(api_key_dependency)):
    tokens = config.get("tokens", [])
    active = [t for t in tokens if t.get("enabled", True)]
    if not active:
        raise HTTPException(status_code=503, detail="没有可用的 Token")

    tk = active[0]
    client = FlowithClient(
        authorization=tk.get("authorization", ""),
        refresh_token=tk.get("refresh_token", ""),
        proxy=config.get("proxy_url"),
    )

    ar = SIZE_TO_RATIO.get(req.size) if req.size else None
    img_size = SIZE_TO_IMG_SIZE.get(req.size) if req.size else None
    quality = QUALITY_MAP.get(req.quality) if req.quality else None

    messages = [{"role": "user", "content": req.prompt}]

    image_url = None
    try:
        async for event in client.generate_image(messages, req.model, aspect_ratio=ar, image_size=img_size, quality=quality, style=req.style):
            if isinstance(event, dict):
                if event.get("type") == "generated_file":
                    gf = event.get("generatedFile", {})
                    if gf.get("status") == "ready" and gf.get("url"):
                        image_url = gf["url"]
    finally:
        await client.close()

    if not image_url:
        raise HTTPException(status_code=502, detail="图片生成失败")

    return {
        "created": int(datetime.now().timestamp()),
        "data": [{"url": image_url}],
    }


class ImageEditRequest(BaseModel):
    model: str = "gemini-3.1-flash-image"
    prompt: str
    image: str  # base64
    mask: str | None = None
    size: str | None = None


@app.post("/v1/images/edits")
async def images_edits(req: ImageEditRequest, authorized: bool = Depends(api_key_dependency)):
    tokens = config.get("tokens", [])
    active = [t for t in tokens if t.get("enabled", True)]
    if not active:
        raise HTTPException(status_code=503, detail="没有可用的 Token")

    tk = active[0]
    client = FlowithClient(
        authorization=tk.get("authorization", ""),
        refresh_token=tk.get("refresh_token", ""),
        proxy=config.get("proxy_url"),
    )

    ar = SIZE_TO_RATIO.get(req.size) if req.size else None
    img_size = SIZE_TO_IMG_SIZE.get(req.size) if req.size else None

    data_url = f"data:image/png;base64,{req.image}"
    content_parts = [{"type": "text", "text": req.prompt}]
    content_parts.append({"type": "image_url", "image_url": {"url": data_url}})
    messages = [{"role": "user", "content": content_parts}]

    image_url = None
    try:
        async for event in client.generate_image(messages, req.model, aspect_ratio=ar, image_size=img_size):
            if isinstance(event, dict):
                if event.get("type") == "generated_file":
                    gf = event.get("generatedFile", {})
                    if gf.get("status") == "ready" and gf.get("url"):
                        image_url = gf["url"]
    finally:
        await client.close()

    if not image_url:
        raise HTTPException(status_code=502, detail="图片编辑失败")

    return {
        "created": int(datetime.now().timestamp()),
        "data": [{"url": image_url}],
    }


# ─── OpenAI-compatible Videos API ────────────────────────────
class VideoRequest(BaseModel):
    model: str = "veo-3.1-fast-generate"
    prompt: str
    size: str | None = None
    duration: str | None = None
    image: str | None = None  # base64 for image-to-video


@app.post("/v1/videos/generations")
async def videos_generations(req: VideoRequest, authorized: bool = Depends(api_key_dependency)):
    tokens = config.get("tokens", [])
    active = [t for t in tokens if t.get("enabled", True)]
    if not active:
        raise HTTPException(status_code=503, detail="没有可用的 Token")

    tk = active[0]
    client = FlowithClient(
        authorization=tk.get("authorization", ""),
        refresh_token=tk.get("refresh_token", ""),
        proxy=config.get("proxy_url"),
    )

    ar = SIZE_TO_RATIO.get(req.size) if req.size else None

    content_parts = [{"type": "text", "text": req.prompt}]
    if req.image:
        data_url = f"data:image/png;base64,{req.image}"
        content_parts.append({"type": "image_url", "image_url": {"url": data_url}})
    messages = [{"role": "user", "content": content_parts}]

    video_url = None
    try:
        async for event in client.generate_video(messages, req.model, aspect_ratio=ar, duration=req.duration):
            if isinstance(event, dict):
                if event.get("type") == "generated_file":
                    gf = event.get("generatedFile", {})
                    if gf.get("status") == "ready" and gf.get("url"):
                        video_url = gf["url"]
    finally:
        await client.close()

    if not video_url:
        raise HTTPException(status_code=502, detail="视频生成失败")

    return {
        "created": int(datetime.now().timestamp()),
        "data": [{"url": video_url}],
    }


# ─── OpenAI-compatible Chat API ────────────────────────────────
class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str = "deepseek-v4-flash"
    messages: list[ChatMessage]
    stream: bool = True
    tools: list | None = None
    tool_choice: str | None = None
    websearch: bool | None = None


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest, authorized: bool = Depends(api_key_dependency)):
    tokens = config.get("tokens", [])
    active = [t for t in tokens if t.get("enabled", True)]
    if not active:
        raise HTTPException(status_code=503, detail="没有可用的 Token")

    # simple round-robin: use first active token (RT auto-refresh if present)
    tk = active[0]
    messages = [{"role": m.role, "content": m.content} for m in req.messages]

    # inject tool definitions if provided
    messages = prepare_messages_with_tools(messages, req.tools)

    client = FlowithClient(
        authorization=tk.get("authorization", ""),
        refresh_token=tk.get("refresh_token", ""),
        proxy=config.get("proxy_url"),
    )

    if req.stream:

        async def generate():
            msg_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
            created = int(datetime.now().timestamp())
            # send role first
            role_data = {
                "id": msg_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": req.model,
                "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(role_data, ensure_ascii=False)}\n\n"

            full_text = ""
            full_reasoning = ""
            async for value, reasoning in client.chat_stream(messages, req.model):
                if value:
                    full_text += value
                    data = {
                        "id": msg_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": req.model,
                        "choices": [{"index": 0, "delta": {"content": value}, "finish_reason": None}],
                    }
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                if reasoning:
                    full_reasoning += reasoning
                    data = {
                        "id": msg_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": req.model,
                        "choices": [{"index": 0, "delta": {"content": "", "reasoning_content": reasoning}, "finish_reason": None}],
                    }
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

            # check for tool calls in accumulated text
            tool_calls, clean_text = parse_tool_calls(full_text)
            if tool_calls:
                tc_data = {
                    "id": msg_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": req.model,
                    "choices": [{"index": 0, "delta": {
                        "content": clean_text or None,
                        "tool_calls": [{
                            "index": i,
                            "id": f"call_{uuid.uuid4().hex[:12]}",
                            "type": "function",
                            "function": tc["function"],
                        } for i, tc in enumerate(tool_calls)],
                    }, "finish_reason": "tool_calls"}],
                }
                yield f"data: {json.dumps(tc_data, ensure_ascii=False)}\n\n"

            done = {
                "id": msg_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": req.model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls" if tool_calls else "stop"}],
            }
            yield f"data: {json.dumps(done, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

            await client.close()

        return StreamingResponse(generate(), media_type="text/event-stream")
    else:
        try:
            full_text = ""
            full_reasoning = ""
            async for value, reasoning in client.chat_stream(messages, req.model):
                full_text += value
                full_reasoning += reasoning
            await client.close()
            tool_calls, clean_text = parse_tool_calls(full_text)
            if tool_calls:
                return {
                    "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
                    "object": "chat.completion",
                    "created": int(datetime.now().timestamp()),
                    "model": req.model,
                    "choices": [{"index": 0, "message": {
                        "role": "assistant",
                        "content": clean_text or None,
                        "tool_calls": [{
                            "id": f"call_{uuid.uuid4().hex[:12]}",
                            "type": "function",
                            "function": tc["function"],
                        } for tc in tool_calls],
                    }, "finish_reason": "tool_calls"}],
                    "usage": {"prompt_tokens": -1, "completion_tokens": -1, "total_tokens": -1},
                }
            return {
                "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
                "object": "chat.completion",
                "created": int(datetime.now().timestamp()),
                "model": req.model,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": full_text}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": -1, "completion_tokens": -1, "total_tokens": -1},
            }
        except Exception as e:
            await client.close()
            raise HTTPException(status_code=502, detail=str(e))


# ─── Admin config API ──────────────────────────────────────────
@app.get("/api/admin/config")
async def get_admin_config(authorized: bool = Depends(admin_dependency)):
    return {
        "success": True,
        "data": {
            "admin_username": config.admin_username,
            "api_key": config.api_key,
            "proxy_enabled": config.get("proxy_enabled", False),
            "proxy_url": config.get("proxy_url", ""),
            "debug": config.get("debug", False),
        }
    }


class AdminConfigUpdate(BaseModel):
    api_key: str | None = None
    proxy_enabled: bool | None = None
    proxy_url: str | None = None
    debug: bool | None = None


@app.post("/api/admin/config")
async def update_admin_config(req: AdminConfigUpdate, authorized: bool = Depends(admin_dependency)):
    if req.api_key is not None:
        config.api_key = req.api_key
    if req.proxy_enabled is not None:
        config.set("proxy_enabled", req.proxy_enabled)
    if req.proxy_url is not None:
        config.set("proxy_url", req.proxy_url)
    if req.debug is not None:
        config.set("debug", req.debug)
    return {"success": True}


class PasswordChange(BaseModel):
    old_password: str
    new_password: str


@app.post("/api/admin/password")
async def change_password(req: PasswordChange, authorized: bool = Depends(admin_dependency)):
    if not bcrypt.checkpw(req.old_password.encode(), config.admin_password_hash.encode()):
        raise HTTPException(status_code=400, detail="旧密码错误")
    new_hash = bcrypt.hashpw(req.new_password.encode(), bcrypt.gensalt()).decode()
    config.admin_password_hash = new_hash
    return {"success": True}


# ─── Health ────────────────────────────────────────────────────
@app.get("/health")
async def health():
    tokens = config.get("tokens", [])
    return {
        "status": "ok",
        "token_count": len(tokens),
        "version": "1.0.0",
    }


# ─── Run ───────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=config.server_host,
        port=config.server_port,
        reload=False,
        log_level="info",
    )
