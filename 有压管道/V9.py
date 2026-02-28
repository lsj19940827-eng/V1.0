# 导入数值计算基础库（用于数组运算、数学函数等）
import numpy as np

# 从SciPy优化模块导入方程求解器（用于后续求解曼宁公式的非线性方程）
from scipy.optimize import fsolve

# 导入数据处理库（用于表格数据存储、清洗和分析）
import pandas as pd

# 导入时间模块（用于计算程序运行耗时）
import time

# 导入操作系统接口库（用于文件路径操作、目录创建等）
import os

# 导入基础绘图库（用于生成各种图表）
import matplotlib.pyplot as plt

# 导入统计可视化库（基于matplotlib，提供更美观的图表样式）
import seaborn as sns # 确保导入seaborn

# 从matplotlib线条模块导入基础线条类（用于手动创建图例中的自定义线条元素）
from matplotlib.lines import Line2D # 用于手动创建图例项

# *** MODIFICATION: Import for PDF merging ***
from pypdf import PdfWriter
import glob
# *** END MODIFICATION ***

# =====================================================
# ===== 输出配置区域 (可按需开启/关闭各输出项) =====
# =====================================================
# True = 输出该项, False = 跳过该项
OUTPUT_CSV = True           # CSV计算结果：包含所有工况的原始数据，便于后续分析和二次处理
OUTPUT_PDF_CHARTS = True    # 图表PDF(图1+图2)：流速对比图和优选设计点图的分组PDF文件
OUTPUT_MERGED_PDF = True    # 合并PDF：将所有图表合并成一个完整文档
OUTPUT_SUBPLOT_PNG = True   # 子图PNG：每个Q值生成独立的高清PNG图片(300DPI)
# =====================================================

# --- 辅助函数：将坡度字符串转换为数值 ---
def convert_slope_to_numeric(slope_str):
    try:
        if isinstance(slope_str, str) and "/" in slope_str:
            num, den = slope_str.split('/')
            return float(num) / float(den)
        return float(slope_str)
    except:
        return np.nan

# --- 新增：加大流量因子计算函数 (由VBA翻译而来) ---
def get_flow_increase_factor(design_q_m3s: float) -> float:
    """
    根据设计流量计算加大流量的乘法因子。
    VBA函数 GetFlowIncreasePercent 返回的是百分比 P，
    此函数返回因子 (1 + P/100)。
    design_q_m3s: 设计流量，单位 m³/s
    """
    percentage = 0.0
    if design_q_m3s <= 0:
        percentage = 0.0
    elif design_q_m3s < 1:
        percentage = 30.0
    elif design_q_m3s < 5:
        percentage = 25.0
    elif design_q_m3s < 20:
        percentage = 20.0
    elif design_q_m3s < 50:
        percentage = 15.0
    elif design_q_m3s < 100:
        percentage = 10.0
    elif design_q_m3s <= 300:
        percentage = 5.0
    else:  # design_q_m3s > 300
        percentage = 5.0
    return 1.0 + (percentage / 100.0)

# --- 设置图表样式和配色 ---
sns.set_theme(style="whitegrid")
plt.rcParams['font.sans-serif'] = ['SimHei']
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['axes.labelsize'] = 12
plt.rcParams['xtick.labelsize'] = 10
plt.rcParams['ytick.labelsize'] = 10
plt.rcParams['legend.fontsize'] = 8
plt.rcParams['figure.titlesize'] = 18
plt.rcParams['axes.titlesize'] = 14


# --- Helper function to calculate Q_max for a given D, n, i (无压) ---
def calculate_q_max_for_pipe_unpressurized(D_pipe, n_curr, i_curr):
    if D_pipe <= 0 or n_curr <=0 or i_curr <= 0: return 0.0
    y_D_ratio_opt_Q = 0.938; theta_opt_Q_rad = 5.278
    k_A_opt_Q = (1/8)*(theta_opt_Q_rad-np.sin(theta_opt_Q_rad))
    k_R_opt_Q = (1/4)*(1-np.sin(theta_opt_Q_rad)/theta_opt_Q_rad)
    A_opt_Q = k_A_opt_Q * D_pipe**2; R_opt_Q = k_R_opt_Q * D_pipe
    if R_opt_Q < 0 : R_opt_Q = 0.0
    return (1/n_curr)*A_opt_Q*(R_opt_Q**(2/3))*(i_curr**0.5)

# --- Main calculation function (v5 - specific pressurized formula - MODIFIED for increased flow head loss) ---
def solve_flow_elements_for_QniD_v5(Q_target_m3s, n_manning_unpr, i_slope_unpr, D_pipe_m, f_coeff, m_coeff, b_coeff):
    notes_unpr = []
    A_pipe_full = np.pi * D_pipe_m**2 / 4
    R_full_unpr = D_pipe_m / 4
    Q_full_capacity_unpr = (1/n_manning_unpr) * A_pipe_full * (R_full_unpr**(2/3)) * (i_slope_unpr**0.5)
    Q_max_theoretical_unpr = calculate_q_max_for_pipe_unpressurized(D_pipe_m, n_manning_unpr, i_slope_unpr)

    y_calc, A_water, R_calc_unpr, v_calc_unpr, y_D_ratio = np.nan, np.nan, np.nan, np.nan, np.nan
    clr_h, clr_a_pct, flg_ch, flg_ca = np.nan, np.nan, False, False

    if Q_target_m3s > Q_max_theoretical_unpr * 1.001:
        notes_unpr.append(f"Q > Q_max_unpr ({Q_max_theoretical_unpr:.4f})")
    else:
        def manning_solver(y_arr):
            y_trial = y_arr[0]
            if y_trial <= 1e-7: return -Q_target_m3s
            y_eff = min(max(y_trial,1e-7),D_pipe_m)
            if np.isclose(y_eff,D_pipe_m,atol=1e-6): A_f,P_f=A_pipe_full,np.pi*D_pipe_m
            else:
                acos_arg=1-(2*y_eff/D_pipe_m); acos_arg=min(1,max(-1,acos_arg))
                theta=2*np.arccos(acos_arg)
                A_f=(D_pipe_m**2/8)*(theta-np.sin(theta)); P_f=(D_pipe_m/2)*theta
            if A_f<1e-9 or P_f<1e-9: return -Q_target_m3s
            R_h=A_f/P_f; R_h=max(0,R_h)
            return (1/n_manning_unpr)*A_f*(R_h**(2/3))*(i_slope_unpr**0.5) - Q_target_m3s

        y_guess_val=D_pipe_m*0.5
        if Q_full_capacity_unpr > 1e-9 and Q_target_m3s/Q_full_capacity_unpr > 0.7: y_guess_val = D_pipe_m * 0.85
        try:
            y_sol,_,ier,msg=fsolve(manning_solver,[y_guess_val],full_output=True,xtol=1e-7)
            if ier!=1:
                if Q_target_m3s>=0.98*Q_full_capacity_unpr and Q_target_m3s<=Q_max_theoretical_unpr*1.001:
                    for guess_val_alt in [D_pipe_m*0.938, D_pipe_m*0.99]:
                        y_sol_alt,_,ier_alt,_=fsolve(manning_solver,[guess_val_alt],full_output=True,xtol=1e-7)
                        if ier_alt==1: y_sol,ier=y_sol_alt,ier_alt;break
            if ier==1:
                y_calc=y_sol[0]; y_calc=min(D_pipe_m,max(0,y_calc))
                if np.isclose(y_calc,D_pipe_m,atol=1e-5):A_water,R_calc_unpr=A_pipe_full,R_full_unpr
                elif y_calc<=1e-6:A_water,R_calc_unpr=0.0,0.0
                else:
                    acos_arg=1-(2*y_calc/D_pipe_m);acos_arg=min(1,max(-1,acos_arg))
                    theta=2*np.arccos(acos_arg)
                    A_water=(D_pipe_m**2/8)*(theta-np.sin(theta))
                    P_w=(D_pipe_m/2)*theta
                    R_calc_unpr=A_water/P_w if P_w>1e-9 else 0.0
                y_D_ratio=y_calc/D_pipe_m if D_pipe_m>0 else 0.0
                if A_water<1e-9:
                    v_calc_unpr=0.0 if Q_target_m3s<1e-7 else np.nan
                    if Q_target_m3s>=1e-7 and pd.isna(v_calc_unpr): notes_unpr.append("A_unpr_water过小")
                else: v_calc_unpr=Q_target_m3s/A_water
                clr_h=D_pipe_m-y_calc
                if pd.notna(A_water) and A_pipe_full>1e-9:
                    clr_a_abs=A_pipe_full-A_water
                    if clr_a_abs<-1e-6:notes_unpr.append("A_w_unpr>A_full");clr_a_abs=0.0
                    clr_a_pct=(clr_a_abs/A_pipe_full)*100.0
                else: clr_a_pct = np.nan
                if pd.notna(clr_h) and clr_h<0.4:flg_ch=True
                if pd.notna(clr_a_pct) and clr_a_pct<15.0:flg_ca=True
            else:notes_unpr.append(f"求解y_unpr失败:{msg[:20]}")
        except Exception as e:notes_unpr.append(f"求解y_unpr异常:{str(e)[:20]}")

    # --- 有压流计算 ---
    # MODIFICATION START: Pressurized head loss calculation updated
    L_press_m = 1000.0 # 水头损失按每公里计算，故长度取1000m

    # 初始化有压流计算结果变量
    hf_press_m_per_km = np.nan       # 沿程水头损失 (根据加大流量计算)
    V_press_m_s = np.nan             # 管内流速 (根据设计流量 Q_target_m3s 计算)
    hf_local_press_m_per_km = np.nan # 局部水头损失 (根据加大流量计算)
    hf_total_press_m_per_km = np.nan # 总水头损失 (根据加大流量计算)

    d_press_mm = D_pipe_m * 1000.0

    if d_press_mm > 1e-6 and A_pipe_full > 1e-9: # 确保管径和面积有效
        # 1. 计算实际流速 (基于设计流量 Q_target_m3s)
        try:
            V_press_m_s = Q_target_m3s / A_pipe_full
        except ZeroDivisionError:
            notes_unpr.append("有压流速计算时A_pipe_full为零")
            V_press_m_s = np.nan # 确保流速是nan

        # 2. 计算加大流量 (用于水头损失计算)
        flow_increase_factor = get_flow_increase_factor(Q_target_m3s) # Q_target_m3s 是设计流量
        Q_increased_m3s = Q_target_m3s * flow_increase_factor
        Q_increased_press_m3h = Q_increased_m3s * 3600.0 # 转换为 m³/h

        # 3. 计算水头损失 (基于加大流量 Q_increased_press_m3h)
        try:
            # 计算沿程水头损失 (使用加大流量)
            current_hf_friction_increased_q = f_coeff * (L_press_m * (Q_increased_press_m3h**m_coeff)) / (d_press_mm**b_coeff)

            if pd.notna(current_hf_friction_increased_q):
                hf_press_m_per_km = current_hf_friction_increased_q
                # 局部水头损失也应基于引起沿程损失的那个流量（即加大流量）
                hf_local_press_m_per_km = 0.15 * hf_press_m_per_km
                hf_total_press_m_per_km = hf_press_m_per_km + hf_local_press_m_per_km
            else:
                # 如果沿程水头损失计算失败，则局部和总损失也为nan
                hf_local_press_m_per_km = np.nan
                hf_total_press_m_per_km = np.nan
                # hf_press_m_per_km 此时已经是 nan

        except ZeroDivisionError:
            notes_unpr.append("有压水头损失计算(基于加大流量)时发生除零错误")
            # V_press_m_s 可能已计算，但水头损失为nan
            hf_press_m_per_km, hf_local_press_m_per_km, hf_total_press_m_per_km = np.nan, np.nan, np.nan
        except Exception as e_press:
            notes_unpr.append(f"有压水头损失计算(基于加大流量)时发生异常: {str(e_press)[:20]}")
            hf_press_m_per_km, hf_local_press_m_per_km, hf_total_press_m_per_km = np.nan, np.nan, np.nan
    else:
        notes_unpr.append("D_pipe_m过小，无法进行有压流计算（包括流速和基于加大流量的水头损失）")
        # 所有有压流相关结果 (V_press_m_s, hf_press_m_per_km等) 保持初始的 np.nan
    # MODIFICATION END

    return (y_calc, A_water, R_calc_unpr, v_calc_unpr, y_D_ratio, Q_full_capacity_unpr, Q_max_theoretical_unpr,
            clr_h, clr_a_pct, flg_ch, flg_ca, "; ".join(notes_unpr),
            hf_press_m_per_km, V_press_m_s, hf_local_press_m_per_km, hf_total_press_m_per_km)


# --- 定义参数范围 ---
Q_values = np.round(np.arange(0.1, 2.1, 0.1), 1) # Q值范围改为0.1-2.0，步长0.1
n_const_unpr = 0.014
i_frac_denominators = [500, 750, 1000, 1500, 2000, 2500, 3000, 3500, 4000]
i_values_unpr = [1/d for d in i_frac_denominators]
D_values_small = np.round(np.arange(0.1, 0.55, 0.05), 2)
D_values_medium = np.round(np.arange(0.6, 1.6, 0.1), 1)
D_values_large = np.round(np.arange(1.6, 3.2, 0.2), 1)
D_values = np.concatenate([D_values_small, D_values_medium, D_values_large])

# --- 定义多组管材参数 ---
pipe_materials = {
    'HDPE_玻璃钢夹砂管': {'f': 0.948e5, 'm': 1.77, 'b': 4.77, 'name': 'HDPE和玻璃钢夹砂管'},
    '球墨铸铁管': {'f': 1.899e5, 'm': 1.852, 'b': 4.87, 'name': '球墨铸铁管'},
    '预应力钢筒混凝土管': {'f': 1.312e6, 'm': 2.0, 'b': 5.33, 'name': '预应力钢筒混凝土管(n=0.013)'},
    '预应力钢筒混凝土管_n014': {'f': 1.516e6, 'm': 2.0, 'b': 5.33, 'name': '预应力钢筒混凝土管(n=0.014)'},
    '钢管': {'f': 6.25e5, 'm': 1.9, 'b': 5.1, 'name': '钢管'}
}

# --- 执行计算 ---
results_list = []
total_calc = len(Q_values) * len(i_values_unpr) * len(D_values) * len(pipe_materials)
print(f"总计需要执行 {total_calc} 次核心工况计算（包含{len(pipe_materials)}种管材）。")
start_time_calc = time.time(); calc_count = 0

for material_key, material_params in pipe_materials.items():
    f_coeff = material_params['f']
    m_coeff = material_params['m']
    b_coeff = material_params['b']
    material_name = material_params['name']
    
    print(f"\n正在计算管材: {material_name}")
    
    for Q_target_m3s in Q_values: # Q_target_m3s 已经四舍五入
        for idx, i_unpr_val in enumerate(i_values_unpr):
            i_str_unpr_label = f"1/{i_frac_denominators[idx]}"
            for D_m_val in D_values:
                calc_count += 1
                if calc_count % 5000 == 0 or calc_count == 1 or calc_count == total_calc:
                    elapsed = time.time()-start_time_calc; rem = (elapsed/calc_count)*total_calc-elapsed if calc_count>0 else 0
                    print(f"计算中: {calc_count}/{total_calc}... 已用:{elapsed:.0f}s, 预计剩余:{rem:.0f}s")

                (y_u,A_u,R_u,v_u,yD_u,Qf_u,Qm_u,ch_u,ca_u,fch_u,fca_u,note_u,
                 hf_p, V_p, hf_j_p, hf_tot_p) = solve_flow_elements_for_QniD_v5(Q_target_m3s,n_const_unpr,i_unpr_val,D_m_val,f_coeff,m_coeff,b_coeff)

                results_list.append({"管材类型":material_name,"Q_target (m³/s)":Q_target_m3s,"n_unpr":n_const_unpr,"i_unpr_str":i_str_unpr_label,"i_unpr_val":i_unpr_val,"D (m)":D_m_val,
                                     "y_unpr (m)":y_u,"v_unpr (m/s)":v_u,"y/D_unpr":yD_u,
                                     "hf_press (m/km)":hf_p,
                                     "V_press (m/s)":V_p,
                                     "hf_local_press (m/km)": hf_j_p,
                                     "hf_total_press (m/km)": hf_tot_p,
                                     "净空高度 (m)":ch_u,"净空面积 (%)":ca_u,"净空高<0.4m":fch_u,"净空面积(%)<15":fca_u,
                                     "Q_full_unpr (m³/s)":Qf_u,"Q_max_unpr (m³/s)":Qm_u,"备注":note_u,
                                     "f系数":f_coeff,"m系数":m_coeff,"b系数":b_coeff})

df_results = pd.DataFrame(results_list)
end_time_calc = time.time()
print(f"所有 {total_calc} 次计算完成，总耗时: {end_time_calc - start_time_calc:.2f} 秒。")

# --- 保存到CSV ---
output_dir = r"D:\6、亭子口二期\2--管材比较\无压有压圆形管道计算\绘图代码\V9" # 修改输出目录名以区分
if not os.path.exists(output_dir):
    try: os.makedirs(output_dir); print(f"创建目录: {output_dir}")
    except OSError as e: print(f"无法创建目录 {output_dir}: {e}. 请手动创建或检查权限."); output_dir = "."
csv_file_name = "hydraulic_calc_多管材_Q_0.1_to_2.0_五种管材参数.csv"
csv_file = os.path.join(output_dir, csv_file_name)
if OUTPUT_CSV:
    try: df_results.to_csv(csv_file, index=False, encoding='utf-8-sig'); print(f"CSV 计算结果已保存到: {csv_file}")
    except Exception as e: print(f"保存CSV文件失败: {e}")
else:
    print("已跳过 CSV 输出（配置为关闭）")

# --- 绘图部分 ---
print("\n开始准备绘图数据...")

try:
    df_plot_data = pd.read_csv(csv_file)
    # ****** 关键修改：确保从CSV读取的Q值精度统一，防止子图重复 ******
    df_plot_data['Q_target (m³/s)'] = df_plot_data['Q_target (m³/s)'].round(1)  # 改为1位小数
    # ****************************************************************

    df_plot_data['i_numeric'] = df_plot_data['i_unpr_str'].apply(convert_slope_to_numeric)

    # 获取所有管材类型
    all_materials = df_plot_data['管材类型'].unique()
    print(f"数据中包含的管材类型: {all_materials}")

    # 为每种管材分别绘图
    for material_idx, selected_material in enumerate(all_materials):
        print(f"\n=== 正在为管材 {material_idx+1}/{len(all_materials)} 进行绘图: {selected_material} ===")

        df_plot_data_selected = df_plot_data[df_plot_data['管材类型'] == selected_material].copy()

        df_plot_unpr_valid_global = df_plot_data_selected.dropna(subset=['v_unpr (m/s)']).copy()
        df_plot_press_valid_global = df_plot_data_selected.dropna(subset=['V_press (m/s)', 'hf_press (m/km)', 'hf_total_press (m/km)']).copy()

        if df_plot_unpr_valid_global.empty and df_plot_press_valid_global.empty:
            print(f"管材 {selected_material} 没有有效的流速数据可供绘图。")
            continue
        else:
            unique_numeric_slopes = sorted(df_plot_data_selected['i_numeric'].dropna().unique())
            slope_val_to_str_map = pd.Series(df_plot_data_selected['i_unpr_str'].values, index=df_plot_data_selected['i_numeric'].values).drop_duplicates().sort_index()
            ordered_slope_labels = [slope_val_to_str_map[val] for val in unique_numeric_slopes if val in slope_val_to_str_map]
            num_slopes = len(ordered_slope_labels)
            nature_palette = sns.color_palette("tab10", n_colors=max(num_slopes, 2))
            nature_linestyles_mpl = ['-', '--', '-.', ':', (0,(3,1,1,1)), (0,(5,1)), (0,(1,1)),(0,(3,5,1,5)),(0,(5,10))]
            seaborn_dash_patterns = ["", (4,1.5), (4,1.5,1,1.5), (1,1.5), (3,1,1,1), (5,1), (1,1), (3,5,1,5), (5,10)]
            if len(seaborn_dash_patterns) < num_slopes:
                seaborn_dash_patterns.extend(seaborn_dash_patterns[:num_slopes-len(seaborn_dash_patterns)])
            elif len(seaborn_dash_patterns) > num_slopes:
                seaborn_dash_patterns = seaborn_dash_patterns[:num_slopes]
            nature_markers = ['o','s','D','^','v','P','X','*','h']
            final_mpl_linestyles = [nature_linestyles_mpl[i % len(nature_linestyles_mpl)] for i in range(num_slopes)]
            final_seaborn_dashes = [seaborn_dash_patterns[i % len(seaborn_dash_patterns)] for i in range(num_slopes)]
            final_markers = [nature_markers[i % len(nature_markers)] for i in range(num_slopes)]
            if not df_plot_unpr_valid_global.empty:
                 df_plot_unpr_valid_global.loc[:, 'i_unpr_str_cat'] = pd.Categorical(df_plot_unpr_valid_global['i_unpr_str'], categories=ordered_slope_labels, ordered=True)

            all_Q_values_present_in_data = sorted(df_plot_data_selected['Q_target (m³/s)'].unique()) # 这时应该是正确的唯一Q值
            df_facet_unpr_for_vel_plot = df_plot_unpr_valid_global.copy()
            df_facet_press_for_vel_plot = df_plot_press_valid_global.copy()
            adj_left_global=0.043; adj_right_global=0.90; adj_bottom_global=0.07; adj_top_global=0.92; adj_hspace_global=0.5; adj_wspace_global=0.35

            q_unit_tex = r"m$^3$/s"

        # --- 图1: 流速对比 ---
        if not df_facet_unpr_for_vel_plot.empty or not df_facet_press_for_vel_plot.empty:
            print("绘制图1: 流速对比图 ...")
            # 使用数据中实际存在的、经过round(1)的Q值进行分块
            all_Q_values_for_fig1 = sorted(df_plot_data_selected['Q_target (m³/s)'].unique())
            chunk_size_fig1 = 10
            q_chunks_fig1 = [all_Q_values_for_fig1[i:i + chunk_size_fig1] for i in range(0, len(all_Q_values_for_fig1), chunk_size_fig1)]

            if not q_chunks_fig1:
                 print("图1: 没有Q值分块可供处理。")

            for fig1_idx, current_q_chunk_fig1 in enumerate(q_chunks_fig1):
                # current_q_chunk_fig1 现在是numpy array，可以直接使用
                if not len(current_q_chunk_fig1): continue # 检查是否为空列表/数组

                q_start_label_fig1 = f"{current_q_chunk_fig1[0]:.1f}"
                q_end_label_fig1 = f"{current_q_chunk_fig1[-1]:.1f}"
                print(f"\n绘制图1 (系列 {fig1_idx + 1}/{len(q_chunks_fig1)}): Q范围 {q_start_label_fig1} - {q_end_label_fig1} m³/s")

                df_facet_unpr_current_chunk = df_facet_unpr_for_vel_plot[df_facet_unpr_for_vel_plot['Q_target (m³/s)'].isin(current_q_chunk_fig1)]
                df_facet_press_current_chunk = df_facet_press_for_vel_plot[df_facet_press_for_vel_plot['Q_target (m³/s)'].isin(current_q_chunk_fig1)]

                if df_facet_unpr_current_chunk.empty and df_facet_press_current_chunk.empty:
                    print(f"图1 (系列 {fig1_idx + 1}): 在Q范围 {q_start_label_fig1}-{q_end_label_fig1} 未找到满足条件的数据点。")
                    continue

                num_q_facet_fig1 = len(current_q_chunk_fig1)
                col_wrap_q_facet_fig1 = 5 if num_q_facet_fig1 >=10 else (4 if num_q_facet_fig1 >= 8 else (3 if num_q_facet_fig1 >= 5 else (max(1,num_q_facet_fig1))))
                n_rows_facet_vel_fig1 = (num_q_facet_fig1 + col_wrap_q_facet_fig1 - 1) // col_wrap_q_facet_fig1
                current_figsize = plt.rcParams['figure.figsize']
                if col_wrap_q_facet_fig1 == 5 and n_rows_facet_vel_fig1 == 2: plt.rcParams['figure.figsize'] = (38,18)
                elif col_wrap_q_facet_fig1 == 4 and n_rows_facet_vel_fig1 == 3: plt.rcParams['figure.figsize'] = (22,13)
                else: plt.rcParams['figure.figsize'] = (max(19,col_wrap_q_facet_fig1*6), max(9,n_rows_facet_vel_fig1*6+3))

                adj_left,adj_right,adj_bottom,adj_top,adj_hspace,adj_wspace = adj_left_global,adj_right_global,adj_bottom_global,adj_top_global,adj_hspace_global,adj_wspace_global
                fig_w_total,fig_h_total=plt.rcParams['figure.figsize']; plot_area_width=fig_w_total*(adj_right-adj_left); plot_area_height=fig_h_total*(adj_top-adj_bottom)
                denominator_w = col_wrap_q_facet_fig1+(col_wrap_q_facet_fig1-1)*adj_wspace if col_wrap_q_facet_fig1>1 else col_wrap_q_facet_fig1
                facet_width_param = plot_area_width/denominator_w if denominator_w > 0 else plot_area_width*0.9
                denominator_h = n_rows_facet_vel_fig1+(n_rows_facet_vel_fig1-1)*adj_hspace if n_rows_facet_vel_fig1>1 else n_rows_facet_vel_fig1
                facet_height_param = plot_area_height/denominator_h if denominator_h > 0 else plot_area_height*0.9
                facetgrid_height_arg=facet_height_param; facetgrid_aspect_arg=facet_width_param/facet_height_param if facet_height_param > 1e-6 else 1.1

                g_vel = sns.FacetGrid(df_facet_unpr_current_chunk,
                                      col="Q_target (m³/s)", col_wrap=col_wrap_q_facet_fig1, height=facetgrid_height_arg, aspect=facetgrid_aspect_arg,
                                      sharex=True, sharey=False, col_order=current_q_chunk_fig1, margin_titles=True)

                # 导入MultipleLocator
                from matplotlib.ticker import MultipleLocator

                for ax_idx_g1, ax_g1 in enumerate(g_vel.axes.flat):
                    ax_g1.set_xlabel('管径 D (m)')
                    ax_g1.xaxis.set_major_locator(MultipleLocator(0.5))
                    ax_g1.xaxis.set_minor_locator(MultipleLocator(0.1))
                    ax_g1.tick_params(axis='x', which='both', bottom=True, labelbottom=True, direction='out')
                    ax_g1.grid(axis='x', which='major', linestyle='-', linewidth=1.2, color='#A9A9A9', zorder=0)
                    ax_g1.grid(axis='x', which='minor', linestyle='--', linewidth=0.7, color='#D3D3D3', zorder=0)

                g_vel.map_dataframe(sns.lineplot,x='D (m)',y='v_unpr (m/s)',hue='i_unpr_str_cat',hue_order=ordered_slope_labels,palette=nature_palette,
                                    style='i_unpr_str_cat',style_order=ordered_slope_labels,dashes=final_seaborn_dashes[:num_slopes],markers=final_markers,markersize=4,linewidth=1.3,legend=False)

                HF_PRESS_YLIM_MAX_INTEREST=3.0; HF_PRESS_YLIM_BUFFER_ABOVE_MAX=0.2
                for q_idx_g1, q_val_target_plot_g1 in enumerate(current_q_chunk_fig1):
                    if q_idx_g1 >= len(g_vel.axes.flat): continue
                    ax1_g1 = g_vel.axes.flat[q_idx_g1]; ax1_g1.tick_params(axis='y',which='both',left=True,direction='out')
                    y_top_limit_vel_ax1_g1=1.0
                    v_unpr_in_facet_g1 = df_facet_unpr_current_chunk[df_facet_unpr_current_chunk['Q_target (m³/s)']==q_val_target_plot_g1]['v_unpr (m/s)']
                    if not v_unpr_in_facet_g1.empty and v_unpr_in_facet_g1.notna().any():
                        v_unpr_max_val_g1 = v_unpr_in_facet_g1.max();
                        if pd.notna(v_unpr_max_val_g1): y_top_limit_vel_ax1_g1 = v_unpr_max_val_g1 + 0.2

                    data_slice_press_current_q_g1 = df_facet_press_current_chunk[(df_facet_press_current_chunk['Q_target (m³/s)']==q_val_target_plot_g1)].drop_duplicates(subset=['D (m)'])
                    if not data_slice_press_current_q_g1.empty:
                        data_slice_press_current_q_g1 = data_slice_press_current_q_g1.sort_values(by='D (m)')
                        if pd.isna(v_unpr_in_facet_g1.max()) or not v_unpr_in_facet_g1.notna().any():
                            temp_v_press_max_for_ylim_ax1_g1 = data_slice_press_current_q_g1[data_slice_press_current_q_g1['D (m)']>=0.5]['V_press (m/s)'].max()
                            if pd.notna(temp_v_press_max_for_ylim_ax1_g1) and temp_v_press_max_for_ylim_ax1_g1 > 0: y_top_limit_vel_ax1_g1 = min(temp_v_press_max_for_ylim_ax1_g1*1.2, 3.5)
                            else: y_top_limit_vel_ax1_g1 = 1.5
                        drawable_V_press_g1 = data_slice_press_current_q_g1[data_slice_press_current_q_g1['V_press (m/s)'] <= y_top_limit_vel_ax1_g1*1.05]
                        if not drawable_V_press_g1.empty:
                            ax1_g1.plot(drawable_V_press_g1['D (m)'],drawable_V_press_g1['V_press (m/s)'],linestyle=':',color='dimgray',linewidth=1.8,marker='.',markersize=5,label='V_press (有压, 左轴)' if q_idx_g1==0 and fig1_idx == 0 else "_nolegend_")
                    ax1_g1.set_ylim(bottom=0,top=max(0.6,y_top_limit_vel_ax1_g1)); ax1_g1.tick_params(axis='y',labelsize=plt.rcParams['ytick.labelsize']); ax1_g1.spines["left"].set_edgecolor('black')
                    ax2_g1 = ax1_g1.twinx()
                    if not data_slice_press_current_q_g1.empty:
                        hf_color_g1='firebrick'
                        line_hf_g1,=ax2_g1.plot(data_slice_press_current_q_g1['D (m)'],data_slice_press_current_q_g1['hf_total_press (m/km)'],linestyle='--',color=hf_color_g1,linewidth=1.8,marker='x',markersize=4,alpha=0.8,label='总水头损失 (有压, 右轴)' if q_idx_g1==0 and fig1_idx == 0 else "_nolegend_")
                        current_max_hf_g1 = data_slice_press_current_q_g1['hf_total_press (m/km)'].max(); y_top_limit_hf_ax2_g1 = HF_PRESS_YLIM_MAX_INTEREST + HF_PRESS_YLIM_BUFFER_ABOVE_MAX
                        if pd.notna(current_max_hf_g1) and current_max_hf_g1 > 0:
                            if current_max_hf_g1 <= HF_PRESS_YLIM_MAX_INTEREST: y_top_limit_hf_ax2_g1 = min(current_max_hf_g1*1.2, HF_PRESS_YLIM_MAX_INTEREST + HF_PRESS_YLIM_BUFFER_ABOVE_MAX)
                        ax2_g1.set_ylim(bottom=0,top=max(0.5,y_top_limit_hf_ax2_g1))
                        ax2_g1.set_ylabel('有压管总水头损失 (m/km)',color=line_hf_g1.get_color(),fontsize=plt.rcParams['axes.labelsize']*0.9)
                        ax2_g1.tick_params(axis='y',labelcolor=line_hf_g1.get_color(),labelsize=plt.rcParams['ytick.labelsize']*0.9,colors=line_hf_g1.get_color(),which='both',right=True,direction='out')
                        ax2_g1.spines["right"].set_edgecolor(line_hf_g1.get_color()); ax2_g1.spines["right"].set_visible(True)
                    else: ax2_g1.set_yticks([]); ax2_g1.set_yticklabels([]); ax2_g1.spines["right"].set_visible(False)

                fig1_title_suffix = f"(Q范围: {q_start_label_fig1} - {q_end_label_fig1} m³/s, 管材: {selected_material})"
                g_vel.figure.suptitle(f'图1: 无压与有压管道流速(左轴)和总水头损失(右轴,关注总hf=0-3m/km)对比 {fig1_title_suffix}',y=(adj_top+(1-adj_top)/2+0.008),fontsize=plt.rcParams['figure.titlesize'])
                g_vel.set_axis_labels('管径 D (m)','流速 (m/s)')
                g_vel.set_titles("目标流量 Q = {col_name:.1f} " + q_unit_tex)  # 改为1位小数

                if fig1_idx == 0:
                    handles_vel,labels_vel = [],[]
                    for i_g1,slope_label_plot_g1 in enumerate(ordered_slope_labels):
                        handles_vel.append(Line2D([0],[0],color=nature_palette[i_g1%num_slopes],linestyle=final_mpl_linestyles[i_g1%num_slopes],marker=final_markers[i_g1%num_slopes],markersize=5,linewidth=1.3))
                        labels_vel.append(f"{slope_label_plot_g1} (无压流速, 左轴)")
                    handles_vel.append(Line2D([0],[0],color='dimgray',linewidth=1.8,linestyle=':',marker='.',markersize=5)); labels_vel.append('V_press (有压流速, 左轴)')
                    if not df_facet_press_for_vel_plot.empty:
                        hf_color_for_legend_g1='firebrick'
                        handles_vel.append(Line2D([0],[0],color=hf_color_for_legend_g1,linestyle='--',linewidth=1.8,marker='x',markersize=4,alpha=0.8)); labels_vel.append('总水头损失 (有压, 右轴)')
                    legend_x_anchor_g1=adj_right+0.005
                    g_vel.figure.legend(handles_vel,labels_vel,title='图例 (图1)',loc='center left',bbox_to_anchor=(legend_x_anchor_g1,0.5),frameon=True,title_fontsize='medium',fontsize=plt.rcParams['legend.fontsize']*1.1)

                plt.subplots_adjust(left=adj_left,right=adj_right,top=adj_top,bottom=adj_bottom,hspace=adj_hspace,wspace=adj_wspace)
                try: g_vel.figure.tight_layout(rect=(adj_left,adj_bottom,adj_right,adj_top))
                except UserWarning as uw_g1: print(f"UserWarning during tight_layout for Fig 1 (Q: {q_start_label_fig1}-{q_end_label_fig1}): {uw_g1}")
                except Exception as e_g1: print(f"Error during tight_layout for Fig 1 (Q: {q_start_label_fig1}-{q_end_label_fig1}): {e_g1}")

                filename_q_suffix_fig1 = f"Q_{q_start_label_fig1.replace('.','_')}_to_{q_end_label_fig1.replace('.','_')}"
                plot_file_fig1_pdf = os.path.join(output_dir,f"图1_流速与总水头损失_{filename_q_suffix_fig1}_{selected_material.replace('(','_').replace(')','_').replace('=','_')}.pdf")

                # 保存PDF
                if OUTPUT_PDF_CHARTS:
                    plt.savefig(plot_file_fig1_pdf)
                    print(f"图1 (Q: {q_start_label_fig1}-{q_end_label_fig1}) PDF 已保存: {plot_file_fig1_pdf}")

                # 创建子图PNG输出目录
                if OUTPUT_SUBPLOT_PNG:
                    png_subplots_dir = os.path.join(output_dir, "子图PNG", selected_material.replace('(','_').replace(')','_').replace('=','_'))
                    if not os.path.exists(png_subplots_dir):
                        os.makedirs(png_subplots_dir)

                # 为每个Q值创建独立完整的子图PNG
                if OUTPUT_SUBPLOT_PNG:
                    for subplot_idx, q_val in enumerate(current_q_chunk_fig1):
                        # 筛选当前Q值的数据
                        df_unpr_q = df_facet_unpr_current_chunk[df_facet_unpr_current_chunk['Q_target (m³/s)'] == q_val]
                        df_press_q = df_facet_press_current_chunk[df_facet_press_current_chunk['Q_target (m³/s)'] == q_val]

                        # 检查是否有数据可绘制
                        if df_unpr_q.empty and df_press_q.empty:
                            print(f"  跳过图1子图 Q={q_val:.1f}，无数据")
                            continue

                        # 创建独立figure
                        fig_sub, ax1_sub = plt.subplots(figsize=(10, 7))
                        ax2_sub = ax1_sub.twinx()

                        # 设置X轴
                        ax1_sub.set_xlabel('管径 D (m)', fontsize=12)
                        ax1_sub.xaxis.set_major_locator(MultipleLocator(0.5))
                        ax1_sub.xaxis.set_minor_locator(MultipleLocator(0.1))
                        ax1_sub.tick_params(axis='x', which='both', bottom=True, labelbottom=True, direction='out')
                        ax1_sub.grid(axis='x', which='major', linestyle='-', linewidth=1.2, color='#A9A9A9', zorder=0)
                        ax1_sub.grid(axis='x', which='minor', linestyle='--', linewidth=0.7, color='#D3D3D3', zorder=0)
                        ax1_sub.grid(axis='y', which='major', linestyle='-', linewidth=0.8, color='#D3D3D3', zorder=0)

                        # 绘制无压流速线（按坡度分组）
                        y_max_vel = 0.6
                        for i_slope, slope_label in enumerate(ordered_slope_labels):
                            df_slope = df_unpr_q[df_unpr_q['i_unpr_str'] == slope_label].sort_values('D (m)')
                            if not df_slope.empty:
                                ax1_sub.plot(df_slope['D (m)'], df_slope['v_unpr (m/s)'],
                                            color=nature_palette[i_slope % num_slopes],
                                            linestyle=final_mpl_linestyles[i_slope % num_slopes],
                                            marker=final_markers[i_slope % num_slopes],
                                            markersize=4, linewidth=1.3,
                                            label=f"i={slope_label} (无压)")
                                if df_slope['v_unpr (m/s)'].max() > y_max_vel:
                                    y_max_vel = df_slope['v_unpr (m/s)'].max()

                        # 绘制有压流速线
                        df_press_q_unique = df_press_q.drop_duplicates(subset=['D (m)']).sort_values('D (m)')
                        if not df_press_q_unique.empty:
                            drawable_V_press = df_press_q_unique[df_press_q_unique['V_press (m/s)'] <= (y_max_vel + 0.2) * 1.05]
                            if not drawable_V_press.empty:
                                ax1_sub.plot(drawable_V_press['D (m)'], drawable_V_press['V_press (m/s)'],
                                            linestyle=':', color='dimgray', linewidth=1.8,
                                            marker='.', markersize=5, label='V_press (有压)')
                                if drawable_V_press['V_press (m/s)'].max() > y_max_vel:
                                    y_max_vel = drawable_V_press['V_press (m/s)'].max()

                        # 设置左Y轴
                        ax1_sub.set_ylabel('流速 (m/s)', fontsize=12, color='black')
                        ax1_sub.set_ylim(bottom=0, top=max(0.6, y_max_vel + 0.2))
                        ax1_sub.tick_params(axis='y', labelsize=10, direction='out')

                        # 绘制总水头损失（右Y轴）
                        hf_color = 'firebrick'
                        y_max_hf = 0.5
                        if not df_press_q_unique.empty:
                            ax2_sub.plot(df_press_q_unique['D (m)'], df_press_q_unique['hf_total_press (m/km)'],
                                        linestyle='--', color=hf_color, linewidth=1.8,
                                        marker='x', markersize=4, alpha=0.8, label='总水头损失 (有压)')
                            hf_max = df_press_q_unique['hf_total_press (m/km)'].max()
                            if pd.notna(hf_max) and hf_max > 0:
                                y_max_hf = min(hf_max * 1.2, 3.2)

                        ax2_sub.set_ylabel('有压管总水头损失 (m/km)', fontsize=11, color=hf_color)
                        ax2_sub.set_ylim(bottom=0, top=max(0.5, y_max_hf))
                        ax2_sub.tick_params(axis='y', labelcolor=hf_color, labelsize=10, colors=hf_color, direction='out')
                        ax2_sub.spines["right"].set_edgecolor(hf_color)

                        # 设置X轴范围
                        if D_values.size > 0:
                            ax1_sub.set_xlim(min(D_values) - 0.05, max(D_values) + 0.05)

                        # 设置标题
                        fig_sub.suptitle(f'图1: 流速与总水头损失对比\n目标流量 Q = {q_val:.1f} m³/s, 管材: {selected_material}',
                                       fontsize=14, y=0.98)

                        # 合并图例
                        handles1, labels1 = ax1_sub.get_legend_handles_labels()
                        handles2, labels2 = ax2_sub.get_legend_handles_labels()
                        fig_sub.legend(handles1 + handles2, labels1 + labels2,
                                      loc='upper right', bbox_to_anchor=(0.98, 0.88),
                                      fontsize=8, frameon=True, ncol=2)

                        # 调整布局并保存
                        fig_sub.tight_layout(rect=[0, 0, 1, 0.93])
                        subplot_filename = f"图1_子图_{subplot_idx+1:02d}_Q{q_val:.1f}_{selected_material.replace('(','_').replace(')','_').replace('=','_')}.png"
                        subplot_filepath = os.path.join(png_subplots_dir, subplot_filename)
                        fig_sub.savefig(subplot_filepath, dpi=300, bbox_inches='tight', pad_inches=0.1)
                        plt.close(fig_sub)
                        print(f"  子图PNG已保存: {subplot_filename}")

                plt.close(g_vel.figure)
                plt.rcParams['figure.figsize'] = current_figsize
        else: print("没有足够数据绘制图1系列。")

        # --- 图2: 特定工况下的有压管道设计点 (经济流速与妥协流速)---
        if not df_plot_press_valid_global.empty:
                print(f"\n准备绘制图2系列: 特定工况下有压管道设计点 (经济流速与妥协流速) - 管材: {selected_material}...")
                df_fig2_base_data = df_plot_press_valid_global[['Q_target (m³/s)','D (m)','V_press (m/s)','hf_total_press (m/km)']].drop_duplicates().copy()
                df_fig2_base_data['category'] = pd.Series(dtype='object')
                cond_economic = ((df_fig2_base_data['V_press (m/s)']>=0.9)&(df_fig2_base_data['V_press (m/s)']<=1.5)&(df_fig2_base_data['hf_total_press (m/km)']<=5.0))
                cond_compromise = ((df_fig2_base_data['V_press (m/s)']>=0.6)&(df_fig2_base_data['V_press (m/s)']<0.9)&(df_fig2_base_data['hf_total_press (m/km)']<=5.0))
                df_fig2_base_data.loc[cond_economic,'category'] = '经济流速 (0.9-1.5 m/s, 总hf ≤ 5 m/km)'
                df_fig2_base_data.loc[cond_compromise,'category'] = '妥协流速 (0.6-0.89 m/s, 总hf ≤ 5 m/km)'
                df_fig2_categorized_global = df_fig2_base_data.dropna(subset=['category']).copy()

                if df_fig2_categorized_global.empty:
                    print(f"图2系列: 管材 {selected_material} 未找到满足指定经济/妥协流速及总水头损失条件的数据点。")
                else:
                    # 使用数据中实际存在的、经过round(1)的Q值进行分块
                    all_Q_values_for_fig2_series = sorted(df_fig2_categorized_global['Q_target (m³/s)'].unique())
                    chunk_size_fig2 = 10
                    q_chunks_fig2 = [all_Q_values_for_fig2_series[i:i+chunk_size_fig2] for i in range(0,len(all_Q_values_for_fig2_series),chunk_size_fig2)]

                    if not q_chunks_fig2:
                        print("图2: 没有Q值分块可供处理。")

                    for fig2_idx, current_q_chunk_fig2 in enumerate(q_chunks_fig2):
                        if not len(current_q_chunk_fig2): continue # 检查是否为空列表/数组
                        q_start_label_str_fig2 =f"{current_q_chunk_fig2[0]:.1f}"; q_end_label_str_fig2 =f"{current_q_chunk_fig2[-1]:.1f}"
                        print(f"\n绘制图2 (系列 {fig2_idx+1}/{len(q_chunks_fig2)}): Q范围 {q_start_label_str_fig2} - {q_end_label_str_fig2} m³/s")

                        df_fig2_filtered_chunk = df_fig2_categorized_global[df_fig2_categorized_global['Q_target (m³/s)'].isin(current_q_chunk_fig2)].copy()
                        if df_fig2_filtered_chunk.empty:
                            print(f"图2 (系列 {fig2_idx+1}): 在Q范围 {q_start_label_str_fig2}-{q_end_label_str_fig2} 未找到满足条件的数据点。"); continue

                        df_fig2_filtered_chunk.loc[:,'category'] = pd.Categorical(df_fig2_filtered_chunk['category'],
                                                                                  categories=['经济流速 (0.9-1.5 m/s, 总hf ≤ 5 m/km)',
                                                                                              '妥协流速 (0.6-0.89 m/s, 总hf ≤ 5 m/km)'],ordered=True)
                        df_fig2_filtered_chunk.sort_values(by=['Q_target (m³/s)','category','D (m)'],inplace=True)

                        num_q_facet_fig2 = len(current_q_chunk_fig2); col_wrap_q_facet_fig2 = 5 if num_q_facet_fig2 > 5 else (max(1,num_q_facet_fig2))
                        n_rows_q_facet_fig2 = (num_q_facet_fig2 + col_wrap_q_facet_fig2 - 1) // col_wrap_q_facet_fig2
                        current_figsize_fig2 = plt.rcParams['figure.figsize']
                        if col_wrap_q_facet_fig2==5 and n_rows_q_facet_fig2==2 : plt.rcParams['figure.figsize']=(38,18)
                        elif n_rows_q_facet_fig2==1 and col_wrap_q_facet_fig2<=5 : plt.rcParams['figure.figsize']=(col_wrap_q_facet_fig2*7.5,9)
                        else: plt.rcParams['figure.figsize']=(max(19,col_wrap_q_facet_fig2*6),max(9,n_rows_q_facet_fig2*6+3))

                        adj_left_f2,adj_right_f2,adj_bottom_f2,adj_top_f2,adj_hspace_f2,adj_wspace_f2 = adj_left_global,adj_right_global,adj_bottom_global,adj_top_global,adj_hspace_global,adj_wspace_global
                        fig_w_total_fig2,fig_h_total_fig2=plt.rcParams['figure.figsize']; plot_area_width_fig2=fig_w_total_fig2*(adj_right_f2-adj_left_f2); plot_area_height_fig2=fig_h_total_fig2*(adj_top_f2-adj_bottom_f2)
                        denominator_w_fig2=col_wrap_q_facet_fig2+(col_wrap_q_facet_fig2-1)*adj_wspace_f2 if col_wrap_q_facet_fig2 > 1 else col_wrap_q_facet_fig2
                        facet_width_param_fig2=plot_area_width_fig2/denominator_w_fig2 if denominator_w_fig2 > 0 else plot_area_width_fig2*0.9
                        denominator_h_fig2=n_rows_q_facet_fig2+(n_rows_q_facet_fig2-1)*adj_hspace_f2 if n_rows_q_facet_fig2 > 1 else n_rows_q_facet_fig2
                        facet_height_param_fig2=plot_area_height_fig2/denominator_h_fig2 if denominator_h_fig2 > 0 else plot_area_height_fig2*0.9
                        facetgrid_height_arg_fig2=facet_height_param_fig2; facetgrid_aspect_arg_fig2=facet_width_param_fig2/facet_height_param_fig2 if facet_height_param_fig2 > 1e-6 else 1.1

                        g_fig2 = sns.FacetGrid(df_fig2_filtered_chunk,col="Q_target (m³/s)",col_wrap=col_wrap_q_facet_fig2,height=facetgrid_height_arg_fig2,aspect=facetgrid_aspect_arg_fig2,sharex=True,sharey=False,col_order=current_q_chunk_fig2,margin_titles=False)
                        color_v_f2=nature_palette[0]; color_hf_f2='darkorange'; marker_style_f2='o'; marker_size_f2=70; text_fontsize_f2=6.5; text_offset_x_f2=0.015

                        for q_idx_facet_fig2, q_val_target_plot_fig2 in enumerate(current_q_chunk_fig2):
                            if q_idx_facet_fig2 >= len(g_fig2.axes.flat): continue
                            ax1_fig2=g_fig2.axes.flat[q_idx_facet_fig2]; ax2_fig2=ax1_fig2.twinx(); ax2_fig2.cla()
                            ax1_fig2.spines["left"].set_visible(True); ax1_fig2.spines["bottom"].set_visible(True); ax1_fig2.spines["top"].set_visible(False); ax1_fig2.spines["right"].set_visible(False)
                            ax2_fig2.spines["right"].set_visible(True); ax2_fig2.spines["bottom"].set_visible(True); ax2_fig2.spines["top"].set_visible(False); ax2_fig2.spines["left"].set_visible(False)

                            ax1_fig2.set_xlabel('管径 D (m)')
                            ax1_fig2.xaxis.set_major_locator(MultipleLocator(0.5))
                            ax1_fig2.xaxis.set_minor_locator(MultipleLocator(0.1))
                            ax1_fig2.tick_params(axis='x', which='both', bottom=True, labelbottom=True, direction='out', color='black', labelcolor='black', length=5, width=0.8)

                            ax1_fig2.grid(axis='x', which='major', linestyle='-', linewidth=1.2, color='#696969', zorder=0)
                            ax1_fig2.grid(axis='x', which='minor', linestyle='--', linewidth=0.7, color='#A9A9A9', zorder=0)

                            current_q_data_for_facet_f2 = df_fig2_filtered_chunk[df_fig2_filtered_chunk['Q_target (m³/s)']==q_val_target_plot_fig2]
                            if current_q_data_for_facet_f2.empty:
                                ax1_fig2.text(0.5,0.5,"无符合条件的点",ha='center',va='center',fontsize=9,transform=ax1_fig2.transAxes)
                                ax1_fig2.set_yticks([]); ax1_fig2.set_yticklabels([]); ax2_fig2.set_yticks([]); ax2_fig2.set_yticklabels([])
                                if q_idx_facet_fig2 % col_wrap_q_facet_fig2 == 0: ax1_fig2.set_ylabel('')
                                ax2_fig2.set_ylabel(''); ax1_fig2.xaxis.set_tick_params(labelbottom=True)
                                continue

                            for _,row_f2 in current_q_data_for_facet_f2.iterrows():
                                is_economic_f2 = row_f2['category']=='经济流速 (0.9-1.5 m/s, 总hf ≤ 5 m/km)'
                                facecolor_v_pt_f2=color_v_f2 if is_economic_f2 else 'none'; edgecolor_v_pt_f2=color_v_f2; linewidth_v_pt_f2=0.6 if is_economic_f2 else 1.8
                                ax1_fig2.scatter(row_f2['D (m)'],row_f2['V_press (m/s)'],marker=marker_style_f2,s=marker_size_f2,facecolors=facecolor_v_pt_f2,edgecolors=edgecolor_v_pt_f2,linewidths=linewidth_v_pt_f2,alpha=0.85,zorder=5)
                                ax1_fig2.text(row_f2['D (m)']+text_offset_x_f2,row_f2['V_press (m/s)'],f" {row_f2['V_press (m/s)']:.2f}m/s",fontsize=text_fontsize_f2,va='center',ha='left',color=color_v_f2,fontweight='bold',zorder=6)
                                facecolor_hf_pt_f2=color_hf_f2 if is_economic_f2 else 'none'; edgecolor_hf_pt_f2=color_hf_f2; linewidth_hf_pt_f2=0.6 if is_economic_f2 else 1.8
                                ax2_fig2.scatter(row_f2['D (m)'],row_f2['hf_total_press (m/km)'],marker=marker_style_f2,s=marker_size_f2,facecolors=facecolor_hf_pt_f2,edgecolors=edgecolor_hf_pt_f2,linewidths=linewidth_hf_pt_f2,alpha=0.85,zorder=5)
                                ax2_fig2.text(row_f2['D (m)']-text_offset_x_f2,row_f2['hf_total_press (m/km)'],f" {row_f2['hf_total_press (m/km)']:.2f}m/km ",fontsize=text_fontsize_f2,va='center',ha='right',color=color_hf_f2,fontstyle='italic',zorder=6)

                            ax1_fig2.set_ylim(0.5,1.8)
                            if q_idx_facet_fig2 % col_wrap_q_facet_fig2 == 0: ax1_fig2.set_ylabel('流速 V (m/s)',color=color_v_f2,fontsize=plt.rcParams['axes.labelsize'])
                            else: ax1_fig2.set_ylabel('')
                            ax1_fig2.tick_params(axis='y',labelcolor=color_v_f2,labelsize=plt.rcParams['ytick.labelsize'],colors=color_v_f2,which='both',direction='out',left=True,labelleft=True,length=5,width=0.8)
                            ax1_fig2.spines["left"].set_edgecolor(color_v_f2); ax1_fig2.spines["left"].set_linewidth(1.5)

                            ax2_fig2.set_ylim(0,5.5)
                            ax2_fig2.set_ylabel('总水头损失 hf_total (m/km)',color=color_hf_f2,fontsize=plt.rcParams['axes.labelsize']*0.9)
                            ax2_fig2.tick_params(axis='y',labelcolor=color_hf_f2,labelsize=plt.rcParams['ytick.labelsize']*0.9,pad=8,colors=color_hf_f2,which='both',direction='out',right=True,labelright=True,length=5,width=0.8)
                            ax2_fig2.spines["right"].set_edgecolor(color_hf_f2); ax2_fig2.spines["right"].set_linewidth(1.5); ax2_fig2.yaxis.set_label_coords(1.15,0.5)

                            if D_values.size > 0: ax1_fig2.set_xlim(min(D_values)-0.05,max(D_values)+0.05)
                            else: ax1_fig2.set_xlim(0,1.5)

                        q_start_str_for_title_fig2 = f"{current_q_chunk_fig2[0]:.1f}"
                        q_end_str_for_title_fig2 = f"{current_q_chunk_fig2[-1]:.1f}"
                        if len(current_q_chunk_fig2) > 1: q_range_title_display_fig2 = f"Q = {q_start_str_for_title_fig2} - {q_end_str_for_title_fig2} {q_unit_tex}"
                        else: q_range_title_display_fig2 = f"Q = {q_start_str_for_title_fig2} {q_unit_tex}"

                        g_fig2.figure.suptitle(f'图2 ({q_range_title_display_fig2}, 管材: {selected_material}): 有压管道优选设计点 (基于总水头损失)',y=(adj_top_f2+(1-adj_top_f2)/2+0.008),fontsize=plt.rcParams['figure.titlesize'])
                        g_fig2.set_xlabels('管径 D (m)')
                        g_fig2.set_titles("Q = {col_name:.1f} " + q_unit_tex)  # 改为1位小数

                        handles_fig2=[Line2D([0],[0],marker=marker_style_f2,color='w',markerfacecolor=color_v_f2,markeredgecolor=color_v_f2,markersize=8,linestyle='None',mew=0.6,label='经济区 流速 (实心蓝)'),
                                      Line2D([0],[0],marker=marker_style_f2,color='w',markerfacecolor=color_hf_f2,markeredgecolor=color_hf_f2,markersize=8,linestyle='None',mew=0.6,label='经济区 总水损 (实心橙)'),
                                      Line2D([0],[0],marker=marker_style_f2,color='w',markerfacecolor='none',markeredgecolor=color_v_f2,markersize=8,linestyle='None',mew=1.8,label='妥协区 流速 (空心蓝)'),
                                      Line2D([0],[0],marker=marker_style_f2,color='w',markerfacecolor='none',markeredgecolor=color_hf_f2,markersize=8,linestyle='None',mew=1.8,label='妥协区 总水损 (空心橙)')]
                        labels_fig2=['经济区 流速 (实心蓝)', '经济区 总水损 (实心橙)', '妥协区 流速 (空心蓝)', '妥协区 总水损 (空心橙)']; final_adj_right_fig2=adj_right_f2-0.04
                        legend_title_fig2 = f'图例 (图2 - {q_range_title_display_fig2})'
                        g_fig2.figure.legend(handles_fig2,labels_fig2,title=legend_title_fig2,loc='center left',bbox_to_anchor=(final_adj_right_fig2+0.01,0.5),frameon=True,title_fontsize='medium',fontsize=plt.rcParams['legend.fontsize']*0.95)
                        plt.subplots_adjust(left=adj_left_f2,right=final_adj_right_fig2,top=adj_top_f2,bottom=adj_bottom_f2,hspace=adj_hspace_f2,wspace=adj_wspace_f2)
                        try: g_fig2.figure.tight_layout(rect=(adj_left_f2,adj_bottom_f2,final_adj_right_fig2,adj_top_f2))
                        except UserWarning as uw_f2:
                            if "Glyph" not in str(uw_f2): print(f"UserWarning during tight_layout for Fig 2 ({q_range_title_display_fig2}): {uw_f2}")
                        except Exception as e_f2: print(f"Error during tight_layout for Fig 2 ({q_range_title_display_fig2}): {e_f2}")

                        filename_q_suffix_fig2 = f"Q_{q_start_label_str_fig2.replace('.','_')}_to_{q_end_label_str_fig2.replace('.','_')}" if len(current_q_chunk_fig2) > 1 else f"Q_{q_start_label_str_fig2.replace('.','_')}"
                        plot_file_fig2_pdf = os.path.join(output_dir,f"图2_优选设计点_总hf_{filename_q_suffix_fig2}_{selected_material.replace('(','_').replace(')','_').replace('=','_')}.pdf")

                        # 保存PDF
                        if OUTPUT_PDF_CHARTS:
                            plt.savefig(plot_file_fig2_pdf)
                            print(f"图2 ({q_range_title_display_fig2}) PDF 已保存: {plot_file_fig2_pdf}")

                        # 确保子图PNG目录存在（防止图1未执行时目录不存在）
                        if OUTPUT_SUBPLOT_PNG:
                            png_subplots_dir = os.path.join(output_dir, "子图PNG", selected_material.replace('(','_').replace(')','_').replace('=','_'))
                            if not os.path.exists(png_subplots_dir):
                                os.makedirs(png_subplots_dir)

                            # 为每个Q值创建独立完整的子图PNG
                            for subplot_idx, q_val in enumerate(current_q_chunk_fig2):
                                # 筛选当前Q值的数据
                                df_fig2_q = df_fig2_filtered_chunk[df_fig2_filtered_chunk['Q_target (m³/s)'] == q_val]
                                
                                if df_fig2_q.empty:
                                    print(f"  跳过图2子图 Q={q_val:.1f}，无符合条件的数据")
                                    continue

                                # 创建独立figure
                                fig_sub2, ax1_sub2 = plt.subplots(figsize=(10, 7))
                                ax2_sub2 = ax1_sub2.twinx()

                                # 设置X轴
                                ax1_sub2.set_xlabel('管径 D (m)', fontsize=12)
                                ax1_sub2.xaxis.set_major_locator(MultipleLocator(0.5))
                                ax1_sub2.xaxis.set_minor_locator(MultipleLocator(0.1))
                                ax1_sub2.tick_params(axis='x', which='both', bottom=True, labelbottom=True, direction='out')
                                ax1_sub2.grid(axis='x', which='major', linestyle='-', linewidth=1.2, color='#696969', zorder=0)
                                ax1_sub2.grid(axis='x', which='minor', linestyle='--', linewidth=0.7, color='#A9A9A9', zorder=0)
                                ax1_sub2.grid(axis='y', which='major', linestyle='-', linewidth=0.8, color='#D3D3D3', zorder=0)

                                # 绘制散点和标注
                                color_v_sub2 = nature_palette[0]
                                color_hf_sub2 = 'darkorange'
                                marker_style_sub2 = 'o'
                                marker_size_sub2 = 80
                                text_fontsize_sub2 = 8
                                text_offset_x_sub2 = 0.02

                                for _, row in df_fig2_q.iterrows():
                                    is_economic = row['category'] == '经济流速 (0.9-1.5 m/s, 总hf ≤ 5 m/km)'
                                    
                                    # 绘制流速散点（左Y轴）
                                    facecolor_v = color_v_sub2 if is_economic else 'none'
                                    linewidth_v = 0.6 if is_economic else 1.8
                                    ax1_sub2.scatter(row['D (m)'], row['V_press (m/s)'],
                                                   marker=marker_style_sub2, s=marker_size_sub2,
                                                   facecolors=facecolor_v, edgecolors=color_v_sub2,
                                                   linewidths=linewidth_v, alpha=0.85, zorder=5)
                                    ax1_sub2.text(row['D (m)'] + text_offset_x_sub2, row['V_press (m/s)'],
                                                f" {row['V_press (m/s)']:.2f}m/s",
                                                fontsize=text_fontsize_sub2, va='center', ha='left',
                                                color=color_v_sub2, fontweight='bold', zorder=6)
                                    
                                    # 绘制水头损失散点（右Y轴）
                                    facecolor_hf = color_hf_sub2 if is_economic else 'none'
                                    linewidth_hf = 0.6 if is_economic else 1.8
                                    ax2_sub2.scatter(row['D (m)'], row['hf_total_press (m/km)'],
                                                   marker=marker_style_sub2, s=marker_size_sub2,
                                                   facecolors=facecolor_hf, edgecolors=color_hf_sub2,
                                                   linewidths=linewidth_hf, alpha=0.85, zorder=5)
                                    ax2_sub2.text(row['D (m)'] - text_offset_x_sub2, row['hf_total_press (m/km)'],
                                                f" {row['hf_total_press (m/km)']:.2f}m/km ",
                                                fontsize=text_fontsize_sub2, va='center', ha='right',
                                                color=color_hf_sub2, fontstyle='italic', zorder=6)

                                # 设置左Y轴
                                ax1_sub2.set_ylabel('流速 V (m/s)', fontsize=12, color=color_v_sub2)
                                ax1_sub2.set_ylim(0.5, 1.8)
                                ax1_sub2.tick_params(axis='y', labelcolor=color_v_sub2, labelsize=10, colors=color_v_sub2, direction='out')
                                ax1_sub2.spines["left"].set_edgecolor(color_v_sub2)
                                ax1_sub2.spines["left"].set_linewidth(1.5)

                                # 设置右Y轴
                                ax2_sub2.set_ylabel('总水头损失 hf_total (m/km)', fontsize=11, color=color_hf_sub2)
                                ax2_sub2.set_ylim(0, 5.5)
                                ax2_sub2.tick_params(axis='y', labelcolor=color_hf_sub2, labelsize=10, colors=color_hf_sub2, direction='out')
                                ax2_sub2.spines["right"].set_edgecolor(color_hf_sub2)
                                ax2_sub2.spines["right"].set_linewidth(1.5)

                                # 设置X轴范围
                                if D_values.size > 0:
                                    ax1_sub2.set_xlim(min(D_values) - 0.05, max(D_values) + 0.05)

                                # 设置标题
                                fig_sub2.suptitle(f'图2: 有压管道优选设计点\n目标流量 Q = {q_val:.1f} m³/s, 管材: {selected_material}',
                                                fontsize=14, y=0.98)

                                # 创建图例
                                handles_sub2 = [
                                    Line2D([0], [0], marker=marker_style_sub2, color='w',
                                          markerfacecolor=color_v_sub2, markeredgecolor=color_v_sub2,
                                          markersize=8, linestyle='None', mew=0.6, label='经济区 流速 (实心蓝)'),
                                    Line2D([0], [0], marker=marker_style_sub2, color='w',
                                          markerfacecolor=color_hf_sub2, markeredgecolor=color_hf_sub2,
                                          markersize=8, linestyle='None', mew=0.6, label='经济区 总水损 (实心橙)'),
                                    Line2D([0], [0], marker=marker_style_sub2, color='w',
                                          markerfacecolor='none', markeredgecolor=color_v_sub2,
                                          markersize=8, linestyle='None', mew=1.8, label='妥协区 流速 (空心蓝)'),
                                    Line2D([0], [0], marker=marker_style_sub2, color='w',
                                          markerfacecolor='none', markeredgecolor=color_hf_sub2,
                                          markersize=8, linestyle='None', mew=1.8, label='妥协区 总水损 (空心橙)')
                                ]
                                fig_sub2.legend(handles=handles_sub2, loc='upper right',
                                              bbox_to_anchor=(0.98, 0.88), fontsize=9, frameon=True, ncol=2)

                                # 调整布局并保存
                                fig_sub2.tight_layout(rect=[0, 0, 1, 0.93])
                                subplot_filename = f"图2_子图_{subplot_idx+1:02d}_Q{q_val:.1f}_{selected_material.replace('(','_').replace(')','_').replace('=','_')}.png"
                                subplot_filepath = os.path.join(png_subplots_dir, subplot_filename)
                                fig_sub2.savefig(subplot_filepath, dpi=300, bbox_inches='tight', pad_inches=0.1)
                                plt.close(fig_sub2)
                                print(f"  子图PNG已保存: {subplot_filename}")

                        plt.close(g_fig2.figure); plt.rcParams['figure.figsize'] = current_figsize_fig2
        else: print(f"图2系列: 管材 {selected_material} 没有有效的有压管道数据可供筛选绘制。")

except FileNotFoundError:
    print(f"绘图错误：CSV文件 {csv_file} 未找到。")
    print(f"请确保文件路径正确，并且计算部分已成功生成CSV文件。")
except Exception as e:
    print(f"绘图过程中发生其他错误: {e}")
    import traceback
    traceback.print_exc()

# --- PDF合并 ---
if OUTPUT_MERGED_PDF:
    print("\n开始合并所有PDF文件...")
    fig1_pdf_files = sorted(glob.glob(os.path.join(output_dir, "图1_流速与总水头损失_Q_*.pdf")))
    print(f"找到 {len(fig1_pdf_files)} 个图1的PDF文件")

    fig2_pdf_pattern = os.path.join(output_dir, "图2_优选设计点_总hf_Q_*.pdf")
    fig2_pdf_files = sorted(glob.glob(fig2_pdf_pattern))
    print(f"找到 {len(fig2_pdf_files)} 个图2的PDF文件")

    all_generated_pdf_files = fig1_pdf_files + fig2_pdf_files

    if all_generated_pdf_files:
        merger = PdfWriter()
        print("\n正在合并以下PDF文件:")
        for pdf_path in all_generated_pdf_files:
            try:
                merger.append(pdf_path)
                print(f"  已添加 {os.path.basename(pdf_path)} 到合并列表")
            except Exception as e_merge:
                print(f"  警告: 无法添加文件 {os.path.basename(pdf_path)} 到合并列表: {e_merge}")

        merged_pdf_filename = f"合并图表_所有图1和图2_五种管材_Q_0.1_to_2.0_全部管材.pdf"
        merged_pdf_filepath = os.path.join(output_dir, merged_pdf_filename)
        try:
            with open(merged_pdf_filepath, "wb") as fout:
                merger.write(fout)
            print(f"\n所有PDF已成功合并到: {merged_pdf_filepath}")
        except Exception as e_merge_write:
            print(f"\n合并PDF文件失败: {e_merge_write}")
        finally:
            merger.close()
    else:
        print("没有找到生成的PDF文件进行合并。")
else:
    print("已跳过 合并PDF 输出（配置为关闭）")

print("\n脚本执行完毕。")
