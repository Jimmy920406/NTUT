import os
import re
import traceback
import time
import asyncio
import sys

# --- 必要的套件引入 ---
from dotenv import load_dotenv
import jieba
# 修改點 1: 將 Groq 的引入換成 OpenAI
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser


class SOPQuerySystem:
    """
    將整個 SOP 查詢流程封裝在一個類別中，方便管理狀態與設定。
    """
    def __init__(self):
        """初始化系統，載入設定、LLM 和文件。"""
        print("--- 開始初始化 SOP 查詢系統 (使用 OpenAI) ---")
        self._load_config()
        self.llm = None
        self.sections_to_search = []
        self.initialization_success = self._initialize()

    def _load_config(self):
        """載入所有設定檔"""
        load_dotenv()
        self.config = {
            # 修改點 2: 更新預設模型名稱和 API Key 的讀取
            "MODEL_NAME": os.getenv("MODEL_NAME", "gpt-4o-mini"),
            "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
            "SIMPLIFIED_MD_FILENAME": os.getenv("SIMPLIFIED_MD_FILENAME", "simplified_output_by_section.md"),
            "TARGET_DESCRIPTION_KEYWORDS": ["結塊", "過篩", "順序", "吸濕", "稠度", "黏稠", "流動性"],
            "CHINESE_STOP_WORDS": {"的", "和", "與", "或", "了", "呢", "嗎", "喔", "啊", "關於", "有關", "請", "請問", " ", ""},
            "ALLOWED_WORKSHEET_IDENTIFIERS": ["工作表: 9", "工作表: 10"]
        }

    def _initialize(self):
        """執行初始化步驟：設定 LLM 和載入文件。"""
        # 修改點 3: 完全替換為 OpenAI 的初始化邏輯
        # 1. 初始化 LangChain 的 ChatOpenAI 物件
        if not self.config["OPENAI_API_KEY"] or not self.config["MODEL_NAME"]:
            print("❌ 錯誤：未能獲取 OPENAI_API_KEY 或 MODEL_NAME，無法初始化 ChatOpenAI。")
            return False
        try:
            self.llm = ChatOpenAI(model=self.config["MODEL_NAME"], openai_api_key=self.config["OPENAI_API_KEY"])
            print(f"✅ ChatOpenAI (LangChain) for model '{self.config['MODEL_NAME']}' 初始化成功。")
        except Exception as e:
            print(f"❌ 初始化 ChatOpenAI 時發生錯誤：{e}")
            return False

        # 2. 載入並過濾 SOP 文件區塊 (這部分邏輯不變)
        all_sections = self._load_markdown_sections()
        if not all_sections:
            print(f"❌ 錯誤：未能從 '{self.config['SIMPLIFIED_MD_FILENAME']}' 載入任何 SOP 文件區塊。")
            return False

        self.sections_to_search = self._filter_sections_by_title(all_sections)
        if not self.sections_to_search:
            print(f"⚠️ 警告：未過濾出任何目標區塊，將在全部 {len(all_sections)} 個區塊中搜尋。")
            self.sections_to_search = all_sections
        
        print(f"✅ 成功準備 {len(self.sections_to_search)} 個區塊供查詢。")
        return True

    def _load_markdown_sections(self):
        """從檔案讀取並解析 Markdown 區塊。"""
        # 這部分的程式碼完全不需要修改
        script_dir = os.path.dirname(__file__)
        filename = os.path.abspath(os.path.join(script_dir, '..', self.config["SIMPLIFIED_MD_FILENAME"]))
        
        print(f"(SUT) 正在從絕對路徑載入檔案: {filename}")
        if not os.path.exists(filename):
            print(f"❌ (SUT) 錯誤：檔案 '{filename}' 不存在。")
            return []
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                markdown_content = f.read()
        except Exception as e:
            print(f"❌ (SUT) 讀取檔案 '{filename}' 時發生錯誤：{e}")
            return []

        parts = re.split(r'(## 工作表:.*)', markdown_content)
        sections = []
        for i in range(1, len(parts), 2):
            if i + 1 < len(parts):
                title = parts[i].strip()
                content = parts[i + 1].strip()
                if title and content:
                    sections.append({"title": title, "content": content})
        
        if not sections:
            print(f"⚠️ (SUT) 警告：未能從檔案 '{filename}' 解析出任何工作表區塊。")
        else:
            print(f"(SUT) 從 '{filename}' 解析出 {len(sections)} 個區塊。")
        return sections

    def _filter_sections_by_title(self, all_sections):
        """根據標題過濾區塊。"""
        # 這部分的程式碼完全不需要修改
        allowed_identifiers = self.config["ALLOWED_WORKSHEET_IDENTIFIERS"]
        return [sec for sec in all_sections if
                any(allowed_id in sec.get("title", "") for allowed_id in allowed_identifiers)]

    # --- 以下所有 RAG 流程的函式，都因為 LangChain 的抽象化而【完全不需要修改】 ---

    def _extract_keywords_rule_based(self, user_input):
        """使用規則提取關鍵字。"""
        # ... (此處省略以保持簡潔，您的程式碼不需變動) ...
        print(f"--- (階段0) 使用規則解析輸入 (主要提取原料): '{user_input}' ---")
        tokens = list(jieba.cut_for_search(user_input.strip().lower()))
        potential_materials = []
        identified_characteristics = set()
        for token in tokens:
            token_clean = token.strip()
            if not token_clean or token_clean in self.config["CHINESE_STOP_WORDS"]: continue
            is_characteristic = False
            for target_char in self.config["TARGET_DESCRIPTION_KEYWORDS"]:
                if token_clean == target_char.lower():
                    identified_characteristics.add(target_char)
                    is_characteristic = True
                    break
            if not is_characteristic and not token_clean.isnumeric() and len(token_clean) > 0:
                potential_materials.append(token_clean)
        
        if not potential_materials: return None
        return {"原料名稱": sorted(list(set(potential_materials))), "特性描述": sorted(list(identified_characteristics))}

    def _search_sections(self, keywords_data):
        """初步篩選包含關鍵字的工作表。"""
        # ... (此處省略以保持簡潔，您的程式碼不需變動) ...
        material_keywords = keywords_data.get("原料名稱", [])
        if not material_keywords: return []
        relevant_sections = []
        for section in self.sections_to_search:
            text_to_search = section.get("title", "") + section.get("content", "")
            if any(keyword.lower() in text_to_search.lower() for keyword in material_keywords):
                relevant_sections.append(section)
        return relevant_sections
        
    async def _extract_relevant_text_async(self, section, keywords_data):
        """(第一階段 LLM - 非同步) 提取與原料最直接相關的文字片段。"""
        # ... (此處省略以保持簡潔，您的程式碼不需變動) ...
        material_name_str = "、".join(keywords_data.get('原料名稱', []))
        description_keywords_str = ', '.join(keywords_data.get('特性描述', []))
        prompt_template_str = """
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
        3.  **【嚴格禁止】添加任何額外文字**
        4.  **【嚴格禁止】提取元信息**
        5.  **找不到內容的處理**: 如果找不到，唯一輸出**必須**是：`NO_DIRECT_CONTENT_FOUND`
        6.  **輸出格式**: 直接輸出文字即可，不要使用 markdown 的 ` ``` ` 區塊包圍。
        """
        prompt_template = ChatPromptTemplate.from_template(prompt_template_str)
        chain = prompt_template | self.llm | StrOutputParser()
        print(f"  (Async) 正在處理區塊: {section['title']}...")
        try:
            relevant_text = await chain.ainvoke({"material_name_str": material_name_str, "description_keywords_str": description_keywords_str, "text": section["content"]})
            relevant_text = relevant_text.strip()
            is_found = "NO_DIRECT_CONTENT_FOUND" not in relevant_text and relevant_text
            if not is_found: print(f"     ↳ 在區塊 '{section['title']}' 中未找到內容。")
            else: print(f"     ↳ 從 '{section['title']}' 提取到內容。")
            return {"title": section['title'], "text": relevant_text, "found": is_found}
        except Exception as e:
            print(f"❌ 從區塊 '{section['title']}' 非同步提取時出錯: {e}")
            return {"title": section['title'], "text": "LLM 提取失敗", "found": False}

    def _synthesize_results(self, keywords_data, extracted_texts):
        """(第二階段 LLM) 將提取的文字片段整合成統一格式列表。"""
        # ... (此處省略以保持簡潔，您的程式碼不需變動) ...
        valid_extractions = [item['text'] for item in extracted_texts if item.get("found")]
        if not valid_extractions:
            material_name_str = "、".join(keywords_data.get('原料名稱', ["所查詢的項目"]))
            return f"已檢查所有相關SOP文件區塊，但均未找到關於原料【{material_name_str}】的直接操作說明或注意事項。"
        print(f"\n🔄 (階段2) 正在整合 {len(valid_extractions)} 份提取的重點內容...")
        combined_extracted_text = "\n\n---\n\n".join(valid_extractions)
        material_name = "、".join(keywords_data.get('原料名稱', []))
        characteristics_list = keywords_data.get('特性描述', [])
        synthesis_prompt_template_str = """
        您是一位SOP內容整理員。您的任務是將下方提供的、已從SOP文件中提取出的、與指定原料相關的【多個獨立的簡短文字片段】，整理成一個【極簡的、統一格式的數字編號列表】。
        使用者主要查詢的原料名稱為【{material_name}】。(使用者查詢時提及的相關詞彙，供您理解上下文：{characteristics_list})
        
        已提取的相關SOP片段 (請將它們視為獨立的資訊點)：
        ---
        {combined_extracted_text}
        ---

        您的任務與輸出要求：
        1.  **【核心任務】：** 將這些片段整理成列表中的一個獨立項目。
        2.  **【格式統一】：** 使用從 1. 開始的數字編號列表。
        3.  **【原文呈現】：** 盡最大可能【直接使用】原文表述，【嚴格禁止】任何形式的改寫或摘要。
        4.  **【極簡輸出】：** 您的最終輸出【必須直接是這個數字編號列表本身】。
        5.  如果多個片段資訊重複，請只保留一個。
        請直接開始輸出列表：
        """
        synthesis_prompt = ChatPromptTemplate.from_template(synthesis_prompt_template_str)
        synthesis_chain = synthesis_prompt | self.llm | StrOutputParser()
        final_response = synthesis_chain.invoke({"material_name": material_name, "characteristics_list": ', '.join(characteristics_list), "combined_extracted_text": combined_extracted_text})
        return final_response.strip()

    async def process_query(self, user_query):
        """處理單一使用者查詢並返回結果 (非同步)。"""
        # ... (此處省略以保持簡潔，您的程式碼不需變動) ...
        if not self.initialization_success:
            return "系統初始化失敗，無法處理查詢。"
        print(f"\n處理查詢: '{user_query}'")
        start_time = time.time()
        try:
            keywords_data = self._extract_keywords_rule_based(user_query)
            if not keywords_data or not keywords_data.get("原料名稱"):
                return "無法從您的訊息中解析出有效的原料名稱進行查詢。"
            relevant_sop_sections = self._search_sections(keywords_data)
            if not relevant_sop_sections:
                material_name_str = "、".join(keywords_data.get("原料名稱", ["未知原料"]))
                return f"在SOP文件中，找不到與原料【{material_name_str}】直接相關的工作表。"
            tasks = [self._extract_relevant_text_async(section, keywords_data) for section in relevant_sop_sections]
            extracted_texts = await asyncio.gather(*tasks)
            final_summary = self._synthesize_results(keywords_data, extracted_texts)
            reply_text = final_summary
        except Exception as e:
            print(f"!!!!!!!!!! 處理查詢 '{user_query}' 時發生嚴重錯誤 !!!!!!!!!!")
            traceback.print_exc()
            reply_text = f"處理查詢時遇到未預期的錯誤，請檢查日誌。"
        end_time = time.time()
        print(f"查詢 \"{user_query}\" 處理完成，耗時 {end_time - start_time:.2f} 秒。")
        return reply_text if reply_text.strip() else "抱歉，未能找到明確的資訊。"


# --- 主執行區塊 ---
async def main():
    """程式進入點，執行非同步的查詢迴圈。"""
    # 這部分的程式碼完全不需要修改
    sop_system = SOPQuerySystem()

    if sop_system.initialization_success:
        print("\n--- 系統已就緒，請輸入您的查詢 ---")
        print("    (例如：'食鹽 結塊')")
        print("    (輸入 'exit' 或 'quit' 來結束程式)")
        
        while True:
            try:
                user_input = await asyncio.to_thread(input, "\n您的查詢: ")
                if user_input.strip().lower() in ['exit', 'quit']:
                    print("正在結束程式...")
                    break
                if not user_input.strip():
                    continue

                result = await sop_system.process_query(user_input)
                print("\n========== 查詢結果 ==========")
                print(result)
                print("==============================")
            except (KeyboardInterrupt, EOFError):
                print("\n偵測到使用者中斷，正在結束程式...")
                break
            except Exception as e:
                print(f"\n在主查詢迴圈中發生未預期錯誤: {e}")
                traceback.print_exc()
    else:
        print("\n❌ 因系統初始化失敗，無法啟動 SOP 查詢系統。請檢查上方的錯誤訊息。")
    
    print("--- 程式執行完畢 ---")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程式被強制終止。")
