# NotebookLM 反爬补强 Patch 记录

**版本**: notebooklm-py 0.3.4  
**修改时间**: 2026-04-27  
**目的**: 引入 notebooklm-client (Node.js/TS) 的反爬技术，解决 PPT 生成质量下降和请求失败问题

---

## 修改文件清单

| 文件 | 修改内容 |
|------|---------|
| `_core.py` | Chrome 特征请求头、请求ID随机抖动、网络错误指数退避重试 |
| `auth.py` | `fetch_tokens()` 增加 Chrome 特征请求头 |
| `client.py` | `refresh_auth()` 增加 Chrome 特征请求头 |

---

## 1. _core.py 修改详情

### 1.1 新增导入和常量

```python
import random  # 新增

# Chrome 131 特征请求头（反爬对抗）
CHROME_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "X-Same-Domain": "1",
    "Origin": "https://notebooklm.google.com",
    "Referer": "https://notebooklm.google.com/",
}

# 网络错误重试配置
NETWORK_RETRY_MAX_ATTEMPTS = 3
NETWORK_RETRY_INITIAL_DELAY = 2.0
NETWORK_RETRY_MAX_DELAY = 30.0
NETWORK_RETRY_BACKOFF_MULTIPLIER = 2.0
```

### 1.2 open() 方法：合并 Chrome 特征头

```python
async def open(self) -> None:
    if self._http_client is None:
        timeout = httpx.Timeout(...)
        # 合并 Chrome 特征头 + 认证头
        headers = {
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "Cookie": self.auth.cookie_header,
        }
        headers.update(CHROME_HEADERS)
        self._http_client = httpx.AsyncClient(headers=headers, timeout=timeout)
```

### 1.3 请求ID随机抖动

```python
# 初始化时增加随机偏移
self._reqid_counter: int = 100000 + random.randint(0, 50000)
```

### 1.4 rpc_call() 网络错误重试

新增 `_network_attempt` 参数，对 `httpx.RequestError`（超时、连接错误等）实施指数退避重试：

- 最多重试 3 次
- 初始延迟 2s，每次翻倍，最高 30s
- 增加 ±20% 随机抖动避免 thundering herd

```python
delay = min(
    NETWORK_RETRY_INITIAL_DELAY * (NETWORK_RETRY_BACKOFF_MULTIPLIER ** _network_attempt),
    NETWORK_RETRY_MAX_DELAY,
)
delay = delay * (0.8 + random.random() * 0.4)  # jitter
```

---

## 2. auth.py 修改详情

### 2.1 fetch_tokens() 增加 Chrome 特征头

```python
async def fetch_tokens(cookies: dict[str, str]) -> tuple[str, str]:
    headers = {
        "Cookie": cookie_header,
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 ...",
        "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Accept": "text/html,application/xhtml+xml...",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Upgrade-Insecure-Requests": "1",
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://notebooklm.google.com/",
            headers=headers,
            follow_redirects=True,
            timeout=30.0,
        )
```

---

## 3. client.py 修改详情

### 3.1 refresh_auth() 增加 Chrome 特征头

```python
async def refresh_auth(self) -> AuthTokens:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 ...",
        "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Accept": "text/html...",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Upgrade-Insecure-Requests": "1",
    }
    response = await http_client.get("https://notebooklm.google.com/", headers=headers)
```

---

## 4. curl-impersonate 备选方案（未安装）

如果未来遇到 `CookieMismatch` 或 401/403 持续失败，需要：

1. 安装 curl-impersonate：`brew install curl-impersonate`
2. 在 `auth.py` 的 `fetch_tokens()` 中增加 curl-impersonate 分支
3. 参考 notebooklm-client 的 `session-store.ts` 实现

当前系统未安装 curl-impersonate，暂不使用。

---

## 5. 如何重新应用 Patch

如果 notebooklm-py 被重新安装（如升级版本），需要重新应用这些修改：

```bash
# 1. 找到备份文件
cp /tmp/notebooklm_core_patched.py .venv/lib/python3.11/site-packages/notebooklm/_core.py
cp /tmp/notebooklm_auth_patched.py .venv/lib/python3.11/site-packages/notebooklm/auth.py
cp /tmp/notebooklm_client_patched.py .venv/lib/python3.11/site-packages/notebooklm/client.py

# 2. 验证语法
python3 -m py_compile .venv/lib/python3.11/site-packages/notebooklm/_core.py
python3 -m py_compile .venv/lib/python3.11/site-packages/notebooklm/auth.py
python3 -m py_compile .venv/lib/python3.11/site-packages/notebooklm/client.py
```

---

## 6. 预期效果

| 问题 | 修复方式 |
|------|---------|
| 请求被识别为自动化脚本 | Chrome 特征请求头模拟真实浏览器 |
| 请求ID序列被追踪 | 随机初始化 + 抖动 |
| 网络超时导致任务失败 | 指数退避重试（最多3次） |
| Token 获取阶段被拦截 | fetch_tokens 增加完整浏览器特征 |
| Token 刷新阶段被拦截 | refresh_auth 增加完整浏览器特征 |
