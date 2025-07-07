import os
import json
import sys
import asyncio
import time

# 為了讓 Python 找到 sut_system 這個資料夾裡的模組
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), 'sut_system')))

try:
    from main import SOPQuerySystem
    print("✅ 成功從 'sut_system' 模組引入 SOPQuerySystem。")
except ImportError:
    print("❌ 錯誤：無法從 'sut_system/main.py' 引入 SOPQuerySystem。")
    sys.exit(1)

# --- 新增的設定：控制批次大小和延遲時間 ---
BATCH_SIZE = 5  # 每批處理 5 個問題
DELAY_BETWEEN_BATCHES = 0  # 每批處理完後，休息 10 秒

def load_test_dataset(file_path="test_dataset.json"):
    """載入 Q&A 測試集。"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            dataset = json.load(f)
        print(f"✅ 成功載入測試集 '{file_path}'，共 {len(dataset)} 個問題。")
        return dataset
    except FileNotFoundError:
        print(f"❌ 錯誤：找不到測試集檔案 '{file_path}'。請先執行 1_generate_qa.py。")
        return None
    except Exception as e:
        print(f"❌ 讀取測試集時發生錯誤：{e}")
        return None

async def run_single_test(sut, qa_pair, index, total):
    """(非同步) 執行單一測試並回傳結果"""
    question = qa_pair.get("question")
    golden_answer = qa_pair.get("golden_answer")
    
    if not question:
        return None

    print(f"\n⏳ 正在測試第 {index+1}/{total} 個問題...")
    print(f"   問題: {question[:50]}...")

    start_time = time.time()
    try:
        actual_answer = await sut.process_query(question)
        duration = time.time() - start_time
        print(f"   ✅ 系統在 {duration:.2f} 秒內回覆。")
        return {
            "question": question,
            "golden_answer": golden_answer,
            "actual_answer": actual_answer
        }
    except Exception as e:
        duration = time.time() - start_time
        print(f"   ❌ 測試問題時發生錯誤 (耗時 {duration:.2f} 秒): {e}")
        return {
            "question": question,
            "golden_answer": golden_answer,
            "actual_answer": f"ERROR: {str(e)}"
        }

async def main():
    """
    主執行函式，執行分批測試流程。
    """
    test_data = load_test_dataset()
    if not test_data:
        return

    print("\n--- 正在初始化受測系統 (SOPQuerySystem) ---")
    sut = SOPQuerySystem()
    if not sut.initialization_success:
        print("❌ 受測系統初始化失敗，測試中止。")
        return
    
    print("\n--- 開始執行自動化測試 (分批模式) ---")
    test_results = []
    total_questions = len(test_data)

    # 將所有測試資料分成多個批次
    for i in range(0, total_questions, BATCH_SIZE):
        batch = test_data[i:i + BATCH_SIZE]
        batch_number = (i // BATCH_SIZE) + 1
        print(f"\n--- 正在處理第 {batch_number} 批次 (問題 {i+1} 到 {min(i + BATCH_SIZE, total_questions)}) ---")

        # 為當前批次的每個問題建立非同步任務
        tasks = [run_single_test(sut, qa_pair, i + j, total_questions) for j, qa_pair in enumerate(batch)]
        
        # 並行執行當前批次的任務
        batch_results = await asyncio.gather(*tasks)
        
        # 收集結果
        test_results.extend([res for res in batch_results if res is not None])

        # 如果這不是最後一批，則進行延遲
        if i + BATCH_SIZE < total_questions:
            print(f"\n--- 第 {batch_number} 批次處理完畢，休息 {DELAY_BETWEEN_BATCHES} 秒以避免速率超限 ---")
            await asyncio.sleep(DELAY_BETWEEN_BATCHES)

    output_filename = "test_results.json"
    try:
        with open(output_filename, 'w', encoding='utf-8') as f:
            json.dump(test_results, f, ensure_ascii=False, indent=4)
        print(f"\n\n🎉 測試全部完成！結果已儲存至 '{output_filename}'")
    except Exception as e:
        print(f"❌ 儲存測試結果時發生錯誤：{e}")

if __name__ == "__main__":
    asyncio.run(main())
