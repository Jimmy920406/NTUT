## 專案結構

```
llm_evaluator/
    ├── sut_system/
    │   ├── __init__.py
    │   └── main.py    #想要修改的LLM
    │
    ├── 1_generate_qa.py        #生成問答
    ├── 2_run_tests.py          #對LLM提問
    ├── 3_evaluate_results.py   #評估回答與標準答案
    ├── 4_optimize_prompt.py    #生成建議與修改的prompt
    │
    └── simplified_output_by_section.md     #輸入的文件


```
