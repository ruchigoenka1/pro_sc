import streamlit as st
import pandas as pd
import pulp
import plotly.figure_factory as ff
import plotly.express as px
from datetime import datetime, timedelta

st.set_page_config(layout="wide", page_title="Advanced Job Scheduler")

## --------------------------------------------------------
## 1. TITLE & INTRODUCTION
## --------------------------------------------------------
st.title("🗓️ Smart Job & Resource Scheduler")
st.markdown("""
Optimize your project schedules using Mixed-Integer Linear Programming (**PuLP**). 
Input your jobs, process flows, resource capabilities, and deadlines to generate optimal schedules and interactive Gantt charts.
""")


## --------------------------------------------------------
## 2. SAMPLE DATA & INPUTS
## --------------------------------------------------------
# Default sample data for easy testing
default_data = pd.DataFrame([
    {"Job": "Job_1", "Process": "P1", "Eligible_Resources": "R1, R2", "Duration": 2, "Preceding_Process": ""},
    {"Job": "Job_1", "Process": "P2", "Eligible_Resources": "R2, R3", "Duration": 3, "Preceding_Process": "P1"},
    {"Job": "Job_2", "Process": "P1", "Eligible_Resources": "R1",    "Duration": 4, "Preceding_Process": ""},
    {"Job": "Job_2", "Process": "P2", "Eligible_Resources": "R2, R3", "Duration": 2, "Preceding_Process": "P1"},
])

st.sidebar.header("⏱️ Project Timeline Settings")
start_date = st.sidebar.date_input("Project Start Date", datetime.today())
deadline_days = st.sidebar.number_input("Project Deadline (Days from start)", min_value=1, value=15)

st.subheader("📋 Step 1: Define Job & Process Data")
st.markdown("*Modify the table below or paste your data. Use commas to separate multiple eligible resources.*")

# Editable dataframe
df_input = st.data_editor(
    default_data, 
    num_rows="dynamic", 
    use_container_width=True,
    column_config={
        "Eligible_Resources": st.column_config.TextColumn(help="Comma-separated resources, e.g., R1, R2"),
        "Duration": st.column_config.NumberColumn(help="Duration in days/hours"),
        "Preceding_Process": st.column_config.TextColumn(help="Process name that must finish before this one starts")
    }
)


## --------------------------------------------------------
## 3. OPTIMIZATION ENGINE (PuLP)
## --------------------------------------------------------
if st.button("🚀 Optimize Schedule", type="primary"):
    
    # Data Parsing
    tasks = []
    all_resources = set()
    
    for idx, row in df_input.iterrows():
        if pd.isna(row['Job']) or pd.isna(row['Process']):
            continue
        
        resources = [r.strip() for r in str(row['Eligible_Resources']).split(',') if r.strip()]
        for r in resources:
            all_resources.add(r)
            
        tasks.append({
            'id': f"{row['Job']}_{row['Process']}",
            'job': row['Job'],
            'process': row['Process'],
            'resources': resources,
            'duration': int(row['Duration']),
            'preceding': row['Preceding_Process'].strip() if pd.notna(row['Preceding_Process']) else ""
        })
        
    all_resources = list(all_resources)
    
    # Initialize PuLP Problem (Minimize Makespan / Total End Time)
    prob = pulp.LpProblem("Job_Scheduling", pulp.LpMinimize)
    
    # Decision Variables
    # Start times for each task
    start_vars = {t['id']: pulp.LpVariable(f"start_{t['id']}", lowBound=0, cat='Integer') for t in tasks}
    # End times for each task
    end_vars = {t['id']: pulp.LpVariable(f"end_{t['id']}", lowBound=0, cat='Integer') for t in tasks}
    # Binary variable: 1 if task t uses resource r
    assign_vars = {(t['id'], r): pulp.LpVariable(f"assign_{t['id']}_{r}", cat='Binary') for t in tasks for r in t['resources']}
    
    # Overall project completion time (Makespan)
    makespan = pulp.LpVariable("Makespan", lowBound=0, cat='Integer')
    
    # Objective Function
    prob += makespan
    
    # Constraints
    # 1. End time definition & Makespan boundary
    for t in tasks:
        prob += end_vars[t['id']] == start_vars[t['id']] + t['duration']
        prob += makespan >= end_vars[t['id']]
        
    # 2. Resource Assignment: Each task must be assigned to exactly ONE of its eligible resources
    for t in tasks:
        prob += pulp.lpSum([assign_vars[(t['id'], r)] for r in t['resources']]) == 1
        
    # 3. Precedence Constraints (Within the same Job)
    for t in tasks:
        if t['preceding']:
            # Find the preceding task id
            pred_id = f"{t['job']}_{t['preceding']}"
            if pred_id in start_vars:
                prob += start_vars[t['id']] >= end_vars[pred_id]

    # 4. Resource Overlap Constraints (No two tasks can overlap on the same resource)
    # Big-M notation to handle conditional logic
    M = 10000 
    for i in range(len(tasks)):
        for j in range(i + 1, len(tasks)):
            t1 = tasks[i]
            t2 = tasks[j]
            
            # Find common resources they both can use
            common_res = set(t1['resources']).intersection(set(t2['resources']))
            for r in common_res:
                # Binary variable: 1 if t1 runs before t2
                y = pulp.LpVariable(f"overlap_{t1['id']}_{t2['id']}_{r}", cat='Binary')
                
                # If both tasks are assigned to resource r, they must not overlap
                prob += start_vars[t1['id']] >= end_vars[t2['id']] - M * (3 - assign_vars[(t1['id'], r)] - assign_vars[(t2['id'], r)] - y)
                prob += start_vars[t2['id']] >= end_vars[t1['id']] - M * (2 - assign_vars[(t1['id'], r)] - assign_vars[(t2['id'], r)] + y)

    # 5. Deadline Constraint
    prob += makespan <= deadline_days

    # Solve
    solver = pulp.PULP_CBC_CMD(msg=False)
    status = prob.solve(solver)
    
    # Check Result Status
    if pulp.LpStatus[status] == "Optimal":
        st.success(f"✨ Optimal Schedule Found! Total project duration: **{int(makespan.varValue)} days**.")
        
        # Build Results DataFrame
        results = []
        for t in tasks:
            # Find which resource was selected
            selected_resource = None
            for r in t['resources']:
                if assign_vars[(t['id'], r)].varValue == 1:
                    selected_resource = r
                    break
            
            s_val = int(start_vars[t['id']].varValue)
            e_val = int(end_vars[t['id']].varValue)
            
            # Convert offset integers to real calendar dates
            start_date_actual = pd.to_datetime(start_date) + timedelta(days=s_val)
            end_date_actual = pd.to_datetime(start_date) + timedelta(days=e_val)
            
            results.append({
                "Job": t['job'],
                "Process": t['process'],
                "Task": f"{t['job']} ({t['process']})",
                "Resource": selected_resource,
                "Start_Day": s_val,
                "End_Day": e_val,
                "Start": start_date_actual,
                "Finish": end_date_actual
            })
            
        df_res = pd.DataFrame(results)
        
        # Display Data Table
        with st.expanders("🔍 View Schedule Data Table"):
            st.dataframe(df_res[["Job", "Process", "Resource", "Start_Day", "End_Day"]], use_container_width=True)
            
        
        
        ## --------------------------------------------------------
        ## 4. GANTT CHARTS
        ## --------------------------------------------------------
        st.subheader("📊 Step 2: Interactive Gantt Charts")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("### 🔹 Chart 1: Job View (Grouped by Job)")
            # Create Gantt categorized by Job, displaying which resource is handling it
            fig_job = px.timeline(
                df_res, 
                start="Start", 
                end="Finish", 
                y="Job", 
                color="Resource",
                text="Process",
                hover_data=["Resource", "Start_Day", "End_Day"],
                title="Timeline Grouped by Jobs"
            )
            fig_job.update_yaxes(autorange="reversed")
            fig_job.update_layout(use_container_width=True)
            st.plotly_chart(fig_job, use_container_width=True)
            
        with col2:
            st.markdown("### 🔸 Chart 2: Resource View (Grouped by Resource)")
            # Create Gantt categorized by Resource, displaying which job is running on it
            fig_res = px.timeline(
                df_res, 
                start="Start", 
                end="Finish", 
                y="Resource", 
                color="Job",
                text="Process",
                hover_data=["Job", "Start_Day", "End_Day"],
                title="Timeline Grouped by Resources"
            )
            fig_res.update_yaxes(autorange="reversed")
            fig_res.update_layout(use_container_width=True)
            st.plotly_chart(fig_res, use_container_width=True)
            
    else:
        st.error("❌ No feasible schedule found within the specified deadline. Try increasing the project deadline in the sidebar.")
