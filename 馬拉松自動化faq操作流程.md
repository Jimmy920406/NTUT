# 建立自動化faq
### 請把所有taipei_marathon_history換成歷史紀錄table的名稱
---
## cmd暫時連接supabase帳號
**需要先去 Supabase 產生一把鑰匙，讓 CMD 暫時擁有權限。**：

- **到 Supabase**
- **點擊左下角的 使用者頭像 -> Account Settings (帳號設定)。**
- **點擊 Access Tokens。**
- **點擊右上角 Generate new token。**
- **隨便取個名字（例如：Temp Deploy），按 Generate。**
- **複製那串以 sbp_ 開頭的密鑰 (這串只會出現一次，請複製好)。**

**取得「目標專案 ID」 (Project Reference)** ：

- **進入你「現在要上傳」的那個專案。**
- **看瀏覽器的網址列，網址結構是 https://supabase.com/dashboard/project/abcdefghijklm。**
- **後面那串亂碼 abcdefghijklm 就是你的 Project ID (Project Reference)。**

**在 CMD 執行**

- **開一個新的 CMD (命令提示字元) 視窗。**
- **假設你的程式碼資料夾在 C:\Users\You\my-project**：
```dos
cd path\to\your\folder
```
- **(請確保這個資料夾裡面有 supabase 資料夾，且裡面有 functions/auto-faq)**
- **請將 sbp_xxxx 換成你在第一步複製的鑰匙。**:
```dos
set SUPABASE_ACCESS_TOKEN=sbp_你的金鑰貼在這裡
```
- **請將 your_project_id 換成你在第二步找到的 ID。 我們加上 --project-ref 參數，強迫它對準新專案**:
```dos
npx supabase functions deploy auto-faq --project-ref your_project_id --no-verify-jwt
```

---
## 新增欄位來標記是否已轉為 FAQ

```sql
alter table taipei_marathon_history  -- 請自行改成歷史紀錄table的名稱
add column if not exists is_processed boolean default false;
```
---
## 建立Edge Function
### 部署：npx supabase functions deploy auto-faq --no-verify-jwt
#### 部署成功後，終端機會顯示一行網址，請務必複製下來！ 格式會像這樣：https://[你的專案ID].supabase.co/functions/v1/auto-faq

```typescript
// 檔案位置: supabase/functions/auto-faq/index.ts
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'

const OPENAI_API_URL = "https://api.openai.com/v1/embeddings";

Deno.serve(async (req) => {
  try {
    const { record } = await req.json();

    // 1. 基本檢查
    if (!record || record.who !== 'chatbot') {
      return new Response(JSON.stringify({ message: "Skipped" }), { headers: { "Content-Type": "application/json" } });
    }

    // 2. 檢查是否已經處理過 (避免重複觸發)
    // 注意：如果是舊系統剛升級，這個欄位可能是 null，所以檢查 false 或 null
    if (record.is_processed === true) {
      return new Response(JSON.stringify({ message: "Already processed" }), { headers: { "Content-Type": "application/json" } });
    }

    const supabase = createClient(
      Deno.env.get('SUPABASE_URL') ?? '',
      Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') ?? ''
    );

    // 3. 找上一句使用者的話
    const { data: prevMsg, error: fetchError } = await supabase
      .from('taipei_marathon_history')
      .select('*')
      .lt('id', record.id)
      .order('id', { ascending: false })
      .limit(1)
      .single();

    if (fetchError || !prevMsg || prevMsg.who !== 'people') {
      // 即使找不到對應問題，也標記為已處理，以免未來反覆錯誤嘗試
      await supabase.from('taipei_marathon_history').update({ is_processed: true }).eq('id', record.id);
      return new Response(JSON.stringify({ message: "No user question found, marked as processed." }), { headers: { "Content-Type": "application/json" } });
    }

    const userQuestion = prevMsg.message;
    const botAnswer = record.message;
    
    // 清洗與過濾
    let cleanQuestion = userQuestion
      .replace(/^關於台北馬拉松.*?[，,]/, "") 
      .replace(/[，,]請翻閱知識庫回答[。.]?$/, "")
      .trim();

    // 4. 呼叫 OpenAI 產生 Embedding
    const apiKey = Deno.env.get('OPENAI_API_KEY');
    const embedResponse = await fetch(OPENAI_API_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${apiKey}`
      },
      body: JSON.stringify({
        model: "text-embedding-3-large",
        input: cleanQuestion
      })
    });
    
    const embedData = await embedResponse.json();
    
    if (!embedData.data) {
       console.error("OpenAI Error", embedData);
       return new Response(JSON.stringify({ error: "Embedding failed" }), { status: 500 });
    }
    
    const vector = embedData.data[0].embedding;

    // 5. 檢查重複與寫入 FAQ
    const { data: duplicates } = await supabase.rpc('match_faq', {
      query_embedding: vector,
      match_threshold: 0.92,
      match_count: 1
    });

    if (!duplicates || duplicates.length === 0) {
      await supabase.from('faq').insert({
        question: cleanQuestion,
        answer: botAnswer,
        embedding: vector
      });
      console.log(`Added FAQ: ${cleanQuestion}`);
    } else {
      console.log(`Duplicate skipped: ${cleanQuestion}`);
    }

    // 6. 【關鍵新增】將該筆紀錄標記為已處理
    await supabase.from('taipei_marathon_history')
      .update({ is_processed: true })
      .eq('id', record.id);

    return new Response(JSON.stringify({ success: true }), { headers: { "Content-Type": "application/json" } });

  } catch (err) {
    console.error(err);
    return new Response(JSON.stringify({ error: err.message }), { status: 500 });
  }
});
```
---
## 建立 Trigger
### 把複製的網址貼到下面的程式碼

```sql
-- 1. 啟用網路請求功能
create extension if not exists pg_net;

-- 2. 建立觸發函式 (Function)
create or replace function trigger_auto_faq()
returns trigger
language plpgsql
security definer
as $$
declare
  -- 請將下方引號內的網址，換成您剛剛部署時拿到的 Edge Function URL
  -- 範例格式： https://abcdefg.supabase.co/functions/v1/auto-faq
  edge_function_url text := 'https://您的專案ID.supabase.co/functions/v1/auto-faq';
begin
  -- 只有當chatbot回答時，才觸發
  if NEW.who = 'chatbot' then
    perform
      net.http_post(
        url := edge_function_url,
        headers := '{"Content-Type": "application/json"}'::jsonb,
        body := json_build_object('record', row_to_json(NEW))::jsonb
      );
  end if;
  return NEW;
end;
$$;

-- 3. 建立觸發器 (Trigger)
-- 這段指令會把上面的函式「綁定」到 taipei_marathon_history 表格上
drop trigger if exists on_chat_created on taipei_marathon_history;

create trigger on_chat_created
  after insert on taipei_marathon_history
  for each row
  execute function trigger_auto_faq();
```

---
## 設定金鑰與網址串接 (Supabase Dashboard)
**設定 OpenAI Key**：

- **到 Supabase**
- **點選左側 Edge Functions -> 點選 auto-faq。**
- **點選 Secrets (或 Manage Secrets)。**
- **點選 Add new secret**：Name: OPENAI_API_KEY, Value: sk-xxxxxxxxx (您的 OpenAI API Key)

---
## 處理原本table的歷史紀錄
### 因為 Function 只會處理「未來」的資料，對於「過去」的資料，我們需要手動處理

```python
import os
from supabase import create_client, Client
from openai import OpenAI

# --- 設定區 ---
SUPABASE_URL = "您的_SUPABASE_URL"
SUPABASE_KEY = "您的_SUPABASE_SERVICE_ROLE_KEY" # 必須用 Service Role Key
OPENAI_API_KEY = "您的_OPENAI_API_KEY"

# 初始化
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
client = OpenAI(api_key=OPENAI_API_KEY)

def get_embedding(text):
    response = client.embeddings.create(
        input=text,
        model="text-embedding-3-large"
    )
    return response.data[0].embedding

def backfill_history():
    print("開始掃描未處理的歷史紀錄...")
    
    # 1. 抓取未處理的 Chatbot 回應
    # 這裡一次抓 100 筆，避免記憶體爆掉，可以迴圈執行
    response = supabase.table("taipei_marathon_history")\
        .select("*")\
        .eq("who", "chatbot")\
        .eq("is_processed", False)\
        .limit(100)\
        .execute()
    
    logs = response.data
    if not logs:
        print("沒有發現未處理的紀錄。")
        return

    print(f"找到 {len(logs)} 筆資料，開始處理...")

    for log in logs:
        bot_msg = log['message']
        current_id = log['id']
        
        # 2. 找上一句 User 提問
        # 邏輯：找 id 小於 current_id 的最後一筆 people 發言
        prev_res = supabase.table("taipei_marathon_history")\
            .select("*")\
            .lt("id", current_id)\
            .order("id", desc=True)\
            .limit(1)\
            .execute()
            
        if prev_res.data and prev_res.data[0]['who'] == 'people':
            user_msg = prev_res.data[0]['message']
            
            # 清洗
            clean_q = user_msg.replace("關於台北馬拉松的所有賽事有些相關問題想請教，", "")\
                              .replace("，請翻閱知識庫回答。", "").strip()
            
            if len(clean_q) > 1 and "無法提供回覆" not in bot_msg:
                try:
                    # 轉向量
                    vector = get_embedding(clean_q)
                    
                    # 檢查重複 (呼叫資料庫 RPC)
                    dup_check = supabase.rpc("match_faq", {
                        "query_embedding": vector,
                        "match_threshold": 0.95,
                        "match_count": 1
                    }).execute()
                    
                    if not dup_check.data:
                        # 寫入 FAQ
                        supabase.table("faq").insert({
                            "question": clean_q,
                            "answer": bot_msg,
                            "embedding": vector
                        }).execute()
                        print(f"[新增] {clean_q}")
                    else:
                        print(f"[重複] {clean_q}")
                except Exception as e:
                    print(f"Error processing {clean_q}: {e}")
            
        # 3. 標記為已處理 (無論成功失敗都標記，避免卡住)
        supabase.table("taipei_marathon_history").update({"is_processed": True}).eq("id", current_id).execute()

if __name__ == "__main__":
    # 您可以用迴圈讓他一直跑，直到處理完所有資料
    while True:
        try:
            backfill_history()
            # 如果想一次跑完，可以判斷如果沒資料就 break
            # break 
        except Exception as e:
            print(f"發生錯誤: {e}")
            break
```
---