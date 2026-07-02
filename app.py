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
## 1. TITLE & MODE SELECTION
## --------------------------------------------------------
st.title("🗓️ Smart Job & Resource Scheduler")
st.markdown("Optimize production workflows or run strategic capacity assessments dynamically.")

st.sidebar.header("⚙️ Global Settings")
start_date = st.sidebar.date_input("Project Start Date", datetime.today())

# NEW: Toggle between the two primary business analyses
analysis_mode = st.sidebar.selectbox(
    "Select Analysis Mode:",
    ("Demand Scheduling (Fixed Deadlines)", "Maximum Capacity Assessment (Fixed Time Span)")
)

solver_choice = st.sidebar.radio(
    "Select Solving Engine:", 
    ("Optimizer", "Evolutionary Algorithm")
)

st.sidebar.markdown("---")
st.sidebar.header("⏱️ Engine Parameters")

if solver_choice == "Optimizer":
    time_limit = st.sidebar.number_input(
        "Optimizer Time Limit (Seconds)", 
        min_value=10, max_value=1200, value=120, step=10,
        help="Limits how long the solver searches. Increase if you get timeout errors."
    )
else:
    ga_generations = st.sidebar.number_input(
        "No of Generation", 
        min_value=50, max_value=1000, value=100, step=50
    )
    ga_pop_size = st.sidebar.number_input(
        "Size", 
        min_value=20, max_value=500, value=50, step=10
    )

st.markdown("---")

## --------------------------------------------------------
## 2. STEP 1: DATA ENTRY (BASE RECIPES / ORDERS)
## --------------------------------------------------------
st.subheader("📋 Step 1: Define Job & Process Data")
if analysis_mode == "Maximum Capacity Assessment (Fixed Time Span)":
    st.info("💡 **Capacity Mode Active:** Enter details below to represent **1 Unit** of the job. The system will figure out how many units can fit in your timeline.")

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
## 3. STEP 2: TEMPORAL BOUNDS (DEADLINES OR TIME SPAN)
## --------------------------------------------------------
unique_jobs_list = sorted(list(valid_df['Job'].unique()))

if analysis_mode == "Demand Scheduling (Fixed Deadlines)":
    st.subheader("⏳ Step 2: Project-Specific Deadlines")
    st.markdown("Set a specific deadline (in days from the start date) for each individual job/product.")
    default_deadlines = pd.DataFrame({"Job": unique_jobs_list, "Deadline (Days)": [30] * len(unique_jobs_list)})
    df_deadlines = st.data_editor(default_deadlines, hide_index=True, use_container_width=True)
    deadline_dict = dict(zip(df_deadlines['Job'], df_deadlines['Deadline (Days)']))
else:
    st.subheader("⏳ Step 2: Planning Time Horizon & Assessment Bounds")
    col_cap1, col_cap2 = st.columns(2)
    with col_cap1:
        time_span = st.number_input("Planning Time Span Horizon (Days)", min_value=10, max_value=5000, value=1000, step=50, help="The model maximizes throughput within this window.")
    with col_cap2:
        max_instances = st.number_input("Max Instances per Job Type to Evaluate", min_value=2, max_value=50, value=8, step=1, help="Upper variable bound for tracking scaling configurations.")

st.markdown("---")

## --------------------------------------------------------
## 4. STEP 3: VISUAL MAP GENERATION
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
## 5. STEP 4: CHANGEOVER MATRIX
## --------------------------------------------------------
st.subheader("🔄 Step 4: Changeover Matrix (Job-Process Level)")
task_ids = [f"{row['Job']}_{row['Process']}" for idx, row in valid_df.iterrows()]
default_changeover = pd.DataFrame(0, index=task_ids, columns=task_ids)

with st.expander("📝 Edit Process-Level Changeover Matrix", expanded=False):
    df_changeover = st.data_editor(default_changeover, use_container_width=True)

st.markdown("---")

## --------------------------------------------------------
## 6. OPTIMIZATION LOGIC & RESULTS COMPONENT
## --------------------------------------------------------

def display_scheduling_results(results_df, total_makespan, penalty_msg=""):
    st.success(f"✨ Schedule Found! Total overall duration: **{total_makespan} days**.")
    if penalty_msg: st.warning(penalty_msg)
        
    st.subheader("📅 Step 5: Project Completion & Deadline Status")
    job_summary = results_df.groupby("Job").agg(Finished_Day=("End_Day", "max"), Finish_Date=("Finish", "max")).reset_index()
    job_summary["Deadline (Days)"] = job_summary["Job"].apply(lambda x: int(deadline_dict.get(x, 999)))
    job_summary = job_summary[["Job", "Finish_Date", "Finished_Day", "Deadline (Days)"]]
    job_summary.rename(columns={"Finished_Day": "Total Days Taken", "Finish_Date": "Completion Date"}, inplace=True)
    
    def highlight_late_jobs(row):
        if row["Total Days Taken"] > row["Deadline (Days)"]:
            return ['background-color: rgba(255, 75, 75, 0.3); color: white; font-weight: bold;'] * len(row)
        return [''] * len(row)
    st.dataframe(job_summary.style.apply(highlight_late_jobs, axis=1), use_container_width=True, hide_index=True)
    
    with st.expander("🔍 View Detailed Task Schedule Table"):
        st.dataframe(results_df[["Job", "Process", "Resource", "Start_Day", "End_Day"]], use_container_width=True, hide_index=True)
    
    render_gantt_charts(results_df)

def display_capacity_results(results_df, horizon):
    st.success("✨ Strategic Capacity Assessment Complete!")
    
    # 1. Output Summary Table
    st.subheader("📊 Step 5: Optimal Capacity Output Summary")
    results_df["Instance_Count"] = 1
    summary = results_df.groupby("Base_Job").agg(
        Total_Units_Produced=("Job", "nunique"),
        Last_Unit_Finished_Day=("End_Day", "max")
    ).reset_index()
    summary.rename(columns={"Base_Job": "Job Type"}, inplace=True)
    st.dataframe(summary, use_container_width=True, hide_index=True)
    
    # 2. Machine Utilization Statistics
    st.subheader("🏭 Step 6: Asset Utilization Metrics")
    all_resources = results_df['Resource'].unique()
    metric_cols = st.columns(len(all_resources))
    
    for idx, res in enumerate(sorted(all_resources)):
        res_data = results_df[results_df['Resource'] == res]
        total_active_time = res_data['Duration'].sum()
        utilization_pct = min(100.0, (total_active_time / horizon) * 100)
        with metric_cols[idx]:
            st.metric(label=f"Machine {res} Utilization", value=f"{utilization_pct:.1f}%", delta=f"{total_active_time} active days")
            
    with st.expander("🔍 View Volumetric Production Sequence Logs"):
        st.dataframe(results_df[["Job", "Process", "Resource", "Start_Day", "End_Day"]], use_container_width=True, hide_index=True)
        
    render_gantt_charts(results_df)

def render_gantt_charts(df):
    st.subheader("📊 Interactive Sequence Gantt Charts")
    fig_job = px.timeline(df, x_start="Start", x_end="Finish", y="Job", color="Resource", text="Process", title="Timeline Grouped by Production Batches", height=450)
    fig_job.update_yaxes(autorange="reversed")
    fig_job.update_traces(textposition='inside', insidetextanchor='middle')
    st.plotly_chart(fig_job, use_container_width=True)
    st.markdown("---")
    fig_res = px.timeline(df, x_start="Start", x_end="Finish", y="Resource", color="Job", text="Process", title="Timeline Grouped by Resource Allocation", height=450)
    fig_res.update_yaxes(autorange="reversed")
    fig_res.update_traces(textposition='inside', insidetextanchor='middle')
    st.plotly_chart(fig_res, use_container_width=True)

# Parse Baseline Data
base_tasks = []
for idx, row in valid_df.iterrows():
    base_tasks.append({
        'id': f"{row['Job']}_{row['Process']}",
        'job': row['Job'],
        'process': row['Process'],
        'resources': [r.strip() for r in str(row['Eligible_Resources']).split(',') if r.strip()],
        'duration': int(row['Duration']),
        'preceding': [p.strip() for p in str(row['Preceding_Process']).split(',') if p.strip()]
    })

if st.button(f"🚀 Run {solver_choice}", type="primary"):
    if not base_tasks:
        st.error("Please ensure you have inputted process recipes in Step 1.")
        st.stop()

    # =========================================================================
    # ANALYSIS MODE: DEMAND SCHEDULING (FIXED OBJECTS)
    # =========================================================================
    if analysis_mode == "Demand Scheduling (Fixed Deadlines)":
        if solver_choice == "Optimizer":
            prob = pulp.LpProblem("Demand_Scheduling", pulp.LpMinimize)
            start_vars = {t['id']: pulp.LpVariable(f"start_{t['id']}", lowBound=0, cat='Integer') for t in base_tasks}
            end_vars = {t['id']: pulp.LpVariable(f"end_{t['id']}", lowBound=0, cat='Integer') for t in base_tasks}
            assign_vars = {(t['id'], r): pulp.LpVariable(f"assign_{t['id']}_{r}", cat='Binary') for t in base_tasks for r in t['resources']}
            makespan = pulp.LpVariable("Makespan", lowBound=0, cat='Integer')
            
            # Hybrid objective: Minimize makespan primarily, pull individuals left ASAP
            prob += makespan * 1000 + pulp.lpSum([end_vars[t['id']] for t in base_tasks])
            
            for t in base_tasks:
                prob += end_vars[t['id']] == start_vars[t['id']] + t['duration']
                prob += makespan >= end_vars[t['id']]
                prob += pulp.lpSum([assign_vars[(t['id'], r)] for r in t['resources']]) == 1
                for pred in t['preceding']:
                    pred_id = f"{t['job']}_{pred}"
                    if pred_id in start_vars: prob += start_vars[t['id']] >= end_vars[pred_id]

            M = max(1000, max(list(deadline_dict.values())) * 3) if deadline_dict else 3000
            for i in range(len(base_tasks)):
                for j in range(i + 1, len(base_tasks)):
                    t1, t2 = base_tasks[i], base_tasks[j]
                    common_res = set(t1['resources']).intersection(set(t2['resources']))
                    if common_res:
                        y = pulp.LpVariable(f"seq_{t1['id']}_{t2['id']}", cat='Binary')
                        for r in common_res:
                            c12 = int(df_changeover.loc[t1['id'], t2['id']]) if t1['id'] in df_changeover.index and t2['id'] in df_changeover.columns else 0
                            c21 = int(df_changeover.loc[t2['id'], t1['id']]) if t2['id'] in df_changeover.index and t1['id'] in df_changeover.columns else 0
                            prob += start_vars[t2['id']] >= end_vars[t1['id']] + c12 - M * (3 - assign_vars[(t1['id'], r)] - assign_vars[(t2['id'], r)] - y)
                            prob += start_vars[t1['id']] >= end_vars[t2['id']] + c21 - M * (2 - assign_vars[(t1['id'], r)] - assign_vars[(t2['id'], r)] + y)

            for t in base_tasks: prob += end_vars[t['id']] <= int(deadline_dict.get(t['job'], 999))

            solver = pulp.PULP_CBC_CMD(timeLimit=time_limit, msg=False)
            with st.spinner("Calculating exact optimal schedule..."): status = prob.solve(solver)
            
            if pulp.LpStatus[status] in ["Optimal", "Not Solved"] and start_vars[base_tasks[0]['id']].varValue is not None:
                results = []
                for t in base_tasks:
                    sel_res = [r for r in t['resources'] if assign_vars[(t['id'], r)].varValue > 0.5][0]
                    s_val, e_val = int(start_vars[t['id']].varValue), int(end_vars[t['id']].varValue)
                    results.append({
                        "Job": t['job'], "Process": t['process'], "Resource": sel_res, "Duration": t['duration'],
                        "Start_Day": s_val, "End_Day": e_val,
                        "Start": pd.to_datetime(start_date) + timedelta(days=s_val), "Finish": pd.to_datetime(start_date) + timedelta(days=e_val)
                    })
                display_scheduling_results(pd.DataFrame(results), int(makespan.varValue))
            else:
                st.error("❌ No feasible schedule found. Deadlines might be too tight.")
                
        else: # Evolutionary Algorithm - Demand Mode
            # Reuse the structural decode function built previously
            def decode_demand(priorities, t_list, d_dict, c_df):
                sorted_idx = np.argsort(priorities)
                res_avail, res_last, task_ends, sched = {}, {}, {}, []
                for t in t_list: 
                    for r in t['resources']: res_avail[r] = 0
                penalty = 0
                for idx in sorted_idx:
                    t = t_list[idx]
                    p_ready = max([task_ends.get(f"{t['job']}_{p}", 0) for p in t['preceding']] + [0])
                    best_s, best_r = float('inf'), None
                    for r in t['resources']:
                        c_time = int(c_df.loc[res_last[r], t['id']]) if r in res_last and res_last[r] in c_df.index else 0
                        ps = max(p_ready, res_avail[r] + c_time)
                        if ps < best_s: best_s, best_r = ps, r
                    end = best_s + t['duration']
                    res_avail[best_r], res_last[best_r], task_ends[t['id']] = end, t['id'], end
                    if end > int(d_dict.get(t['job'], 999)): penalty += (end - int(d_dict.get(t['job'], 999))) * 100
                    sched.append({
                        "Job": t['job'], "Process": t['process'], "Resource": best_r, "Duration": t['duration'],
                        "Start_Day": best_s, "End_Day": end,
                        "Start": pd.to_datetime(start_date) + timedelta(days=best_s), "Finish": pd.to_datetime(start_date) + timedelta(days=end)
                    })
                return sched, max(task_ends.values()) if task_ends else 0, penalty

            class DemandGA(ElementwiseProblem):
                def __init__(self, tl, dd, cf): super().__init__(n_var=len(tl), n_obj=1, xl=0, xu=1); self.tl, self.dd, self.cf = tl, dd, cf
                def _evaluate(self, x, out, *args, **kwargs): _, ms, pen = decode_demand(x, self.tl, self.dd, self.cf); out["F"] = ms + pen

            with st.spinner("Evolving demand schedule..."):
                res = minimize(DemandGA(base_tasks, deadline_dict, df_changeover), GA(pop_size=ga_pop_size), get_termination("n_gen", ga_generations), seed=1)
                best_sched, best_ms, final_pen = decode_demand(res.X, base_tasks, deadline_dict, df_changeover)
                msg = "⚠️ Deadlines unachievable within set bounds." if final_pen > 0 else ""
                display_scheduling_results(pd.DataFrame(best_sched), best_ms, msg)

    # =========================================================================
    # ANALYSIS MODE: MAXIMUM CAPACITY ASSESSMENT (NEW LOGIC)
    # =========================================================================
    else:
        # Build expanded task list mimicking potential replicates
        expanded_tasks = []
        for k in range(1, max_instances + 1):
            for bt in base_tasks:
                expanded_tasks.append({
                    'id': f"{bt['job']}_Copy{k}_{bt['process']}",
                    'base_id': bt['id'],
                    'job': bt['job'],
                    'copy_num': k,
                    'job_display': f"{bt['job']} (Unit {k})",
                    'process': bt['process'],
                    'resources': bt['resources'],
                    'duration': bt['duration'],
                    'preceding': bt['preceding']
                })

        if solver_choice == "Optimizer":
            prob = pulp.LpProblem("Capacity_Maximization", pulp.LpMaximize)
            
            start_vars = {t['id']: pulp.LpVariable(f"start_{t['id']}", lowBound=0, cat='Integer') for t in expanded_tasks}
            end_vars = {t['id']: pulp.LpVariable(f"end_{t['id']}", lowBound=0, cat='Integer') for t in expanded_tasks}
            assign_vars = {(t['id'], r): pulp.LpVariable(f"assign_{t['id']}_{r}", cat='Binary') for t in expanded_tasks for r in t['resources']}
            active_vars = {(j, k): pulp.LpVariable(f"active_{j}_{k}", cat='Binary') for j in unique_jobs_list for k in range(1, max_instances + 1)}
            
            # Objective: Maximize total loaded processing days on all machines
            prob += pulp.lpSum([t['duration'] * active_vars[t['job'], t['copy_num']] for t in expanded_tasks])
            
            for t in expanded_tasks:
                prob += end_vars[t['id']] == start_vars[t['id']] + t['duration'] * active_vars[t['job'], t['copy_num']]
                prob += pulp.lpSum([assign_vars[(t['id'], r)] for r in t['resources']]) == active_vars[t['job'], t['copy_num']]
                prob += end_vars[t['id']] <= time_span
                
                for pred in t['preceding']:
                    pred_id = f"{t['job']}_Copy{t['copy_num']}_{pred}"
                    if pred_id in start_vars: prob += start_vars[t['id']] >= end_vars[pred_id]
            
            # Symmetric Sequencing: Force copy k to be filled sequentially
            for j in unique_jobs_list:
                for k in range(2, max_instances + 1):
                    prob += active_vars[j, k] <= active_vars[j, k-1]

            M = max(1000, time_span * 3)
            for i in range(len(expanded_tasks)):
                for j in range(i + 1, len(expanded_tasks)):
                    t1, t2 = expanded_tasks[i], expanded_tasks[j]
                    common_res = set(t1['resources']).intersection(set(t2['resources']))
                    if common_res:
                        y = pulp.LpVariable(f"seq_{t1['id']}_{t2['id']}", cat='Binary')
                        for r in common_res:
                            c12 = int(df_changeover.loc[t1['base_id'], t2['base_id']]) if t1['base_id'] in df_changeover.index and t2['base_id'] in df_changeover.columns else 0
                            c21 = int(df_changeover.loc[t2['base_id'], t1['base_id']]) if t2['base_id'] in df_changeover.index and t1['base_id'] in df_changeover.columns else 0
                            
                            prob += start_vars[t2['id']] >= end_vars[t1['id']] + c12 - M * (3 - assign_vars[(t1['id'], r)] - assign_vars[(t2['id'], r)] - y) - M * (1 - active_vars[t1['job'], t1['copy_num']]) - M * (1 - active_vars[t2['job'], t2['copy_num']])
                            prob += start_vars[t1['id']] >= end_vars[t2['id']] + c21 - M * (2 - assign_vars[(t1['id'], r)] - assign_vars[(t2['id'], r)] + y) - M * (1 - active_vars[t1['job'], t1['copy_num']]) - M * (1 - active_vars[t2['job'], t2['copy_num']])

            solver = pulp.PULP_CBC_CMD(timeLimit=time_limit, msg=False)
            with st.spinner("Analyzing absolute volumetric capacity boundaries..."): status = prob.solve(solver)
            
            if pulp.LpStatus[status] in ["Optimal", "Not Solved"] and active_vars[(unique_jobs_list[0], 1)].varValue is not None:
                results = []
                for t in expanded_tasks:
                    if active_vars[(t['job'], t['copy_num'])].varValue < 0.5: continue
                    sel_res = [r for r in t['resources'] if assign_vars[(t['id'], r)].varValue > 0.5][0]
                    s_val, e_val = int(start_vars[t['id']].varValue), int(end_vars[t['id']].varValue)
                    results.append({
                        "Job": t['job_display'], "Base_Job": t['job'], "Process": t['process'], "Resource": sel_res, "Duration": t['duration'],
                        "Start_Day": s_val, "End_Day": e_val,
                        "Start": pd.to_datetime(start_date) + timedelta(days=s_val), "Finish": pd.to_datetime(start_date) + timedelta(days=e_val)
                    })
                if results: display_capacity_results(pd.DataFrame(results), time_span)
                else: st.warning("No jobs could fit into the planning time span.")
            else:
                st.error("❌ Capacity estimation failed. Loosen structural parameters or increase run time.")

        else: # Evolutionary Algorithm - Capacity Mode
            def decode_capacity(priorities, t_list, horizon, c_df):
                sorted_idx = np.argsort(priorities)
                res_avail, res_last, task_ends, sched = {}, {}, {}, []
                for t in t_list: 
                    for r in t['resources']: res_avail[r] = 0
                
                cancelled_copies = set()
                total_duration = 0
                
                for idx in sorted_idx:
                    t = t_list[idx]
                    copy_key = (t['job'], t['copy_num'])
                    if copy_key in cancelled_copies: continue
                    
                    # Ensure precedence constraint rules match replica flow
                    pred_ready, possible = 0, True
                    for pred in t['preceding']:
                        pred_id = f"{t['job']}_Copy{t['copy_num']}_{pred}"
                        if pred_id in task_ends: pred_ready = max(pred_ready, task_ends[pred_id])
                        else: possible = False; break
                    
                    if not possible: cancelled_copies.add(copy_key); continue
                    
                    best_s, best_r = float('inf'), None
                    for r in t['resources']:
                        c_time = int(c_df.loc[res_last[r], t['base_id']]) if r in res_last and res_last[r] in c_df.index else 0
                        ps = max(pred_ready, res_avail[r] + c_time)
                        if ps < best_s: best_s, best_r = ps, r
                        
                    if best_s + t['duration'] > horizon:
                        cancelled_copies.add(copy_key); continue
                        
                    end = best_s + t['duration']
                    res_avail[best_r], res_last[best_r], task_ends[t['id']] = end, t['base_id'], end
                    total_duration += t['duration']
                    
                    sched.append({
                        "Job": t['job_display'], "Base_Job": t['job'], "Process": t['process'], "Resource": best_r, "Duration": t['duration'],
                        "Start_Day": best_s, "End_Day": end,
                        "Start": pd.to_datetime(start_date) + timedelta(days=best_s), "Finish": pd.to_datetime(start_date) + timedelta(days=end)
                    })
                return sched, total_duration

            class CapacityGA(ElementwiseProblem):
                def __init__(self, tl, hz, cf): super().__init__(n_var=len(tl), n_obj=1, xl=0, xu=1); self.tl, self.hz, self.cf = tl, hz, cf
                def _evaluate(self, x, out, *args, **kwargs): _, tot_dur = decode_capacity(x, self.tl, self.hz, self.cf); out["F"] = -tot_dur # Maximize

            with st.spinner("Executing evolutionary capacity packing iteration..."):
                res = minimize(CapacityGA(expanded_tasks, time_span, df_changeover), GA(pop_size=ga_pop_size), get_termination("n_gen", ga_generations), seed=1)
                best_sched, _ = decode_capacity(res.X, expanded_tasks, time_span, df_changeover)
                if best_sched: display_capacity_results(pd.DataFrame(best_sched), time_span)
                else: st.warning("No units managed to pack within the requested horizon limit.")
