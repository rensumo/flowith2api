# Flowith2API

将 [Flowith.io](https://flowith.io) 的 AI 对话能力转为 OpenAI 兼容 API，附带 Web 管理面板。

## 特性

- ✅ **OpenAI 兼容 API** — 支持 `/v1/chat/completions` 和 `/v1/models`
- ✅ **流式/非流式** — SSE 流式推送，支持 `stream: true/false`
- ✅ **思维链** — 自动剥离 `<think>` 标签，通过 `reasoning_content` 字段返回
- ✅ **工具调用** — XML 格式工具调用自动转为 OpenAI `tool_calls` 格式
- ✅ **RT → AT 自动刷新** — 输入 Refresh Token 自动获取 Access Token
- ✅ **积分查询** — 实时查询 Flowith Credits
- ✅ **模型列表** — 按用户层级自动过滤可用模型
- ✅ **Web 管理面板** — 登录页 + Token 管理 + 积分概览 + 可用模型 + 系统配置
- ✅ **代理支持** — HTTP/SOCKS5 代理
- ✅ **AT 自动续期** — Access Token 过期前自动用 Refresh Token 刷新

## 快速开始

```bash
git clone https://github.com/rensumo/flowith2api.git
cd flowith2api
pip install -r requirements.txt
python main.py
```

访问 `http://localhost:8000`，默认账号 `admin / admin`。

## API 使用

### 对话

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-flowith" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-v4-flash",
    "messages": [{"role": "user", "content": "你好"}],
    "stream": true
  }'
```

### 获取模型列表

```bash
curl http://localhost:8000/v1/models \
  -H "Authorization: Bearer sk-flowith"
```

### 工具调用

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-flowith" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-v4-flash",
    "messages": [{"role": "user", "content": "北京的天气怎么样？"}],
    "tools": [{
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "获取指定城市的天气",
        "parameters": {
          "type": "object",
          "properties": {
            "location": {"type": "string", "description": "城市名称"}
          },
          "required": ["location"]
        }
      }
    }]
  }'
```

## 管理面板

| 功能 | 说明 |
|------|------|
| **Token 管理** | 添加/删除/启用禁用 Token，支持 AT 和 RT 两种输入模式 |
| **积分概览** | 查看各 Token 的剩余积分、层级、有效期 |
| **可用模型** | 按用户层级自动过滤并展示可用模型列表 |
| **系统配置** | 修改密码、API Key、代理设置 |

### 添加 Token

**方式一：输入 AT**
直接粘贴 `Authorization` 头中的完整 JWT，点「自动获取」可获取邮箱。

**方式二：输入 RT**
粘贴 Refresh Token，点击「刷新并获取信息」自动获取 AT + 邮箱 + 积分。

## 环境要求

- Python 3.8+
- 依赖见 `requirements.txt`

## 配置说明

默认 API Key: `sk-flowith`
默认管理员: `admin / admin`

代理设置在管理面板「系统配置」中配置。

## 项目结构

```
flowith2api/
├── main.py              # FastAPI 主服务
├── flowith_client.py    # Flowith API 客户端
├── config.py            # 配置管理
├── tool_handler.py      # XML 工具调用处理
├── requirements.txt     # Python 依赖
├── static/
│   ├── login.html       # 登录页
│   └── manage.html      # 管理面板
└── data/                # 运行时数据（自动生成）
```

## 免责声明

本项目仅供学习和研究用途。使用本项目时请遵守相关服务条款。
