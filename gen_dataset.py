import json
from pathlib import Path
from .src.memory_module.memory_bank import MemoryBank
from .src.memory_module.framework import MemoryModule
from pprint import pprint

file_name = 'log_succeed_XBOW+020_20260117_231830_labeled.json'
pentest_data = json.load(open(r'E:\MemoryModule\dataset\log_succeed_XBOW+020_20260117_231830_labeled.json', 'r', encoding='utf-8'))

pentest_goal = pentest_data["initial_prompt"]

memory_module = MemoryModule(step_id=1, top_k=50)

def format_query_function(raw_outputs, pentest_info):
    return json.dumps(pentest_info, ensure_ascii=False)

for i, step in enumerate(pentest_data["steps"]):
    print(f"Step {i+1}:")
    step_id = step["step_number"]
    memory_module.step_id = step_id
    phase = step["stage"]
    subgoal = step["planning"]
    state_summary = [
        f"Step {s['step_number']}: {s['label_rationale']}"
        for s in pentest_data["steps"][i - 10 : i]
    ]
    state_summary = "\n".join(state_summary)
    obs_id = "obs_" + str(step["step_number"])
    source_tool = "python"
    source_command = step["code"]
    obs_text = step["observation"]

    pentest_info = {
        "step_id": step_id,
        "phase": phase,
        "subgoal": subgoal,
        "state_summary": state_summary,
        "obs": {
            "obs_id": obs_id,
            "source_tool": source_tool,
            "source_command": source_command,
            "obs_text": obs_text,
        }
    }

    results, action = memory_module.process_observation(
        raw_outputs=obs_text,
        pentest_info=pentest_info,
        format_query_function=format_query_function,
    )

    log_file_name = f'{file_name.split(".")[0].rsplit("_", 1)[0]}_memory.txt'
    with open(log_file_name, 'a', encoding='utf-8') as f:
        f.write(f"STEP {step_id}:\n")
        json.dump(action, f, ensure_ascii=False)
        f.write("\n")
        json.dump(memory_module.memory_bank.memories, f, ensure_ascii=False)
        f.write("\n")
        json.dump(results, f, ensure_ascii=False)
        f.write("\n")
        



    

    

    