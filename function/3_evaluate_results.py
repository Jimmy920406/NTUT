import os
import json
import asyncio
from dotenv import load_dotenv

# --- 必要的套件引入 ---
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field, field_validator

# --- 新增的設定：控制評估的批次大小和延遲時間 ---
BATCH_SIZE = 5  # 每批評估 5 個結果
DELAY_BETWEEN_BATCHES = 0  # 每批處理完後，休息 10 秒

def initialize_llm():
    """載入環境變數並初始化 OpenAI LLM 物件。"""
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    model_name = os.getenv("MODEL_NAME", "gpt-4o-mini")
    if not api_key:
        print("❌ 錯誤：找不到 OPENAI_API_KEY。")
        return None
    try:
        # 將溫度設為0，力求客觀
        llm = ChatOpenAI(model=model_name, openai_api_key=api_key)
        print(f"✅ LLM ({model_name}) 初始化成功，用於評估。")
        return llm
    except Exception as e:
        print(f"❌ LLM 初始化失敗：{e}")
        return None

def load_test_results(file_path="test_results.json"):
    """載入測試結果檔案。"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            results = json.load(f)
        print(f"✅ 成功載入測試結果 '{file_path}'，共 {len(results)} 筆。")
        return results
    except FileNotFoundError:
        print(f"❌ 錯誤：找不到測試結果檔案 '{file_path}'。請先執行 2_run_tests.py。")
        return None
    except Exception as e:
        print(f"❌ 讀取測試結果時發生錯誤：{e}")
        return None

# --- 定義評估結果的資料結構 ---

class EvaluationResult(BaseModel):
    """定義單次評估結果的資料結構。"""
    accuracy_score: float = Field(description="準確度分數，衡量答案是否包含錯誤或幻覺資訊。範圍 0.0 到 1.0。")
    completeness_score: float = Field(description="完整度分數，衡量答案是否涵蓋了所有黃金答案的要點。範圍 0.0 到 1.0。")
    explanation: str = Field(description="一段簡短的文字，解釋給出分數的原因，並指出實際答案的優缺點。")
    
    @field_validator('accuracy_score', 'completeness_score')
    def validate_score(cls, v):
        if not 0.0 <= v <= 1.0:
            raise ValueError('分數必須介於 0.0 和 1.0 之間')
        return v

# --- 評估函式 ---

async def evaluate_single_answer_async(llm, test_result):
    """(非同步函式) 使用 LLM 評估單一的問答結果。"""
    parser = JsonOutputParser(pydantic_object=EvaluationResult)
    
    prompt_template = """
    你的身份是一位客觀、嚴謹、吹毛求疵的AI模型評審員。
    你的任務是根據「黃金標準答案」，來評估「受測系統的實際答案」的表現，不得有任何偏袒。

    **評估維度:**
    1.  **準確度 (Accuracy)**: 實際答案是否包含任何與黃金答案相悖的、錯誤的、或無中生有的(幻覺)資訊？如果完全準確，則為 1.0；如果完全錯誤，則為 0.0。
    2.  **完整度 (Completeness)**: 實際答案是否涵蓋了黃金答案中的所有關鍵要點？如果完全涵蓋，則為 1.0；如果完全沒有提到任何要點，則為 0.0。

    **待評估的資料如下:**
    ---
    - **問題**: {question}
    - **黃金標準答案 (絕對正確的參考依據)**: {golden_answer}
    - **受測系統的實際答案 (待評估)**: {actual_answer}
    ---

    請根據上述評估維度，僅輸出一個 JSON 物件，不得有其他任何文字。
    {format_instructions}
    """
    
    prompt = ChatPromptTemplate.from_template(
        template=prompt_template,
        partial_variables={"format_instructions": parser.get_format_instructions()}
    )
    
    chain = prompt | llm | parser

    try:
        evaluation = await chain.ainvoke({
            "question": test_result.get("question"),
            "golden_answer": test_result.get("golden_answer"),
            "actual_answer": test_result.get("actual_answer")
        })
        # 將原始資料與評估結果合併
        final_result = test_result.copy()
        final_result['evaluation'] = evaluation
        return final_result
    except Exception as e:
        print(f"❌ 評估問題 '{test_result.get('question')[:20]}...' 時出錯: {e}")
        final_result = test_result.copy()
        final_result['evaluation'] = {"error": str(e)}
        return final_result

async def main():
    """主執行流程，執行評估"""
    llm_instance = initialize_llm()
    if not llm_instance:
        return

    test_results = load_test_results()
    if not test_results:
        return

    print("\n--- 開始執行自動化評估 (分批模式) ---")
    evaluation_reports = []
    total_results = len(test_results)

    for i in range(0, total_results, BATCH_SIZE):
        batch = test_results[i:i + BATCH_SIZE]
        batch_number = (i // BATCH_SIZE) + 1
        print(f"\n--- 正在評估第 {batch_number} 批次 (結果 {i+1} 到 {min(i + BATCH_SIZE, total_results)}) ---")

        tasks = [evaluate_single_answer_async(llm_instance, result) for result in batch]
        batch_evaluations = await asyncio.gather(*tasks)
        
        evaluation_reports.extend(batch_evaluations)

        if i + BATCH_SIZE < total_results:
            print(f"--- 第 {batch_number} 批次評估完畢，休息 {DELAY_BETWEEN_BATCHES} 秒 ---")
            await asyncio.sleep(DELAY_BETWEEN_BATCHES)

    output_filename = "evaluation_report.json"
    try:
        with open(output_filename, 'w', encoding='utf-8') as f:
            json.dump(evaluation_reports, f, ensure_ascii=False, indent=4)
        print(f"\n\n🎉 評估全部完成！報告已儲存至 '{output_filename}'")
    except Exception as e:
        print(f"❌ 儲存評估報告時發生錯誤：{e}")

if __name__ == "__main__":
    asyncio.run(main())
