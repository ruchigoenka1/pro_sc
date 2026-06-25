import streamlit as st
import pandas as pd
import pulp
import plotly.express as px
import graphviz
import numpy as np
from datetime import datetime, timedelta

# Import Metaheuristic libraries
from pymoo.algorithms.soo.nonconvex.ga import GA
from pymoo.optimize import minimize
from pymoo.core.problem import ElementwiseProblem
from pymoo.termination import get_termination

st.set_page_config(layout="wide", page_title="Advanced Job Scheduler")

## --------------------------------------------------------
## 1. TITLE & SETTINGS
## --------------------------------------------------------
st.title("🗓️ Smart Job & Resource Scheduler")
st.markdown("Optimize your production schedules dynamically. Features include precedence constraints, visual flow validation, sequence-dependent changeovers, and project-specific deadlines.")

st.sidebar.header("⚙️ Solver Settings")
start_date = st.sidebar.date_input("Project Start Date", datetime.today())

# Terminology updated for demo purposes
solver_choice = st.sidebar.radio(
    "Select Solving Engine:", 
    ("Optimizer", "Evolutionary Algorithm")
)

st.sidebar.markdown("---")
if solver_choice == "Optimizer":
    time_limit = st.sidebar.number_input(
        "Optimizer Time Limit (Seconds)", 
        min_value=10, max_value=1200, value=120, step=10,
        help="Limits how long the solver searches. Increase if you get timeout errors."
    )
else:
    # Labels updated for demo purposes
    ga_generations = st.sidebar.number_input(
        "No of Generation", 
        min_value=50, max_value=1000, value=100, step=50,
        help="How many evolutionary cycles to run. Higher = better results but slower."
    )
    ga_pop_size = st.sidebar.number_input(
        "Size", 
        min_value=20, max_value=500, value=50, step=10,
        help="Number of schedules tested per generation."
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

valid_df = df_input[(df_input['Job'] != '') & (df_input['Process'] != '')].copy()

st.markdown("---")

## --------------------------------------------------------
## 3. PROJECT DEADLINES
## --------------------------------------------------------
st.subheader("⏳ Step 2: Project-Specific Deadlines")
unique_jobs_list = sorted(list(valid_df['Job'].unique()))
default_deadlines = pd.DataFrame({"Job": unique_jobs_list, "Deadline (Days)": [30] * len(unique_jobs_list)})

df_deadlines = st.data_editor(default_deadlines, hide_index=True, use_container_width=True)
deadline_dict = dict(zip(df_deadlines['Job'], df_deadlines['Deadline (Days)']))

st.markdown("---")

## --------------------------------------------------------
## 4. VISUAL MAP GENERATION
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
            
            resources = [r.strip() for r in str(row['Eligible_Resources']).split(',') if r.strip()]
            if resources:
                resources_str = ", ".join(resources) 
                res_id = f"{proc_id}_all_resources" 
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
                    st.graphviz_chart(generate_single_job_flowchart(valid_df, job_name), use_container_width=True)
                except Exception as e:
                    st.warning(f"Could not render map for {job_name}.")

st.markdown("---")

## --------------------------------------------------------
## 5. CHANGEOVER MATRIX 
## --------------------------------------------------------
st.subheader("🔄 Step 4: Changeover Matrix (Job-Process Level)")
task_ids = [f"{row['Job']}_{row['Process']}" for idx, row in valid_df.iterrows()]
default_changeover = pd.DataFrame(0, index=task_ids, columns=task_ids)

with st.expander("📝 Edit Process-Level Changeover Matrix", expanded=False):
    df_changeover = st.data_editor(default_changeover, use_container_width=True)

st.markdown("---")

## --------------------------------------------------------
## 6. OPTIMIZATION LOGIC & RESULTS
## --------------------------------------------------------

# Shared result display function
def display_results(results_df, total_makespan, penalty_msg=""):
    st.success(f"✨ Schedule Found! Total overall duration: **{total_makespan} days**.")
    if penalty_msg:
        st.warning(penalty_msg)
        
    # --- NEW: Job Completion & Deadline Status Table ---
    st.subheader("📅 Step 5: Project Completion & Deadline Status")
    
    # Calculate exactly when each job finishes
    job_summary = results_df.groupby("Job").agg(
        Finished_Day=("End_Day", "max"),
        Finish_Date=("Finish", "max")
    ).reset_index()
    
    # Map the targeted deadlines
    job_summary["Deadline (Days)"] = job_summary["Job"].apply(lambda x: int(deadline_dict.get(x, 999)))
    
    # Reorganize and rename for the UI
    job_summary = job_summary[["Job", "Finish_Date", "Finished_Day", "Deadline (Days)"]]
    job_summary.rename(columns={"Finished_Day": "Total Days Taken", "Finish_Date": "Completion Date"}, inplace=True)
    
    # Highlight function: Red background if it missed the deadline
    def highlight_late_jobs(row):
        if row["Total Days Taken"] > row["Deadline (Days)"]:
            return ['background-color: rgba(255, 75, 75, 0.3); color: white; font-weight: bold;'] * len(row)
        return [''] * len(row)
        
    st.dataframe(job_summary.style.apply(highlight_late_jobs, axis=1), use_container_width=True, hide_index=True)
    
    # --- Detailed Task View ---
    with st.expander("🔍 View Detailed Task Schedule Table"):
        st.dataframe(results_df[["Job", "Process", "Resource", "Start_Day", "End_Day"]], use_container_width=True, hide_index=True)
    
    st.subheader("📊 Step 6: Interactive Gantt Charts")
    
    fig_job = px.timeline(results_df, x_start="Start", x_end="Finish", y="Job", color="Resource", text="Process", title="Timeline Grouped by Jobs", height=450)
    fig_job.update_yaxes(autorange="reversed")
    fig_job.update_traces(textposition='inside', insidetextanchor='middle')
    st.plotly_chart(fig_job, use_container_width=True)
    
    st.markdown("---")
    
    fig_res = px.timeline(results_df, x_start="Start", x_end="Finish", y="Resource", color="Job", text="Process", title="Timeline Grouped by Resources", height=450)
    fig_res.update_yaxes(autorange="reversed")
    fig_res.update_traces(textposition='inside', insidetextanchor='middle')
    st.plotly_chart(fig_res, use_container_width=True)


if st.button(f"🚀 Run {solver_choice}", type="primary"):
    
    # Parse Tasks universally
    tasks = []
    for idx, row in valid_df.iterrows():
        tasks.append({
            'id': f"{row['Job']}_{row['Process']}",
            'job': row['Job'],
            'process': row['Process'],
            'resources': [r.strip() for r in str(row['Eligible_Resources']).split(',') if r.strip()],
            'duration': int(row['Duration']),
            'preceding': [p.strip() for p in str(row['Preceding_Process']).split(',') if p.strip()]
        })

    # ==========================================
    # ENGINE A: Optimizer (PuLP)
    # ==========================================
    if solver_choice == "Optimizer":
        prob = pulp.LpProblem("Job_Scheduling", pulp.LpMinimize)
        
        start_vars = {t['id']: pulp.LpVariable(f"start_{t['id']}", lowBound=0, cat='Integer') for t in tasks}
        end_vars = {t['id']: pulp.LpVariable(f"end_{t['id']}", lowBound=0, cat='Integer') for t in tasks}
        assign_vars = {(t['id'], r): pulp.LpVariable(f"assign_{t['id']}_{r}", cat='Binary') for t in tasks for r in t['resources']}
        makespan = pulp.LpVariable("Makespan", lowBound=0, cat='Integer')
        
        prob += makespan
        
        for t in tasks:
            prob += end_vars[t['id']] == start_vars[t['id']] + t['duration']
            prob += makespan >= end_vars[t['id']]
            prob += pulp.lpSum([assign_vars[(t['id'], r)] for r in t['resources']]) == 1
            for pred in t['preceding']:
                pred_id = f"{t['job']}_{pred}"
                if pred_id in start_vars:
                    prob += start_vars[t['id']] >= end_vars[pred_id]

        max_deadline = max(list(deadline_dict.values())) if deadline_dict else 100
        M = max(1000, max_deadline * 3) 
        
        for i in range(len(tasks)):
            for j in range(i + 1, len(tasks)):
                t1, t2 = tasks[i], tasks[j]
                common_res = set(t1['resources']).intersection(set(t2['resources']))
                if common_res:
                    y = pulp.LpVariable(f"seq_{t1['id']}_{t2['id']}", cat='Binary')
                    for r in common_res:
                        c12 = int(df_changeover.loc[t1['id'], t2['id']]) if t1['id'] in df_changeover.index and t2['id'] in df_changeover.columns else 0
                        c21 = int(df_changeover.loc[t2['id'], t1['id']]) if t2['id'] in df_changeover.index and t1['id'] in df_changeover.columns else 0
                        prob += start_vars[t2['id']] >= end_vars[t1['id']] + c12 - M * (3 - assign_vars[(t1['id'], r)] - assign_vars[(t2['id'], r)] - y)
                        prob += start_vars[t1['id']] >= end_vars[t2['id']] + c21 - M * (2 - assign_vars[(t1['id'], r)] - assign_vars[(t2['id'], r)] + y)

        for t in tasks:
            prob += end_vars[t['id']] <= int(deadline_dict.get(t['job'], 999))

        solver = pulp.PULP_CBC_CMD(timeLimit=time_limit, msg=False)
        with st.spinner(f"Optimizing schedule... (Max {time_limit}s)"):
            status = prob.solve(solver)
        
        if pulp.LpStatus[status] in ["Optimal", "Not Solved"] and start_vars[tasks[0]['id']].varValue is not None:
            results = []
            for t in tasks:
                sel_res = [r for r in t['resources'] if assign_vars[(t['id'], r)].varValue is not None and assign_vars[(t['id'], r)].varValue > 0.5]
                if not sel_res: continue
                s_val, e_val = int(start_vars[t['id']].varValue), int(end_vars[t['id']].varValue)
                results.append({
                    "Job": t['job'], "Process": t['process'], "Resource": sel_res[0],
                    "Start_Day": s_val, "End_Day": e_val,
                    "Start": pd.to_datetime(start_date) + timedelta(days=s_val),
                    "Finish": pd.to_datetime(start_date) + timedelta(days=e_val)
                })
                
            df_res = pd.DataFrame(results).sort_values(by=["Start_Day", "Job"])
            
            # Validation Check
            is_valid = True
            df_res_check = df_res.sort_values(by=["Resource", "Start_Day"])
            for res in df_res_check['Resource'].unique():
                prev_end = -1
                for _, row in df_res_check[df_res_check['Resource'] == res].iterrows():
                    if row['Start_Day'] < prev_end: is_valid = False
                    prev_end = row['End_Day']
                    
            if not is_valid:
                st.error("⚠️ **Timeout:** The optimizer could not find a strictly valid schedule in the allotted time. Please increase the Time Limit.")
            else:
                display_results(df_res, int(makespan.varValue))
        else:
            st.error("❌ No feasible schedule found. Deadlines may be too tight for the given workloads and changeovers.")


    # ==========================================
    # ENGINE B: Evolutionary Algorithm
    # ==========================================
    else:
        def decode_schedule(priorities, t_list, d_dict, c_df):
            sorted_indices = np.argsort(priorities)
            res_avail = {}
            res_last_job = {}
            task_ends = {}
            schedule = []
            
            for t in t_list:
                for r in t['resources']: res_avail[r] = 0
                
            penalty = 0
            
            for idx in sorted_indices:
                t = t_list[idx]
                
                pred_ready_time = 0
                for pred in t['preceding']:
                    pred_id = f"{t['job']}_{pred}"
                    pred_ready_time = max(pred_ready_time, task_ends.get(pred_id, 0))
                
                best_start = float('inf')
                best_res = None
                
                for r in t['resources']:
                    c_time = 0
                    last_task_id = res_last_job.get(r)
                    if last_task_id and last_task_id in c_df.index and t['id'] in c_df.columns:
                        c_time = int(c_df.loc[last_task_id, t['id']])
                        
                    possible_start = max(pred_ready_time, res_avail.get(r, 0) + c_time)
                    if possible_start < best_start:
                        best_start = possible_start
                        best_res = r
                
                duration = t['duration']
                end = best_start + duration
                
                res_avail[best_res] = end
                res_last_job[best_res] = t['id']
                task_ends[t['id']] = end
                
                deadline = int(d_dict.get(t['job'], 999))
                if end > deadline:
                    penalty += (end - deadline) * 100 
                
                schedule.append({
                    "Job": t['job'], "Process": t['process'], "Resource": best_res,
                    "Start_Day": best_start, "End_Day": end,
                    "Start": pd.to_datetime(start_date) + timedelta(days=best_start),
                    "Finish": pd.to_datetime(start_date) + timedelta(days=end)
                })
                
            makespan = max(task_ends.values()) if task_ends else 0
            return schedule, makespan, penalty

        class JobShopGA(ElementwiseProblem):
            def __init__(self, t_list, d_dict, c_df):
                super().__init__(n_var=len(t_list), n_obj=1, xl=0, xu=1)
                self.t_list = t_list
                self.d_dict = d_dict
                self.c_df = c_df

            def _evaluate(self, x, out, *args, **kwargs):
                _, makespan, penalty = decode_schedule(x, self.t_list, self.d_dict, self.c_df)
                out["F"] = makespan + penalty

        with st.spinner(f"Evolving schedule... ({ga_generations} Generations)"):
            problem = JobShopGA(tasks, deadline_dict, df_changeover)
            algorithm = GA(pop_size=ga_pop_size)
            termination = get_termination("n_gen", ga_generations)
            
            res = minimize(problem, algorithm, termination, seed=1, verbose=False)
            
            best_schedule, best_makespan, final_penalty = decode_schedule(res.X, tasks, deadline_dict, df_changeover)
            df_res = pd.DataFrame(best_schedule).sort_values(by=["Start_Day", "Job"])
            
            msg = ""
            if final_penalty > 0:
                msg = "⚠️ The Evolutionary Algorithm could not meet all deadlines within the given generations. Some jobs are late."
                
            display_results(df_res, best_makespan, penalty_msg=msg)
