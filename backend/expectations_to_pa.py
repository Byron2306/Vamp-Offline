"""
Convert expectations JSON (from build_expectations_from_ta) into a StaffProfile
with proper KPAs and KPIs for PA generation.
"""

from typing import Dict, Any, List
from backend.staff_profile import StaffProfile, KPA, KPI


def expectations_to_profile(
    staff_id: str,
    name: str,
    position: str,
    cycle_year: int,
    expectations: Dict[str, Any],
    ta_summary: Dict[str, Any] = None,
    faculty: str = "",
    line_manager: str = ""
) -> StaffProfile:
    """
    Convert expectations JSON into a StaffProfile with KPAs/KPIs.
    
    Args:
        staff_id: Staff number
        name: Staff member's full name
        position: Job title
        cycle_year: Year (e.g., 2025)
        expectations: Dict from build_expectations_from_ta()
        ta_summary: Original TA summary with detailed arrays
        faculty: Faculty name
        line_manager: Line manager name
    
    Returns:
        StaffProfile with populated KPAs and KPIs from expectations
    """
    
    kpa_summary = expectations.get('kpa_summary', {})
    tasks = expectations.get('tasks', [])
    
    # Get detailed TA arrays if available
    if ta_summary is None:
        ta_summary = {}
    teaching_items = ta_summary.get('teaching', [])
    teaching_modules = ta_summary.get('teaching_modules', [])
    supervision_students = ta_summary.get('supervision', [])
    research_items = ta_summary.get('research', [])
    leadership_items = ta_summary.get('leadership', [])
    social_items = ta_summary.get('social', [])
    ohs_items = ta_summary.get('ohs', [])
    
    # Group tasks by KPA
    tasks_by_kpa: Dict[str, List[Dict[str, Any]]] = {}
    for task in tasks:
        kpa_code = task.get('kpa_code', '')
        if kpa_code not in tasks_by_kpa:
            tasks_by_kpa[kpa_code] = []
        tasks_by_kpa[kpa_code].append(task)
    
    # Build KPAs with KPIs
    kpas: List[KPA] = []
    
    for kpa_code, kpa_details in kpa_summary.items():
        kpa_name = kpa_details.get('name', kpa_code)
        kpa_hours = kpa_details.get('hours', 0.0)
        kpa_weight = kpa_details.get('weight_pct', 0.0)
        
        # Get tasks for this KPA
        kpa_tasks = tasks_by_kpa.get(kpa_code, [])
        
        # Convert tasks to KPIs
        kpis: List[KPI] = []
        
        # Distribute KPA weight and hours across tasks
        num_tasks = len(kpa_tasks)
        task_weight = round(kpa_weight / num_tasks, 2) if num_tasks > 0 else kpa_weight
        task_hours = round(kpa_hours / num_tasks, 2) if num_tasks > 0 else kpa_hours
        
        for task in kpa_tasks:
            # Build KPI description from task
            description = task.get('title', '')
            
            # Build detailed outputs based on KPA
            if kpa_code == 'KPA1' and teaching_modules:
                # For teaching, include actual module codes with student counts
                # teaching_modules is now a list of dicts: {'code': 'HISE322', 'students': 40, 'hours': 117.92}
                modules_with_students = []
                for mod in teaching_modules:
                    if isinstance(mod, dict):
                        code = mod.get('code', '')
                        students = mod.get('students')
                        if students:
                            modules_with_students.append(f"{code} ({students} students)")
                        else:
                            modules_with_students.append(code)
                    else:
                        modules_with_students.append(str(mod))
                
                modules_str = ', '.join(modules_with_students)
                outputs = task.get('outputs', '').replace('Teaching modules as per TA', modules_str)
                outputs = outputs.replace('as per TA', modules_str)
                
                # Add teaching items
                if teaching_items and len(kpis) == 0:  # Add once at start
                    outputs = modules_str + ' | ' + '; '.join(teaching_items[:3])
                elif not outputs or 'Modules:' not in outputs:
                    outputs = task.get('outputs', '') + f' | Modules: {modules_str}'
                    
            elif kpa_code == 'KPA3':
                # For research, include actual projects and supervision
                outputs = task.get('outputs', '')
                
                # Add supervision students if this is a supervision task
                if 'supervision' in description.lower() and supervision_students:
                    outputs = 'Students: ' + ' | '.join(supervision_students)
                    
                # Add research projects for research tasks
                elif 'research' in description.lower() and research_items and len(kpis) < 5:
                    outputs = task.get('outputs', '') + ' | ' + research_items[len(kpis)] if len(kpis) < len(research_items) else task.get('outputs', '')
                    
            elif kpa_code == 'KPA4':
                # For leadership, include actual committee names
                outputs = task.get('outputs', '')
                
                # Add actual leadership activities
                if leadership_items and len(kpis) < len(leadership_items):
                    outputs = leadership_items[len(kpis)]
                elif not outputs:
                    outputs = task.get('outputs', '')
                    
            elif kpa_code == 'KPA5':
                # For social responsiveness, include actual activities
                if social_items and len(kpis) < len(social_items):
                    outputs = social_items[len(kpis)]
                else:
                    outputs = task.get('outputs', '')
                    
            else:
                outputs = task.get('outputs', '')
            
            # Build measure from cadence
            cadence = task.get('cadence', 'monthly')
            months = task.get('months', [])
            
            if cadence == 'monthly':
                measure = f"Monthly task for {_month_names(months)}"
            elif cadence == 'quarterly':
                measure = f"Quarterly task for {_month_names(months)}"
            elif cadence == 'semester':
                measure = f"Semester task for {_month_names(months)}"
            elif cadence == 'critical_milestone':
                measure = f"Critical milestone for {_month_names(months)}"
            elif cadence == 'teaching_practice':
                measure = f"Teaching practice assessment for {_month_names(months)}"
            else:
                measure = f"Task for {_month_names(months)}"
            
            # Build target from minimum/stretch counts
            min_count = task.get('minimum_count', 1)
            stretch_count = task.get('stretch_count', 2)
            target = f"Min: {min_count} evidence, Stretch: {stretch_count} evidence"
            
            # Build evidence types from hints
            evidence_types = task.get('evidence_hints', [])
            
            # Outcomes
            outcomes = "Ubuntu; Batho Pele; Excellence; Integrity"
            
            # Build due date from months
            if months:
                due = f"Month(s): {', '.join(str(m) for m in months)}"
            else:
                due = "As per schedule"
            
            kpi = KPI(
                kpi_id=task.get('id', ''),
                description=description,
                outputs=outputs,
                outcomes=outcomes,
                measure=measure,
                target=target,
                due=due,
                evidence_types=evidence_types[:5],  # Limit to top 5
                generated_by_ai=False,
                weight=task_weight,
                hours=task_hours,
                active=True
            )
            kpis.append(kpi)
        
        # Create KPA
        kpa = KPA(
            code=kpa_code,
            name=kpa_name,
            weight=kpa_weight,
            hours=kpa_hours,
            kpis=kpis,
            ta_context={
                'tasks': kpa_tasks,
                'teaching_modules': kpa_details.get('teaching_modules', [])
            }
        )
        kpas.append(kpa)
    
    # Create profile
    profile = StaffProfile(
        staff_id=staff_id,
        name=name,
        position=position,
        cycle_year=cycle_year,
        faculty=faculty,
        line_manager=line_manager,
        kpas=kpas,
        flags=[]
    )
    
    return profile


def _month_names(months: List[int]) -> str:
    """Convert month numbers to names."""
    month_map = {
        1: 'Jan', 2: 'Feb', 3: 'Mar', 4: 'Apr', 5: 'May', 6: 'Jun',
        7: 'Jul', 8: 'Aug', 9: 'Sep', 10: 'Oct', 11: 'Nov', 12: 'Dec'
    }
    return ', '.join(month_map.get(m, str(m)) for m in months)
