# 建立自動化faq
### 請把所有taipei_marathon_history換成歷史紀錄table的名稱
---
## 建立faq的table
```sql
-- 1. 啟用向量擴充套件 (如果還沒開過)
create extension if not exists vector;

-- 2. 建立 FAQ 表格
-- 設定為 1536 維度，對應 OpenAI text-embedding-3-large 模型
create table if not exists faq (
  id bigserial primary key,
  question text not null,       -- 標準問題
  answer text not null,         -- 標準答案
  embedding vector(1536),       -- 向量資料
  created_at timestamptz default now()
);

-- 3. 建立高速搜尋索引 (HNSW)
-- 讓向量比對在大量資料下也能保持秒回
drop index if exists faq_embedding_idx;
create index faq_embedding_idx on faq using hnsw (embedding vector_cosine_ops);

-- 4. 設定安全性 (RLS)
-- 啟用 RLS
alter table faq enable row level security;

-- 清除舊的策略 (避免重複建立報錯)
drop policy if exists "Enable read access for all users" on faq;

-- 建立策略：開放「讀取 (SELECT)」給所有人
-- 這樣您的前端或 Chatbot 都可以查詢 FAQ
create policy "Enable read access for all users"
on faq for select
using (true);

-- 注意：我們故意不建立 INSERT/UPDATE 的策略
-- 這表示只有擁有 Service Role Key (如 Edge Function) 才能修改資料，
-- 一般使用者或公開 API 即使發送請求也會被拒絕，確保資料安全。

-- 建立加速搜尋的索引
create index on faq using hnsw (embedding vector_cosine_ops);
```
---
## 建立match_faq
```sql
-- 建立搜尋函式 (配合 1536 維度)
create or replace function match_faq (
  query_embedding vector(1536),
  match_threshold float,
  match_count int
)
returns table (
  id bigint,
  question text,
  answer text,
  similarity float
)
language plpgsql
as $$
begin
  return query
  select
    faq.id,
    faq.question,
    faq.answer,
    1 - (faq.embedding <=> query_embedding) as similarity
  from faq
  where 1 - (faq.embedding <=> query_embedding) > match_threshold
  order by faq.embedding <=> query_embedding
  limit match_count;
end;
$$;
```
---
## 建立ts檔案結構 (建立在桌面)
**開啟一個新的 CMD (命令提示字元) 視窗,(備註：如果您有使用 OneDrive，可能需要輸入 cd OneDrive\Desktop)**:
```dos
cd Desktop
```
- **依序執行以下程式碼**
```dos
:: 1. 建立一個新資料夾 (名稱叫 my-bot)
mkdir my-bot

:: 2. 進入這個資料夾
cd my-bot

:: 3. 初始化 Supabase (會產生 supabase 資料夾)
npx supabase init

:: 4. 建立 auto-faq 函式 (會產生 index.ts 檔案)
npx supabase functions new auto-faq
```
**後續的edge function就把程式碼貼在這個新建資料夾裡面的index.ts**


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
// 【新增】引入語言偵測庫 (使用 v6 版本以支援 ESM)
import { franc } from 'https://esm.sh/franc@6'

const OPENAI_API_URL = "https://api.openai.com/v1/embeddings";

Deno.serve(async (req) => {
  try {
    const { record } = await req.json();

    // 1. 基本檢查
    if (!record || record.who !== 'chatbot') {
      return new Response(JSON.stringify({ message: "Skipped" }), { headers: { "Content-Type": "application/json" } });
    }

    // 2. 檢查是否已經處理過
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

    // =====================================================
    // 【新增功能】語言一致性檢查 (Language Mismatch Check)
    // =====================================================
    // minLength: 3 避免極短字串造成誤判
    // franc 回傳 ISO 639-3 三碼 (例如: 'cmn' 是中文, 'eng' 是英文, 'und' 是無法判斷)
    const langQ = franc(cleanQuestion, { minLength: 3 });
    const langA = franc(botAnswer, { minLength: 3 });

    // 邏輯：只有當兩者都「不是 unknown」且「不相等」時，才認定為語言不通
    if (langQ !== 'und' && langA !== 'und' && langQ !== langA) {
      console.log(`Skipped due to language mismatch: Q=${langQ}, A=${langA}`);
      
      // 重要：標記為已處理，避免下次重複觸發
      await supabase.from('taipei_marathon_history')
        .update({ is_processed: true })
        .eq('id', record.id);

      return new Response(JSON.stringify({ message: "Language mismatch ignored" }), { headers: { "Content-Type": "application/json" } });
    }
    // =====================================================

    // 4. 呼叫 OpenAI 產生 Embedding
    const apiKey = Deno.env.get('OPENAI_API_KEY');
    
    // 檢查 cleanQuestion 是否為空，避免 OpenAI 報錯
    if (!cleanQuestion || cleanQuestion.length === 0) {
       await supabase.from('taipei_marathon_history').update({ is_processed: true }).eq('id', record.id);
       return new Response(JSON.stringify({ message: "Empty question skipped" }), { headers: { "Content-Type": "application/json" } });
    }

    const embedResponse = await fetch(OPENAI_API_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${apiKey}`
      },
      body: JSON.stringify({
        model: "text-embedding-3-large",
        input: cleanQuestion, // 【修正】這裡原本少了一個逗號
        dimensions: 1536
      })
    });
    
    const embedData = await embedResponse.json();
    
    if (!embedData.data) {
       console.error("OpenAI Error", embedData);
       // 若 OpenAI 失敗，暫時不要標記 is_processed: true，讓它有機會重試？
       // 或者視錯誤類型決定。這裡先回傳 500。
       return new Response(JSON.stringify({ error: "Embedding failed", details: embedData }), { status: 500 });
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

    // 6. 將該筆紀錄標記為已處理
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
## 設定金鑰與網址串接 (Supabase Dashboard)
**設定 OpenAI Key**：

- **到 Supabase**
- **點選左側 Edge Functions -> 點選 auto-faq。**
- **點選 Secrets (或 Manage Secrets)。**
- **點選 Add new secret**：Name: OPENAI_API_KEY, Value: sk-xxxxxxxxx (您的 OpenAI API Key)

---
## 建立 webhook
- **進入 supabase**
- **點選 Webhooks**
- **點選 Create a new hook**
- **Name 隨意，看得懂是甚麼就好**
- **Table 選擇taipei_marathon_history**
- **Event 勾選Insert**
- **Webhook configuration 選擇 Supabase Edge Function**
- **Method 選擇 POST**
- **Select which edge funciton to trigger 選擇auto-faq**

---
## 處理原本table的歷史紀錄
### 因為 Function 只會處理「未來」的資料，對於「過去」的資料，我們需要手動處理
**Project URL和Project API keys的位置**:
- **進入專案**
- **最上方connect點一下，點一下API keys就可以看到Project URL**
- **在最左側的選單欄，點選最下面的 齒輪圖示 (Project Settings)。**
- **在設定選單中，點選 API**
- **Project API keys要用service_role，可能需要點一下 "Reveal" 才能看到完整的字串。長得像：eyJh... (非常長的一串亂碼)。**
- **記得執行pip install langdetect**

```python
import time
from supabase import create_client, Client
from openai import OpenAI
# 【新增功能】引入語言偵測庫
from langdetect import detect, LangDetectException

# --- 設定區 ---
SUPABASE_URL = "你的supabase url"
SUPABASE_KEY = "你的service role key" 
OPENAI_API_KEY = "sk-...."

# 初始化客戶端
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    client = OpenAI(api_key=OPENAI_API_KEY)
except Exception as e:
    print(f"Init Error: {e}")
    exit(1)

def get_embedding(text):
    response = client.embeddings.create(
        input=text,
        model="text-embedding-3-large",
        dimensions=1536 
    )
    return response.data[0].embedding

# 【新增功能】輔助函式：取得正規化後的語言代碼
# 例如 'zh-tw' -> 'zh', 'en' -> 'en'，確保繁簡中都被視為中文
def get_language_code(text):
    try:
        lang = detect(text)
        return lang.split('-')[0].lower() # 取橫線前的主語言代碼
    except LangDetectException:
        return "unknown"

def backfill_history():
    print("Scanning for unprocessed logs...")
    
    # 1. 抓取未處理的 Chatbot 回應
    response = supabase.table("taipei_marathon_history")\
        .select("*")\
        .eq("who", "chatbot")\
        .eq("is_processed", False)\
        .limit(50)\
        .execute()
    
    logs = response.data
    if not logs:
        print("No unprocessed logs found. Sleeping...")
        return False

    print(f"Processing batch of {len(logs)} logs...")

    for log in logs:
        current_id = log['id']
        bot_msg = log.get('message')

        # =====================================================
        # 【過濾邏輯 1】如果是 NULL 或空字串，直接標記處理並跳過
        # =====================================================
        if not bot_msg or len(bot_msg.strip()) == 0:
            print(f"ID {current_id}: Skipped (Empty bot response)")
            supabase.table("taipei_marathon_history").update({"is_processed": True}).eq("id", current_id).execute()
            continue

        # 2. 找上一句 User 提問
        prev_res = supabase.table("taipei_marathon_history")\
            .select("*")\
            .lt("id", current_id)\
            .order("id", desc=True)\
            .limit(1)\
            .execute()
            
        # 為了避免程式中斷或重複卡住，無論稍後成功與否，這裡先標記為已處理
        supabase.table("taipei_marathon_history").update({"is_processed": True}).eq("id", current_id).execute()

        if prev_res.data and prev_res.data[0]['who'] == 'people':
            user_msg = prev_res.data[0].get('message')
            
            # 【過濾邏輯 2】如果使用者的問題是空的，也跳過
            if not user_msg or len(user_msg.strip()) == 0:
                print(f"ID {current_id}: Skipped (Empty user question)")
                continue

            # 清洗問題字串
            clean_q = user_msg.replace("關於台北馬拉松所有賽事有些相關問題想請教，", "")\
                              .replace("，請翻閱知識庫回答。", "")\
                              .strip()
            
            # 【過濾邏輯 3】檢查內容有效性 (長度 & 排除錯誤訊息)
            if len(clean_q) > 1 and "無法提供回覆" not in bot_msg and "沒有直接關聯" not in bot_msg:
                
                # =====================================================
                # 【新增過濾邏輯 4】語言一致性檢查
                # =====================================================
                try:
                    lang_q = get_language_code(clean_q)
                    lang_a = get_language_code(bot_msg)
                    
                    # 如果兩者都不是 unknown，且語言不一致，則跳過
                    if lang_q != "unknown" and lang_a != "unknown" and lang_q != lang_a:
                        print(f"ID {current_id}: Skipped (Language mismatch: Q={lang_q}, A={lang_a})")
                        continue
                except Exception as e:
                    print(f"Language check warning: {e}")
                    # 檢測失敗時可選擇跳過或放行，這裡選擇放行，避免誤殺
                    pass

                try:
                    # 只印出 ID，避免 Windows 中文亂碼問題
                    print(f"ID {current_id}: Checking duplicates...")

                    # 第一層過濾：嚴格文字比對 (完全一樣的文字直接擋掉)
                    exact_match = supabase.table("faq").select("id").eq("question", clean_q).execute()
                    if exact_match.data and len(exact_match.data) > 0:
                        print(f"  -> Skipped (Exact string match found)")
                        continue 

                    # 第二層過濾：向量語意比對 (Embedding 放在後面做，省錢)
                    vector = get_embedding(clean_q)
                    
                    dup_check = supabase.rpc("match_faq", {
                        "query_embedding": vector,
                        "match_threshold": 0.92,
                        "match_count": 1
                    }).execute()
                    
                    if not dup_check.data:
                        # 兩層都通過，寫入資料庫
                        supabase.table("faq").insert({
                            "question": clean_q,
                            "answer": bot_msg,
                            "embedding": vector
                        }).execute()
                        print(f"  -> Success: Saved to FAQ")
                    else:
                        print(f"  -> Skipped (Semantic duplicate found)")
                        
                except Exception as e:
                    print(f"  -> Error: {e}")
            else:
                print(f"ID {current_id}: Skipped (Invalid content or error message)")
        else:
            print(f"ID {current_id}: Skipped (No matching user question)")

    return True 

if __name__ == "__main__":
    while True:
        try:
            has_more = backfill_history()
            if not has_more:
                time.sleep(2) # 沒資料時休息 2 秒
        except Exception as e:
            print(f"Main Loop Error: {e}")
            time.sleep(5)
```
---