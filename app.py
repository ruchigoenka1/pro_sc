import streamlit as st
import pandas as pd
import pulp
import plotly.express as px
import graphviz
from datetime import datetime, timedelta

st.set_page_config(layout="wide", page_title="Advanced Job Scheduler")

## --------------------------------------------------------
## 1. TITLE & SETTINGS
## --------------------------------------------------------
st.title("🗓️ Smart Job & Resource Scheduler")
st.markdown("Optimize schedules using PuLP. Features include precedence constraints, visual flow validation, sequence-dependent changeovers, and project-specific deadlines.")

st.sidebar.header("⏱️ Optimization Settings")
start_date = st.sidebar.date_input("Project Start Date", datetime.today())

st.sidebar.markdown("---")
time_limit = st.sidebar.number_input(
    "Optimizer Time Limit (Seconds)", 
    min_value=1, max_value=600, value=60, step=10,
    help="Limits how long the solver searches for an optimal solution. Crucial when adding complex changeover matrices."
)

st.markdown("---")

## --------------------------------------------------------
## 2. DATA ENTRY
## --------------------------------------------------------
st.subheader("📋 Step 1: Define Job & Process Data")

default_data = pd.DataFrame([
    {"Job": "P1", "Process": "A", "Eligible_Resources": "R1", "Duration": 2, "Preceding_Process": ""},
    {"Job": "P1", "Process": "B", "Eligible_Resources": "R2", "Duration": 3, "Preceding_Process": "A"},
    {"Job": "P1", "Process": "C", "Eligible_Resources": "R2", "Duration": 2, "Preceding_Process": "B"},
    {"Job": "P1", "Process": "D", "Eligible_Resources": "R1", "Duration": 4, "Preceding_Process": "B"},
    {"Job": "P1", "Process": "E", "Eligible_Resources": "R1", "Duration": 2, "Preceding_Process": "C, D"},
    {"Job": "P2", "Process": "A", "Eligible_Resources": "R2, R1", "Duration": 3, "Preceding_Process": ""},
    {"Job": "P2", "Process": "B", "Eligible_Resources": "R1", "Duration": 2, "Preceding_Process": "A"},
])

uploaded_file = st.file_uploader("Upload your scheduling data (.csv or .xlsx)", type=["csv", "xlsx"])

if uploaded_file is not None:
    try:
        if uploaded_file.name.endswith('.csv'):
            initial_data = pd.read_csv(uploaded_file)
        elif uploaded_file.name.endswith('.xlsx'):
            initial_data = pd.read_excel(uploaded_file)
        initial_data = initial_data.fillna("")
    except Exception as e:
        st.error(f"Error reading file: {e}")
        initial_data = default_data
else:
    initial_data = default_data

df_input = st.data_editor(initial_data, num_rows="dynamic", use_container_width=True)

# Filter out empty rows for subsequent steps
valid_df = df_input[(df_input['Job'] != '') & (df_input['Process'] != '')].copy()

st.markdown("---")

## --------------------------------------------------------
## 3. PROJECT DEADLINES
## --------------------------------------------------------
st.subheader("⏳ Step 2: Project-Specific Deadlines")
st.markdown("Set a specific deadline (in days from the start date) for each individual job/product.")

unique_jobs_list = sorted(list(valid_df['Job'].unique()))
default_deadlines = pd.DataFrame({"Job": unique_jobs_list, "Deadline (Days)": [25] * len(unique_jobs_list)})

df_deadlines = st.data_editor(default_deadlines, hide_index=True, use_container_width=True)
# Convert to a dictionary for easy lookup during optimization
deadline_dict = dict(zip(df_deadlines['Job'], df_deadlines['Deadline (Days)']))

st.markdown("---")

## --------------------------------------------------------
## 4. VISUAL MAP GENERATION (Graphviz)
## --------------------------------------------------------
st.subheader("🗺️ Step 3: Verify Process Flow")

def generate_single_job_flowchart(df, job_name):
    dot = graphviz.Digraph(comment=f'Process Flow {job_name}')
    dot.attr(bgcolor='black', rankdir='LR')
    job_data = df[df['Job'] == job_name]
    dot.node(job_name, job_name, shape='box', style='filled', fillcolor='#4A71B5', fontcolor='white', color='white')
    
    for idx, row in job_data.iterrows():
        process = str(row['Process']).strip()
        proc_id = f"{job_name}_{process}"
        
        with dot.subgraph() as s:
            s.attr(rank='same') 
            s.node(proc_id, process, shape='box', style='rounded,filled', fillcolor='#F2D5BA', fontcolor='black', color='white')
            
            # Combine all eligible resources into a single string
            resources = [r.strip() for r in str(row['Eligible_Resources']).split(',') if r.strip()]
            if resources:
                resources_str = ", ".join(resources) 
                res_id = f"{proc_id}_all_resources" 
                
                # Create a single triangle containing all resources
                s.node(res_id, resources_str, shape='triangle', style='filled', fillcolor='#CBE0BE', fontcolor='black', color='white')
                s.edge(proc_id, res_id, arrowhead='none', style='dotted', color='white')
        
        preceding_str = str(row['Preceding_Process']).strip()
        if preceding_str:
            preceding_list = [p.strip() for p in preceding_str.split(',') if p.strip()]
            for pred in preceding_list:
                pred_id = f"{job_name}_{pred}"
                dot.edge(pred_id, proc_id, color='#E28743', penwidth='2')
        else:
            dot.edge(job_name, proc_id, color='#E28743', penwidth='2')
            
    return dot

with st.expander("👁️ View Process Flow Map", expanded=False):
    if not valid_df.empty:
        tabs = st.tabs(unique_jobs_list)
        for idx, job_name in enumerate(unique_jobs_list):
            with tabs[idx]:
                try:
                    flow_graph = generate_single_job_flowchart(valid_df, job_name)
                    st.graphviz_chart(flow_graph, use_container_width=True)
                except Exception as e:
                    st.warning(f"Could not render map for {job_name}. Ensure table data is valid.")

st.markdown("---")

## --------------------------------------------------------
## 5. CHANGEOVER MATRIX 
## --------------------------------------------------------
st.subheader("🔄 Step 4: Changeover Matrix (Job-Process Level)")
st.markdown("Define time penalties (in days) when a resource switches between specific processes. e.g., P1_A to P2_A.")

# Create unique IDs for every Job_Process combination
task_ids = [f"{row['Job']}_{row['Process']}" for idx, row in valid_df.iterrows()]

default_changeover = pd.DataFrame(0, index=task_ids, columns=task_ids)
with st.expander("📝 Edit Process-Level Changeover Matrix", expanded=True):
    df_changeover = st.data_editor(default_changeover, use_container_width=True)

st.markdown("---")

## --------------------------------------------------------
## 6. OPTIMIZATION ENGINE (PuLP)
## --------------------------------------------------------
if st.button("🚀 Optimize Schedule", type="primary"):
    
    tasks = []
    
    for idx, row in valid_df.iterrows():
        resources = [r.strip() for r in str(row['Eligible_Resources']).split(',') if r.strip()]
        preceding = [p.strip() for p in str(row['Preceding_Process']).split(',') if p.strip()]
            
        tasks.append({
            'id': f"{row['Job']}_{row['Process']}",
            'job': row['Job'],
            'process': row['Process'],
            'resources': resources,
            'duration': int(row['Duration']),
            'preceding': preceding
        })
    
    prob = pulp.LpProblem("Job_Scheduling", pulp.LpMinimize)
    
    start_vars = {t['id']: pulp.LpVariable(f"start_{t['id']}", lowBound=0, cat='Integer') for t in tasks}
    end_vars = {t['id']: pulp.LpVariable(f"end_{t['id']}", lowBound=0, cat='Integer') for t in tasks}
    assign_vars = {(t['id'], r): pulp.LpVariable(f"assign_{t['id']}_{r}", cat='Binary') for t in tasks for r in t['resources']}
    makespan = pulp.LpVariable("Makespan", lowBound=0, cat='Integer')
    
    prob += makespan
    
    # 1. Duration logic
    for t in tasks:
        prob += end_vars[t['id']] == start_vars[t['id']] + t['duration']
        prob += makespan >= end_vars[t['id']]
        
    # 2. Resource Assignment
    for t in tasks:
        prob += pulp.lpSum([assign_vars[(t['id'], r)] for r in t['resources']]) == 1
        
    # 3. Precedence Constraints
    for t in tasks:
        for pred in t['preceding']:
            pred_id = f"{t['job']}_{pred}"
            if pred_id in start_vars:
                prob += start_vars[t['id']] >= end_vars[pred_id]

    # 4. Resource Overlap & Process-Level Changeover Time
    M = 10000 
    for i in range(len(tasks)):
        for j in range(i + 1, len(tasks)):
            t1 = tasks[i]
            t2 = tasks[j]
            common_res = set(t1['resources']).intersection(set(t2['resources']))
            
            for r in common_res:
                y = pulp.LpVariable(f"overlap_{t1['id']}_{t2['id']}_{r}", cat='Binary')
                
                # Retrieve penalty based on exact Job_Process ID
                c_time_1_to_2 = int(df_changeover.loc[t1['id'], t2['id']]) if t1['id'] != t2['id'] else 0
                c_time_2_to_1 = int(df_changeover.loc[t2['id'], t1['id']]) if t1['id'] != t2['id'] else 0
                
                prob += start_vars[t2['id']] >= end_vars[t1['id']] + c_time_1_to_2 - M * (3 - assign_vars[(t1['id'], r)] - assign_vars[(t2['id'], r)] - y)
                prob += start_vars[t1['id']] >= end_vars[t2['id']] + c_time_2_to_1 - M * (2 - assign_vars[(t1['id'], r)] - assign_vars[(t2['id'], r)] + y)

    # 5. Project-Specific Deadlines
    for t in tasks:
        job_deadline = int(deadline_dict.get(t['job'], 999))
        prob += end_vars[t['id']] <= job_deadline

    solver = pulp.PULP_CBC_CMD(timeLimit=time_limit, msg=False)
    with st.spinner(f"Optimizing... (Max time limit: {time_limit} seconds)"):
        status = prob.solve(solver)
    
    if pulp.LpStatus[status] in ["Optimal", "Not Solved"]:
        if start_vars[tasks[0]['id']].varValue is not None:
            st.success(f"✨ Schedule Found! Total overall duration: **{int(makespan.varValue)} days**.")
            
            results = []
            for t in tasks:
                selected_resource = [r for r in t['resources'] if assign_vars[(t['id'], r)].varValue == 1][0]
                s_val = int(start_vars[t['id']].varValue)
                e_val = int(end_vars[t['id']].varValue)
                
                results.append({
                    "Job": t['job'],
                    "Process": t['process'],
                    "Resource": selected_resource,
                    "Start_Day": s_val,
                    "End_Day": e_val,
                    "Start": pd.to_datetime(start_date) + timedelta(days=s_val),
                    "Finish": pd.to_datetime(start_date) + timedelta(days=e_val)
                })
                
            df_res = pd.DataFrame(results).sort_values(by=["Start_Day", "Job"])
            
            with st.expander("🔍 View Schedule Data Table"):
                st.dataframe(df_res[["Job", "Process", "Resource", "Start_Day", "End_Day"]], use_container_width=True)
            
            st.subheader("📊 Step 5: Interactive Gantt Charts")
            
            fig_job = px.timeline(df_res, x_start="Start", x_end="Finish", y="Job", color="Resource", text="Process", title="Timeline Grouped by Jobs", height=450)
            fig_job.update_yaxes(autorange="reversed")
            fig_job.update_traces(textposition='inside', insidetextanchor='middle')
            st.plotly_chart(fig_job, use_container_width=True)
            
            st.markdown("---")
            
            fig_res = px.timeline(df_res, x_start="Start", x_end="Finish", y="Resource", color="Job", text="Process", title="Timeline Grouped by Resources", height=450)
            fig_res.update_yaxes(autorange="reversed")
            fig_res.update_traces(textposition='inside', insidetextanchor='middle')
            st.plotly_chart(fig_res, use_container_width=True)
        else:
            st.error("❌ No feasible schedule found. Check if your project-specific deadlines are too tight.")
    else:
        st.error("❌ Optimization failed. Try increasing deadlines or the optimizer time limit.")
