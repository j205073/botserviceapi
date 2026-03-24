# KB-Vector-Service — Ask API 串接文件

> 供 Teams Bot 或其他服務串接 `/api/v1/{kb}/ask` 使用

## API 端點

### 多知識庫版本（推薦）

```
GET  {{kbApiUrl}}/api/v1/kbs                              → 列出有權存取的知識庫
POST {{kbApiUrl}}/api/v1/{kb}/sync                        → 同步指定知識庫
POST {{kbApiUrl}}/api/v1/{kb}/ask?question={問題}&role={user|it}  → 問答指定知識庫
```

### 向後相容版本（使用預設知識庫）

```
POST {{kbApiUrl}}/api/v1/ask?question={問題}&role={user|it}
```

| 項目 | 說明 |
|------|------|
| URL | `{{kbApiUrl}}/api/v1/{kb}/ask` |
| Method | `POST` |
| 參數 | `kb` (URL path，知識庫 slug，如 `it-kb`) |
| | `question` (query string，必填) |
| | `role` (query string，選填，預設 `user`) |
| 認證 | Azure AD Bearer Token |
| 回應格式 | JSON |

> 正式環境 `kbApiUrl` = `https://kb-vector-service.azurewebsites.net`

### role 參數說明

| 值 | 語氣 | 回覆風格 | sources 內容 |
|----|------|----------|-------------|
| `user`（預設） | 親切友善 | 通俗易懂，避免術語，像跟同事聊天 | 僅 title + category |
| `it` | 專業詳細 | 明確指出根據哪份文件，列出處理步驟 | 完整（id、score、contentPreview） |

---

## 認證方式

本 API 使用 **Azure AD** 驗證，僅允許已授權的應用程式呼叫。

### 方法一：Managed Identity（推薦，免管金鑰）

適用於部署在 Azure 上的服務（App Service、Azure Functions 等）。

**設定步驟：**

1. Azure Portal → 你的 Web App → **Identity** → System assigned → **On**
2. 記下產生的 Object ID，查詢 App ID：
   ```bash
   az ad sp show --id <Object-ID> --query appId -o tsv
   ```
3. 將 App ID 加入 KB-Vector-Service 允許名單：
   ```bash
   az webapp config appsettings set \
     --name kb-vector-service \
     --resource-group RinnaiResource \
     --settings Auth__AllowedClientIds__N="<App-ID>"
   ```
   > `__0` 已被 Teams Bot 使用，請用 `__1`、`__2` 依序遞增。

4. （選擇性）若要限制該 client 只能存取特定知識庫，將 App ID 加入該 KB 的 `AllowedClientIds`。

**程式碼（C#）：**

```csharp
using Azure.Identity;
using System.Net.Http.Headers;

var credential = new ManagedIdentityCredential();
var token = await credential.GetTokenAsync(
    new Azure.Core.TokenRequestContext(
        new[] { "api://de281045-d27f-4549-972a-0b331178668a/.default" }
    ));

httpClient.DefaultRequestHeaders.Authorization =
    new AuthenticationHeaderValue("Bearer", token.Token);
```

### 方法二：Client Credentials（非 Azure 環境或本機開發）

**設定步驟：**

1. Azure Portal → **Azure AD** → **App registrations** → **New registration** → 記下 App ID
2. 進入新 App → **Certificates & secrets** → **New client secret** → 複製 Value
3. 將 App ID 加入允許名單（同上）

**程式碼（C#）：**

```csharp
var credential = new ClientSecretCredential(
    tenantId: "36256584-c642-40f2-89a0-89fb18d5c887",
    clientId: "<你的-App-ID>",
    clientSecret: "<你的-Client-Secret>"
);
var token = await credential.GetTokenAsync(
    new Azure.Core.TokenRequestContext(
        new[] { "api://de281045-d27f-4549-972a-0b331178668a/.default" }
    ));
```

**Node.js：**

```javascript
const { ClientSecretCredential } = require("@azure/identity");

const credential = new ClientSecretCredential(
  "36256584-c642-40f2-89a0-89fb18d5c887",
  "<你的-App-ID>",
  "<你的-Client-Secret>"
);
const token = await credential.getToken(
  "api://de281045-d27f-4549-972a-0b331178668a/.default"
);

// 先查詢有哪些知識庫
const kbs = await fetch("{{kbApiUrl}}/api/v1/kbs", {
  headers: { Authorization: `Bearer ${token.token}` }
}).then(r => r.json());

// 對指定知識庫提問
const response = await fetch(
  "{{kbApiUrl}}/api/v1/it-kb/ask?question=VPN連線問題怎麼處理",
  { method: "POST", headers: { Authorization: `Bearer ${token.token}` } }
);
```

**Python：**

```python
from azure.identity import ClientSecretCredential
import requests

credential = ClientSecretCredential(
    tenant_id="36256584-c642-40f2-89a0-89fb18d5c887",
    client_id="<你的-App-ID>",
    client_secret="<你的-Client-Secret>"
)
token = credential.get_token("api://de281045-d27f-4549-972a-0b331178668a/.default")

# 列出有權存取的知識庫
kbs = requests.get(
    "{{kbApiUrl}}/api/v1/kbs",
    headers={"Authorization": f"Bearer {token.token}"}
).json()

# 對指定知識庫提問
response = requests.post(
    "{{kbApiUrl}}/api/v1/it-kb/ask?question=VPN連線問題怎麼處理&role=user",
    headers={"Authorization": f"Bearer {token.token}"}
)
```

---

## Request 範例

### 列出知識庫

```http
GET /api/v1/kbs HTTP/1.1
Host: kb-vector-service.azurewebsites.net
Authorization: Bearer eyJ0eXAiOiJKV1Q...
```

### User 模式（給一般使用者）

```http
POST /api/v1/it-kb/ask?question=VPN連線問題怎麼處理&role=user HTTP/1.1
Host: kb-vector-service.azurewebsites.net
Authorization: Bearer eyJ0eXAiOiJKV1Q...
```

### IT 模式（給 IT 人員）

```bash
curl -X POST "{{kbApiUrl}}/api/v1/it-kb/ask?question=VPN%E9%80%A3%E7%B7%9A%E5%95%8F%E9%A1%8C%E6%80%8E%E9%BA%BC%E8%99%95%E7%90%86&role=it" \
  -H "Authorization: Bearer {token}"
```

---

## Response 格式

### User 模式 (200 OK)

```json
{
  "answer": "嗨！VPN 連不上的話，可以先試試以下方法：\n1. 確認帳號密碼有沒有打錯\n2. 檢查網路連線是不是正常的\n3. 如果還是不行，可以聯繫 IT 同仁幫忙看看喔！",
  "sources": [
    {
      "title": "IT2026030210390002",
      "category": "03"
    }
  ],
  "role": "user",
  "kb": "it-kb"
}
```

### IT 模式 (200 OK)

```json
{
  "answer": "根據工單 IT2026030210390002 的處理記錄，VPN 連線問題的排查步驟如下：...",
  "sources": [
    {
      "id": "01DCCVIQCWBJQZEKFGUJDY5JKSU3737BCC",
      "title": "IT2026030210390002",
      "category": "03",
      "score": 0.46,
      "contentPreview": "使用者反映 VPN 無法連線，經確認為密碼過期導致..."
    }
  ],
  "role": "it",
  "kb": "it-kb"
}
```

| 欄位 | 型別 | 說明 |
|------|------|------|
| `answer` | string | AI 基於知識庫產生的繁體中文回答 |
| `sources` | array | 引用的知識庫文章來源 |
| `role` | string | 使用的角色模式 |
| `kb` | string | 使用的知識庫 slug |

### 查無相關資料 (200 OK)

```json
{
  "answer": "抱歉，目前找不到相關的資料，建議您聯繫 IT 人員協助處理喔！",
  "sources": [],
  "role": "user",
  "kb": "it-kb"
}
```

### 錯誤回應

| HTTP Status | 說明 |
|-------------|------|
| 400 | 缺少 `question` 參數 |
| 401 | 未帶 token 或 token 無效 |
| 403 | token 有效但無權存取（App ID 不在允許名單，或無權存取該 KB） |
| 404 | 知識庫 slug 不存在 |

---

## 完整串接範例（C#）

```csharp
using Azure.Identity;
using System.Net.Http.Headers;
using System.Text.Json;

public class KbVectorClient
{
    private readonly HttpClient _httpClient;
    private readonly string _baseUrl;
    private readonly ManagedIdentityCredential _credential;
    private readonly string _scope;

    public KbVectorClient(string baseUrl)
    {
        _httpClient = new HttpClient();
        _baseUrl = baseUrl.TrimEnd('/');
        _credential = new ManagedIdentityCredential();
        _scope = "api://de281045-d27f-4549-972a-0b331178668a/.default";
    }

    private async Task EnsureAuthAsync()
    {
        var token = await _credential.GetTokenAsync(
            new Azure.Core.TokenRequestContext(new[] { _scope }));
        _httpClient.DefaultRequestHeaders.Authorization =
            new AuthenticationHeaderValue("Bearer", token.Token);
    }

    public async Task<KbInfo[]> ListKbsAsync()
    {
        await EnsureAuthAsync();
        var response = await _httpClient.GetAsync($"{_baseUrl}/api/v1/kbs");
        response.EnsureSuccessStatusCode();
        var json = await response.Content.ReadAsStringAsync();
        return JsonSerializer.Deserialize<KbInfo[]>(json,
            new JsonSerializerOptions { PropertyNameCaseInsensitive = true })!;
    }

    public async Task<KbAnswer> AskAsync(string kbSlug, string question, string role = "user")
    {
        await EnsureAuthAsync();
        var encoded = Uri.EscapeDataString(question);
        var response = await _httpClient.PostAsync(
            $"{_baseUrl}/api/v1/{kbSlug}/ask?question={encoded}&role={role}", null);
        response.EnsureSuccessStatusCode();
        var json = await response.Content.ReadAsStringAsync();
        return JsonSerializer.Deserialize<KbAnswer>(json,
            new JsonSerializerOptions { PropertyNameCaseInsensitive = true })!;
    }
}

public class KbInfo
{
    public string Slug { get; set; } = "";
    public string DisplayName { get; set; } = "";
}

public class KbAnswer
{
    public string Answer { get; set; } = "";
    public string Kb { get; set; } = "";
    public string Role { get; set; } = "";
    public List<KbSource> Sources { get; set; } = new();
}

public class KbSource
{
    public string Id { get; set; } = "";
    public string Title { get; set; } = "";
    public string Category { get; set; } = "";
    public float Score { get; set; }
}
```

### 在 Bot 中使用

```csharp
var kbClient = new KbVectorClient("https://kb-vector-service.azurewebsites.net");

// 列出可用知識庫
var kbs = await kbClient.ListKbsAsync();

// 對指定知識庫提問
var result = await kbClient.AskAsync("it-kb", userMessage);
await turnContext.SendActivityAsync(result.Answer);
```

---

## 知識庫權限控管

每個知識庫可設定 `AllowedClientIds` 來限制存取：

| 設定 | 效果 |
|------|------|
| `AllowedClientIds: []`（空） | 所有已認證的 client 都能存取 |
| `AllowedClientIds: ["xxx-..."]` | 只有列出的 client app ID 能存取 |

設定方式（Azure 環境變數）：

```bash
# 讓 HR KB 只允許特定 client 存取
MSYS_NO_PATHCONV=1 az webapp config appsettings set \
  --name kb-vector-service \
  --resource-group RinnaiResource \
  --settings "KnowledgeBases__1__AllowedClientIds__0=<App-ID>"
```

---

## 注意事項

- API 啟動後需先呼叫 `POST /api/v1/{kb}/sync` 同步知識庫（向量存記憶體，重啟後需重新同步）
- `answer` 為 GPT 根據知識庫內容產生，回覆語言為繁體中文
- `sources` 中的 `score` 可用於判斷回答可信度（建議 > 0.3 才視為可靠）
- 新增串接服務只需：**取得 App ID** → **加入允許名單**

### Azure AD 前置設定（一次性）

若 `api://de281045-d27f-4549-972a-0b331178668a` 尚未設定：

1. Azure Portal → **App registrations** → 找到 KB-Vector-Service App
2. **Expose an API** → Set Application ID URI → `api://de281045-d27f-4549-972a-0b331178668a`
3. **Add a scope** → `access_as_app` → Admins only → 儲存
