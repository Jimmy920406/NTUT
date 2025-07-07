import os
import json
import re
import asyncio
from dotenv import load_dotenv

# --- 必要的套件引入 ---
from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field

# --- 設定與初始化 ---

def initialize_llm():
    """載入環境變數並初始化 Groq LLM 物件。"""
    load_dotenv()
    
    api_key = os.getenv("GROQ_API_KEY")
    model_name = os.getenv("MODEL_NAME", "llama3-8b-8192")

    if not api_key:
        print("❌ 錯誤：找不到 GROQ_API_KEY。請檢查您的 .env 檔案。")
        return None

    try:
        # 增加 temperature 讓每次生成的題目稍微有點不同
        llm = ChatGroq(model=model_name, groq_api_key=api_key, temperature=0.3)
        print(f"✅ LLM ({model_name}) 初始化成功。")
        return llm
    except Exception as e:
        print(f"❌ LLM 初始化失敗：{e}")
        return None

def load_and_split_document(file_path="simplified_output_by_section.md"):
    """載入文件並將其按 '## 工作表:' 分割成多個區塊。"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        print(f"✅ 文件 '{file_path}' 載入成功。")
    except FileNotFoundError:
        print(f"❌ 錯誤：找不到文件 '{file_path}'。")
        return []
    except Exception as e:
        print(f"❌ 讀取文件時發生錯誤：{e}")
        return []

    # 使用正規表示式分割文件
    parts = re.split(r'(## 工作表:.*)', content)
    sections = []
    # 從 1 開始，每次跳 2，因為 parts[0] 是第一個標題前的空內容
    for i in range(1, len(parts), 2):
        if i + 1 < len(parts):
            title = parts[i].strip()
            section_content = parts[i + 1].strip()
            if title and section_content:
                sections.append({"title": title, "content": section_content})
    
    if not sections:
        print(f"⚠️ 警告：未能從 '{file_path}' 解析出任何工作表區塊。")
    else:
        print(f"   總共分割成 {len(sections)} 個獨立區塊。")
    return sections

# --- 定義輸出的資料結構 ---

class QAPair(BaseModel):
    """定義單個問題與答案的資料結構。"""
    question: str = Field(description="根據文件內容生成的一個具有挑戰性的問題")
    golden_answer: str = Field(description="針對該問題，直接源於文件內容的、最精確客觀的標準答案")

class QADataset(BaseModel):
    """定義整個 Q&A 資料集的列表結構。"""
    qa_pairs: list[QAPair] = Field(description="一個包含多個問題與答案組合的列表")

# --- 主執行函式 ---

async def generate_qa_for_section_async(llm, section_content):
    """
    (非同步函式) 使用 LLM 為單一的文件區塊生成 Q&A。
    """
    if not llm or not section_content:
        return None

    parser = JsonOutputParser(pydantic_object=QADataset)
    
    prompt_template = """
    你的身份是一位資深的企業內部訓練講師與品保工程師。
    你的任務是為【單一的】標準作業流程 (SOP) 文件【區塊】設計一份嚴格的測驗題庫。

    請仔細閱讀以下提供的【單一SOP區塊內容】，並生成 1 到 2 組高品質的「問題」與「標準答案」。

    你的要求如下：
    1.  **問題設計**: 問題必須精準地針對此區塊的內容，涵蓋關鍵細節、操作順序或注意事項。
    2.  **答案品質**: 標準答案必須【直接源於】提供的區塊內容，力求精確。
    3.  **格式**: 你必須嚴格遵循我提供的 JSON 格式進行輸出。

    {format_instructions}

    單一SOP區塊內容如下：
    ---
    {document_chunk}
    ---
    """
    
    prompt = ChatPromptTemplate.from_template(
        template=prompt_template,
        partial_variables={"format_instructions": parser.get_format_instructions()}
    )
    
    chain = prompt | llm | parser

    try:
        # 使用 ainvoke 進行非同步呼叫
        result = await chain.ainvoke({"document_chunk": section_content})
        return result
    except Exception as e:
        print(f"❌ 處理某個區塊時 LLM 呼叫失敗：{e}")
        return None

async def main():
    """主執行流程"""
    llm_instance = initialize_llm()
    if not llm_instance:
        return

    sections = load_and_split_document()
    if not sections:
        return

    print(f"\n⏳ 準備並行處理 {len(sections)} 個文件區塊，請稍候...")
    
    # 建立所有非同步任務
    tasks = [generate_qa_for_section_async(llm_instance, section['content']) for section in sections]
    
    # 使用 asyncio.gather 並行執行所有任務
    results = await asyncio.gather(*tasks)

    # 收集所有成功的結果
    all_qa_pairs = []
    for result in results:
        if result and 'qa_pairs' in result:
            all_qa_pairs.extend(result['qa_pairs'])

    if all_qa_pairs:
        output_filename = "test_dataset.json"
        try:
            with open(output_filename, 'w', encoding='utf-8') as f:
                json.dump(all_qa_pairs, f, ensure_ascii=False, indent=4)
            print(f"\n✅ 成功生成 Q&A 資料集，並已儲存至 '{output_filename}'")
            print(f"   總共生成了 {len(all_qa_pairs)} 組問答。")
        except Exception as e:
            print(f"❌ 儲存 JSON 檔案時發生錯誤：{e}")
    else:
        print("\n❌ 未能從 LLM 成功生成任何 Q&A 資料。")


if __name__ == "__main__":
    # 使用 asyncio.run 來執行我們的非同步主函式
    asyncio.run(main())
