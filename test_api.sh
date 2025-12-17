#!/bin/bash
echo "====== Testing VAMP API ======"
echo
echo "1. Testing /api/expectations..."
curl -s "http://localhost:5000/api/expectations?staff_id=20172672&year=2025" | python -c "
import sys, json
data = json.load(sys.stdin)
print(f'✓ Tasks count: {len(data.get(\"tasks\", []))}')
print(f'✓ KPAs: {list(data.get(\"kpa_summary\", {}).keys())}')
print(f'✓ Months: {list(data.get(\"by_month\", {}).keys())}')
print(f'✓ First 3 tasks:')
for i, task in enumerate(data.get('tasks', [])[:3], 1):
    print(f'  {i}. [{task[\"kpa_code\"]}] {task[\"title\"]}')
"
echo
echo "2. Checking file being served..."
curl -s "http://localhost:5000/" | grep -c "monthlyExpectationsContainer"
echo "^ Should be 1 (HTML has the container)"
echo
echo "3. Checking JavaScript..."
curl -s "http://localhost:5000/app.js" | grep -c "renderMonthlyExpectations"
echo "^ Should be 2+ (function defined and called)"
echo
echo "====== All tests complete ======"
