# KB-Vector-Service — Ask API 串接文件

> 供 Teams Bot 或其他服務串接 `/api/v1/ask` 使用

## API 端點

```
POST {{kbApiUrl}}/api/v1/ask?question={問題}&role={user|it}
```

| 項目 | 說明 |
|------|------|
| URL | `{{kbApiUrl}}/api/v1/ask` |
| Method | `POST` |
| 參數 | `question` (query string，必填) |
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

const response = await fetch(
  "{{kbApiUrl}}/api/v1/ask?question=VPN連線問題怎麼處理",
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

response = requests.post(
    "{{kbApiUrl}}/api/v1/ask?question=VPN連線問題怎麼處理",
    headers={"Authorization": f"Bearer {token.token}"}
)
```

---

## Request 範例

### User 模式（給一般使用者）

```http
POST /api/v1/ask?question=VPN連線問題怎麼處理&role=user HTTP/1.1
Host: kb-vector-service.azurewebsites.net
Authorization: Bearer eyJ0eXAiOiJKV1Q...
```

```bash
curl -X POST "{{kbApiUrl}}/api/v1/ask?question=VPN%E9%80%A3%E7%B7%9A%E5%95%8F%E9%A1%8C%E6%80%8E%E9%BA%BC%E8%99%95%E7%90%86&role=user" \
  -H "Authorization: Bearer {token}"
```

### IT 模式（給 IT 人員）

```bash
curl -X POST "{{kbApiUrl}}/api/v1/ask?question=VPN%E9%80%A3%E7%B7%9A%E5%95%8F%E9%A1%8C%E6%80%8E%E9%BA%BC%E8%99%95%E7%90%86&role=it" \
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
  "role": "user"
}
```

### IT 模式 (200 OK)

```json
{
  "answer": "根據工單 IT2026030210390002 的處理記錄，VPN 連線問題的排查步驟如下：\n1. 確認使用者帳號密碼正確性\n2. 檢查 VPN Client 版本是否為最新...",
  "sources": [
    {
      "id": "01DCCVIQCWBJQZEKFGUJDY5JKSU3737BCC",
      "title": "IT2026030210390002",
      "category": "03",
      "score": 0.46,
      "contentPreview": "使用者反映 VPN 無法連線，經確認為密碼過期導致..."
    }
  ],
  "role": "it"
}
```

| 欄位 | 型別 | 說明 |
|------|------|------|
| `answer` | string | AI 基於知識庫產生的繁體中文回答 |
| `sources` | array | 引用的知識庫文章來源 |
| `sources[].id` | string | SharePoint 檔案 ID |
| `sources[].title` | string | 工單編號 / 檔案名稱 |
| `sources[].category` | string | 分類（來自資料夾路徑） |
| `sources[].score` | float | 語意相似度分數 (0~1，越高越相關) |

### 查無相關資料 (200 OK)

```json
{
  "answer": "No relevant knowledge base articles found.",
  "sources": []
}
```

### 錯誤回應

| HTTP Status | 說明 |
|-------------|------|
| 400 | 缺少 `question` 參數 |
| 401 | 未帶 token 或 token 無效 |
| 403 | token 有效但 App ID 不在允許名單 |

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

    public async Task<KbAnswer> AskAsync(string question)
    {
        var token = await _credential.GetTokenAsync(
            new Azure.Core.TokenRequestContext(new[] { _scope }));

        _httpClient.DefaultRequestHeaders.Authorization =
            new AuthenticationHeaderValue("Bearer", token.Token);

        var encoded = Uri.EscapeDataString(question);
        var response = await _httpClient.PostAsync(
            $"{_baseUrl}/api/v1/ask?question={encoded}", null);

        response.EnsureSuccessStatusCode();

        var json = await response.Content.ReadAsStringAsync();
        return JsonSerializer.Deserialize<KbAnswer>(json,
            new JsonSerializerOptions { PropertyNameCaseInsensitive = true })!;
    }
}

public class KbAnswer
{
    public string Answer { get; set; } = "";
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
var result = await kbClient.AskAsync(userMessage);
await turnContext.SendActivityAsync(result.Answer);
```

---

## 注意事項

- API 啟動後需先呼叫 `POST /api/v1/sync` 同步知識庫（向量存記憶體，重啟後需重新同步）
- `answer` 為 GPT 根據知識庫內容產生，回覆語言為繁體中文
- `sources` 中的 `score` 可用於判斷回答可信度（建議 > 0.3 才視為可靠）
- 新增串接服務只需：**取得 App ID** → **加入允許名單**

### Azure AD 前置設定（一次性）

若 `api://de281045-d27f-4549-972a-0b331178668a` 尚未設定：

1. Azure Portal → **App registrations** → 找到 KB-Vector-Service App
2. **Expose an API** → Set Application ID URI → `api://de281045-d27f-4549-972a-0b331178668a`
3. **Add a scope** → `access_as_app` → Admins only → 儲存
