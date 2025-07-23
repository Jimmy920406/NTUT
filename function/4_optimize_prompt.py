import os
import json
from dotenv import load_dotenv

# --- 必要的套件引入 ---
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers import StrOutputParser

# ==============================================================================
# --- 設定區：請將您所有需要優化的 Prompt 集中管理在此字典中 ---
# ==============================================================================
# 鍵 (Key): 您為 Prompt 取的描述性名稱，會顯示在最終報告的標題中。
# 值 (Value): 從 sut_system/main.py 複製過來的完整 Prompt 字串。
# 您可以隨意在這裡新增、刪除或修改 Prompt。

PROMPTS_TO_OPTIMIZE = {
    "Extractor Prompt (第一階段：文字提取)": """
    你的身份是一個自動化的、沒有感情的文字提取機器人。
    你的唯一任務是：在下方提供的「工作表內容」中，僅找出與「主要查詢的原料名稱」最直接相關的【一個或多個簡短文字片段、句子或列表項】。

    主要查詢的原料名稱：【{material_name_str}】
    (使用者同時提及的相關詞彙，僅供你理解上下文，不用於提取：{description_keywords_str})

    工作表內容：
    ```markdown
    {text}
    ```

    ---
    **嚴格輸出規則 (ABSOLUTE RULES):**

    1.  **精確提取**: 只輸出包含「主要查詢的原料名稱」的句子、操作步驟或其非常緊密的上下文。範圍越小越好。
    2.  **【直接輸出原文】**: 你的輸出**必須**直接就是從「工作表內容」中複製出來的文字，一字不改。
    3.  **【嚴格禁止】添加任何額外文字**: 你的輸出中，**絕對不允許**包含任何你自己創造的、解釋性的、總結性的文字。
        -   **錯誤範例 (禁止輸出)**: "根據文件，食鹽在第4點提到..."
        -   **錯誤範例 (禁止輸出)**: "以下是找到的相關內容："
        -   **錯誤範例 (禁止輸出)**: "好的，這是關於食鹽的資訊。"
    4.  **【嚴格禁止】提取元信息**: 絕對禁止包含 '## 工作表: ...' 這種標題，或任何 '製表日期', '製表人' 等頁腳資訊。
    5.  **找不到內容的處理**: 如果在「工作表內容」中找不到任何與「主要查詢的原料名稱」直接相關的內容，你的唯一輸出**必須**是以下這段固定的文字，不得有任何增減：`NO_DIRECT_CONTENT_FOUND`
    6.  **輸出格式**: 直接輸出文字即可，不要使用 markdown 的 ` ``` ` 區塊包圍。

    再次強調：你的任務是複製貼上，不是總結或解釋。直接開始輸出你找到的原文片段。
    """,
    
    "Synthesizer Prompt (第二階段：結果整合)": """
    您是一位SOP內容整理員。您的任務是將下方提供的、已從SOP文件中提取出的、與指定原料相關的【多個獨立的簡短文字片段】，整理成一個【極簡的、統一格式的數字編號列表】。
    使用者主要查詢的原料名稱為【{material_name}】。(使用者查詢時提及的相關詞彙，供您理解上下文：{characteristics_list})
    
    已提取的相關SOP片段 (請將它們視為獨立的資訊點)：
    ---
    {combined_extracted_text}
    ---

    您的任務與輸出要求：
    1.  **【核心任務】：** 將這些片段中的【每一個獨立的資訊點、操作步驟、或注意事項】整理出來，作為列表中的一個獨立項目。
    2.  **【格式統一】：** 使用從 1. 開始的數字編號列表。
    3.  **【原文呈現】：** 盡最大可能【直接使用】提取片段中的【原文表述】。**【嚴格禁止】** 任何形式的改寫、摘要、解釋或歸納。
    4.  **【極簡輸出】：** 您的最終輸出【必須直接是這個數字編號列表本身】。**【嚴格禁止】** 包含任何前言、標題或結語。
    5.  如果多個片段資訊重複，請只保留一個最清晰的。
    6.  使用**繁體中文**。
    請直接開始輸出列表：
    """
    # 如果您有第三個、第四個 Prompt，請直接加在下面
    # "Another Prompt (第三階段：總結)": """...您的第三個 Prompt 內容..."""
}

# --- 函式定義 (與之前相同，無需修改) ---

def initialize_llm():
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    model_name = os.getenv("MODEL_NAME", "gpt-4o-mini")
    if not api_key:
        print("❌ 錯誤：找不到 OPENAI_API_KEY。")
        return None
    try:
        llm = ChatOpenAI(model=model_name, openai_api_key=api_key, temperature=0.5)
        print(f"✅ LLM ({model_name}) 初始化成功，用於 Prompt 優化。")
        return llm
    except Exception as e:
        print(f"❌ LLM 初始化失敗：{e}")
        return None

def load_evaluation_report(file_path="evaluation_report.json"):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            report = json.load(f)
        print(f"✅ 成功載入評估報告 '{file_path}'，共 {len(report)} 筆。")
        return report
    except FileNotFoundError:
        print(f"❌ 錯誤：找不到評估報告檔案 '{file_path}'。請先執行 3_evaluate_results.py。")
        return None
    except Exception as e:
        print(f"❌ 讀取評估報告時發生錯誤：{e}")
        return None

def filter_poor_performing_cases(report, threshold=0.9):
    poor_cases = [
        result for result in report
        if isinstance(result.get("evaluation"), dict) and (
            result["evaluation"].get("accuracy_score", 1.0) < threshold or
            result["evaluation"].get("completeness_score", 1.0) < threshold
        )
    ]
    print(f"篩選出 {len(poor_cases)} 個表現不佳的案例 (分數低於 {threshold})。")
    return poor_cases

def generate_prompt_suggestions(llm, original_prompt, failure_cases):
    if not failure_cases:
        return "所有案例表現良好，無需優化！"
    
    cases_for_analysis = failure_cases[:5] # 為了避免 Prompt 過長，只選前 5 個
    failure_analysis_str = ""
    for i, case in enumerate(cases_for_analysis):
        failure_analysis_str += f"--- 失敗案例 {i+1} ---\n"
        failure_analysis_str += f"問題: {case.get('question')}\n"
        failure_analysis_str += f"黃金答案 (期望的): {case.get('golden_answer')}\n"
        failure_analysis_str += f"系統的錯誤答案: {case.get('actual_answer')}\n"
        failure_analysis_str += f"AI評審員的評語: {json.dumps(case.get('evaluation'), ensure_ascii=False)}\n\n"

    prompt_template_str = """
    你的身份是一位世界頂尖的提示工程 (Prompt Engineering) 專家。
    一個 RAG (檢索增強生成) 系統在回答問題時表現不佳，你的任務是分析一系列失敗案例，並對系統使用的【原始 Prompt】提出具體的、可執行的修改建議。

    **你的分析目標：【原始 Prompt】**
    ```text
    {original_prompt}
    ```

    **失敗案例分析：**
    {failure_cases_str}

    **你的任務與輸出要求：**
    請基於以上所有資訊，產出一份【Prompt 優化報告】。報告必須包含以下三個部分，並使用 Markdown 標題格式化：

    ### 1. 問題根源分析 (Root Cause Analysis)
    - 深入分析【原始 Prompt】中可能存在哪些模糊、有歧義或有漏洞的指令，導致了失敗。

    ### 2. 具體修改建議 (Actionable Suggestions)
    - 提出清晰的修改建議，例如「將 A 句修改為 B 句」。

    ### 3. 優化後的完整 Prompt (Optimized Full Prompt)
    - 提供一個整合了你所有建議的、可以直接複製使用的【優化後完整 Prompt 版本】。
    """
    
    prompt = ChatPromptTemplate.from_template(prompt_template_str)
    chain = prompt | llm | StrOutputParser()
    
    try:
        suggestion_report = chain.invoke({
            "original_prompt": original_prompt,
            "failure_cases_str": failure_analysis_str
        })
        return suggestion_report
    except Exception as e:
        print(f"❌ 生成優化建議時出錯: {e}")
        return f"生成建議失敗: {e}"

# --- 主執行區塊 (已重構為可擴展) ---
def main():
    """
    主執行流程，現在會自動遍歷 PROMPTS_TO_OPTIMIZE 字典中的所有 Prompt。
    """
    llm_instance = initialize_llm()
    if not llm_instance: return

    report = load_evaluation_report()
    if not report: return

    poor_cases = filter_poor_performing_cases(report)
    if not poor_cases:
        print("\n🎉 恭喜！所有測試案例的評分均高於閾值，目前無需優化。")
        return

    # 建立一個列表來存放所有報告內容
    all_reports_content = []

    # 遍歷字典中的每一個 Prompt 進行分析
    for prompt_name, prompt_content in PROMPTS_TO_OPTIMIZE.items():
        print(f"\n{'='*20}\n analyzing Prompt: '{prompt_name}'\n{'='*20}")
        
        suggestion = generate_prompt_suggestions(llm_instance, prompt_content, poor_cases)
        
        # 將每個 Prompt 的分析報告格式化後加入列表
        report_section = f"""
# {prompt_name} - 優化報告

{suggestion}
"""
        all_reports_content.append(report_section)

    # 將所有報告合併成一個檔案
    full_report_content = "\n---\n".join(all_reports_content)
    output_filename = "prompt_optimization_report_full.md"
    
    try:
        with open(output_filename, 'w', encoding='utf-8') as f:
            f.write(full_report_content.strip())
        print(f"\n\n✅ 完整的綜合優化報告已成功生成並儲存至 '{output_filename}'")
    except Exception as e:
        print(f"❌ 儲存綜合報告時發生錯誤：{e}")

if __name__ == "__main__":
    main()
