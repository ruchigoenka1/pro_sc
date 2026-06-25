import streamlit as st
import pandas as pd
import pulp
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

st.markdown("---")

## --------------------------------------------------------
## 2. SAMPLE DATA & FILE UPLOAD
## --------------------------------------------------------
# Expanded default sample data (Now with Job_3 and Job_4)
default_data = pd.DataFrame([
    {"Job": "Job_1", "Process": "P1", "Eligible_Resources": "R1, R2", "Duration": 2, "Preceding_Process": ""},
    {"Job": "Job_1", "Process": "P2", "Eligible_Resources": "R2, R3", "Duration": 3, "Preceding_Process": "P1"},
    {"Job": "Job_2", "Process": "P1", "Eligible_Resources": "R1",    "Duration": 4, "Preceding_Process": ""},
    {"Job": "Job_2", "Process": "P2", "Eligible_Resources": "R2, R3", "Duration": 2, "Preceding_Process": "P1"},
    {"Job": "Job_3", "Process": "P1", "Eligible_Resources": "R3",    "Duration": 2, "Preceding_Process": ""},
    {"Job": "Job_3", "Process": "P2", "Eligible_Resources": "R1, R2", "Duration": 3, "Preceding_Process": "P1"},
    {"Job": "Job_4", "Process": "P1", "Eligible_Resources": "R2",    "Duration": 3, "Preceding_Process": ""},
])

st.sidebar.header("⏱️ Project Timeline Settings")
start_date = st.sidebar.date_input("Project Start Date", datetime.today())
# Increased default deadline since we added more jobs
deadline_days = st.sidebar.number_input("Project Deadline (Days from start)", min_value=1, value=25)

st.subheader("📋 Step 1: Define Job & Process Data")

# File Uploader supporting both CSV and Excel
uploaded_file = st.file_uploader("Upload your scheduling data (.csv or .xlsx)", type=["csv", "xlsx"])

if uploaded_file is not None:
    try:
        # Check file extension to use the correct pandas reader
        if uploaded_file.name.endswith('.csv'):
            initial_data = pd.read_csv(uploaded_file)
        elif uploaded_file.name.endswith('.xlsx'):
            initial_data = pd.read_excel(uploaded_file)
            
        # Clean up empty values
        initial_data = initial_data.fillna("")
        st.success(f"Successfully loaded data from {uploaded_file.name}")
    except Exception as e:
        st.error(f"Error reading file: {e}")
        initial_data = default_data
else:
    st.info("Showing default demo data. Upload a file above to use your own data!")
    initial_data = default_data

st.markdown("*Modify the table below or paste your data directly into it.*")

# Editable Dataframe
df_input = st.data_editor(
    initial_data, 
    num_rows="dynamic", 
    use_container_width=True,
    column_config={
        "Eligible_Resources": st.column_config.TextColumn(help="Comma-separated resources, e.g., R1, R2"),
        "Duration": st.column_config.NumberColumn(help="Duration in days/hours"),
        "Preceding_Process": st.column_config.TextColumn(help="Process name that must finish before this one starts")
    }
)

st.markdown("---")

## --------------------------------------------------------
## 3. OPTIMIZATION ENGINE (PuLP)
## --------------------------------------------------------
if st.button("🚀 Optimize Schedule", type="primary"):
    
    # Data Parsing
    tasks = []
    all_resources = set()
    
    for idx, row in df_input.iterrows():
        if pd.isna(row['Job']) or row['Job'] == "" or pd.isna(row['Process']) or row['Process'] == "":
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
            'preceding': str(row['Preceding_Process']).strip() if pd.notna(row['Preceding_Process']) else ""
        })
        
    all_resources = list(all_resources)
    
    # Initialize PuLP Problem (Minimize Makespan)
    prob = pulp.LpProblem("Job_Scheduling", pulp.LpMinimize)
    
    # Decision Variables
    start_vars = {t['id']: pulp.LpVariable(f"start_{t['id']}", lowBound=0, cat='Integer') for t in tasks}
    end_vars = {t['id']: pulp.LpVariable(f"end_{t['id']}", lowBound=0, cat='Integer') for t in tasks}
    assign_vars = {(t['id'], r): pulp.LpVariable(f"assign_{t['id']}_{r}", cat='Binary') for t in tasks for r in t['resources']}
    makespan = pulp.LpVariable("Makespan", lowBound=0, cat='Integer')
    
    # Objective Function
    prob += makespan
    
    # Constraints
    # 1. End time definition & Makespan boundary
    for t in tasks:
        prob += end_vars[t['id']] == start_vars[t['id']] + t['duration']
        prob += makespan >= end_vars[t['id']]
        
    # 2. Resource Assignment
    for t in tasks:
        prob += pulp.lpSum([assign_vars[(t['id'], r)] for r in t['resources']]) == 1
        
    # 3. Precedence Constraints
    for t in tasks:
        if t['preceding']:
            pred_id = f"{t['job']}_{t['preceding']}"
            if pred_id in start_vars:
                prob += start_vars[t['id']] >= end_vars[pred_id]

    # 4. Resource Overlap Constraints (Big-M notation)
    M = 10000 
    for i in range(len(tasks)):
        for j in range(i + 1, len(tasks)):
            t1 = tasks[i]
            t2 = tasks[j]
            common_res = set(t1['resources']).intersection(set(t2['resources']))
            for r in common_res:
                y = pulp.LpVariable(f"overlap_{t1['id']}_{t2['id']}_{r}", cat='Binary')
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
            selected_resource = None
            for r in t['resources']:
                if assign_vars[(t['id'], r)].varValue == 1:
                    selected_resource = r
                    break
            
            s_val = int(start_vars[t['id']].varValue)
            e_val = int(end_vars[t['id']].varValue)
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
        df_res = df_res.sort_values(by=["Start_Day", "Job"])
        
        # Display Data Table (Fixed 'expander' spelling)
        with st.expander("🔍 View Schedule Data Table"):
            st.dataframe(df_res[["Job", "Process", "Resource", "Start_Day", "End_Day"]], use_container_width=True)
            
        st.markdown("---")
        
        ## --------------------------------------------------------
        ## 4. GANTT CHARTS (FULL WIDTH)
        ## --------------------------------------------------------
        st.subheader("📊 Step 2: Interactive Gantt Charts")
        
        # --- Chart 1: Job View ---
        st.markdown("### 🔹 Chart 1: Job View (Grouped by Job)")
        fig_job = px.timeline(
            df_res, 
            x_start="Start", 
            x_end="Finish", 
            y="Job", 
            color="Resource",
            text="Process",
            hover_data=["Resource", "Start_Day", "End_Day"],
            title="Timeline Grouped by Jobs",
            height=450
        )
        fig_job.update_yaxes(autorange="reversed")
        # Fixed Plotly parameter names
        fig_job.update_traces(textposition='inside', insidetextanchor='middle')
        st.plotly_chart(fig_job, use_container_width=True)
        
        st.markdown("---")
        
        # --- Chart 2: Resource View ---
        st.markdown("### 🔸 Chart 2: Resource View (Grouped by Resource)")
        fig_res = px.timeline(
            df_res, 
            x_start="Start", 
            x_end="Finish", 
            y="Resource", 
            color="Job",
            text="Process",
            hover_data=["Job", "Start_Day", "End_Day"],
            title="Timeline Grouped by Resources",
            height=450
        )
        fig_res.update_yaxes(autorange="reversed")
        # Fixed Plotly parameter names
        fig_res.update_traces(textposition='inside', insidetextanchor='middle')
        st.plotly_chart(fig_res, use_container_width=True)
            
    else:
        st.error("❌ No feasible schedule found within the specified deadline. Try increasing the project deadline in the sidebar.")
