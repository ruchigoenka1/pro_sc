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
st.markdown("Optimize schedules using PuLP. Features include precedence constraints, visual flow validation, and sequence-dependent changeovers.")

st.sidebar.header("⏱️ Optimization Settings")
start_date = st.sidebar.date_input("Project Start Date", datetime.today())
deadline_days = st.sidebar.number_input("Project Deadline (Days)", min_value=1, value=25)

# NEW: Optimizer time limit
st.sidebar.markdown("---")
time_limit = st.sidebar.slider(
    "Optimizer Time Limit (Seconds)", 
    min_value=10, max_value=300, value=60, step=10,
    help="Limits how long the solver searches for an optimal solution. Crucial when adding changeover matrices."
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
    {"Job": "P2", "Process": "A", "Eligible_Resources": "R2", "Duration": 3, "Preceding_Process": ""},
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

st.markdown("---")

## --------------------------------------------------------
## 3. VISUAL MAP GENERATION (Graphviz)
## --------------------------------------------------------
st.subheader("🗺️ Step 2: Verify Process Flow")
st.markdown("This map is generated dynamically from your data to ensure dependencies are correct.")

def generate_flowchart(df):
    dot = graphviz.Digraph(comment='Process Flow')
    dot.attr(rankdir='LR') # Left to Right layout
    
    # Filter out empty rows
    valid_df = df[(df['Job'] != '') & (df['Process'] != '')].copy()
    jobs = valid_df['Job'].unique()
    
    for job in jobs:
        # Add Job Node (Blue Square)
        dot.node(job, job, shape='box', style='filled', fillcolor='#4A71B5', fontcolor='white')
        
        job_data = valid_df[valid_df['Job'] == job]
        for idx, row in job_data.iterrows():
            process = str(row['Process']).strip()
            proc_id = f"{job}_{process}"
            
            # Add Process Node (Beige Square)
            dot.node(proc_id, process, shape='box', style='rounded,filled', fillcolor='#F2D5BA')
            
            # Add Resource Dependencies (Triangles)
            resources = [r.strip() for r in str(row['Eligible_Resources']).split(',') if r.strip()]
            for res in resources:
                res_id = f"{proc_id}_{res}"
                dot.node(res_id, res, shape='triangle', style='filled', fillcolor='#CBE0BE')
                dot.edge(proc_id, res_id, arrowhead='none', style='dotted')
            
            # Add Precedence Edges
            preceding_str = str(row['Preceding_Process']).strip()
            if preceding_str:
                # Handle multiple preceding processes (e.g. "C, D")
                preceding_list = [p.strip() for p in preceding_str.split(',') if p.strip()]
                for pred in preceding_list:
                    pred_id = f"{job}_{pred}"
                    dot.edge(pred_id, proc_id, color='#E28743')
            else:
                # If no preceding process, it connects directly to the Job
                dot.edge(job, proc_id, color='#E28743')
                
    return dot

with st.expander("👁️ View Process Flow Map", expanded=True):
    try:
        flow_graph = generate_flowchart(df_input)
        st.graphviz_chart(flow_graph, use_container_width=True)
    except Exception as e:
        st.warning("Ensure your table data is valid to render the map.")

st.markdown("---")

## --------------------------------------------------------
## 4. CHANGEOVER MATRIX
## --------------------------------------------------------
st.subheader("🔄 Step 3: Changeover Matrix (Sequence-Dependent Setup)")
st.markdown("Define the time penalty (in days) when a resource switches from one Job to another.")

valid_df = df_input[(df_input['Job'] != '') & (df_input['Process'] != '')]
unique_jobs = sorted(list(valid_df['Job'].unique()))

# Create an N x N matrix filled with 0s by default
default_changeover = pd.DataFrame(0, index=unique_jobs, columns=unique_jobs)
df_changeover = st.data_editor(default_changeover, use_container_width=True)

st.markdown("---")

## --------------------------------------------------------
## 5. OPTIMIZATION ENGINE (PuLP)
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
    
    # 1. End time & Makespan
    for t in tasks:
        prob += end_vars[t['id']] == start_vars[t['id']] + t['duration']
        prob += makespan >= end_vars[t['id']]
        
    # 2. Resource Assignment
    for t in tasks:
        prob += pulp.lpSum([assign_vars[(t['id'], r)] for r in t['resources']]) == 1
        
    # 3. Precedence Constraints (Supports multiple predecessors)
    for t in tasks:
        for pred in t['preceding']:
            pred_id = f"{t['job']}_{pred}"
            if pred_id in start_vars:
                prob += start_vars[t['id']] >= end_vars[pred_id]

    # 4. Resource Overlap & Changeover Time Constraints
    M = 10000 
    for i in range(len(tasks)):
        for j in range(i + 1, len(tasks)):
            t1 = tasks[i]
            t2 = tasks[j]
            common_res = set(t1['resources']).intersection(set(t2['resources']))
            
            for r in common_res:
                y = pulp.LpVariable(f"overlap_{t1['id']}_{t2['id']}_{r}", cat='Binary')
                
                # Fetch sequence-dependent changeover penalties from the matrix
                c_time_1_to_2 = int(df_changeover.loc[t1['job'], t2['job']]) if t1['job'] != t2['job'] else 0
                c_time_2_to_1 = int(df_changeover.loc[t2['job'], t1['job']]) if t1['job'] != t2['job'] else 0
                
                # If t1 and t2 share a resource, they cannot overlap. Plus, add changeover time!
                prob += start_vars[t2['id']] >= end_vars[t1['id']] + c_time_1_to_2 - M * (3 - assign_vars[(t1['id'], r)] - assign_vars[(t2['id'], r)] - y)
                prob += start_vars[t1['id']] >= end_vars[t2['id']] + c_time_2_to_1 - M * (2 - assign_vars[(t1['id'], r)] - assign_vars[(t2['id'], r)] + y)

    prob += makespan <= deadline_days

    # Solve with user-defined Time Limit
    solver = pulp.PULP_CBC_CMD(timeLimit=time_limit, msg=False)
    with st.spinner(f"Optimizing... (Max time limit: {time_limit} seconds)"):
        status = prob.solve(solver)
    
    if pulp.LpStatus[status] in ["Optimal", "Not Solved"]: # Not solved might mean feasible but hit time limit
        # Check if we actually have a feasible solution even if it hit the time limit
        if start_vars[tasks[0]['id']].varValue is not None:
            st.success(f"✨ Schedule Found! Total project duration: **{int(makespan.varValue)} days**.")
            
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
            
            st.subheader("📊 Step 4: Interactive Gantt Charts")
            
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
            st.error("❌ No feasible schedule found. Try increasing the deadline or relaxing constraints.")
    else:
        st.error("❌ Optimization failed. Try increasing the deadline or the optimizer time limit.")
