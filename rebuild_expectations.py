import sys
sys.path.insert(0, '.')
from artefact_pipeline import parse_task_agreement, build_expectations_from_ta
import json

# Parse the detailed TA file
ta_file = '2025 FEDU_Task_Agreement_Form (V1_test) B Bunt.xlsx'
staff_number = '20172672'
year = 2025

print(f'Parsing {ta_file}...')
result = parse_task_agreement(ta_file)
if result['status'] == 'success':
    print(f'Successfully parsed TA file')
    print(f'Staff: {result["data"]["staff_number"]}')
    
    # Build expectations
    print('Building expectations...')
    expectations = build_expectations_from_ta(result['data'])
    
    # Save to file
    output_file = f'backend/data/staff_expectations/expectations_{staff_number}_{year}.json'
    with open(output_file, 'w') as f:
        json.dump(expectations, f, indent=2)
    
    print(f'Saved expectations to {output_file}')
    print(f'Task count: {expectations.get("task_count", 0)}')
    print(f'Tasks length: {len(expectations.get("tasks", []))}')
else:
    print(f'Error: {result.get("message", "Unknown error")}')
