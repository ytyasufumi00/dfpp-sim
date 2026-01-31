import streamlit as st
import math
import pandas as pd
import numpy as np
import os

# --- ページ設定 ---
st.set_page_config(page_title="DFPP Sim Ver.35", layout="wide")
st.title("🧮 DFPP Advanced Simulator Ver.35")
st.markdown("### 流量表示レイアウト改善 & 解説改訂版")

# --- 2カラムレイアウト ---
left_col, right_col = st.columns([1, 1.3])

with left_col:
    # ---------------------------------------------------------
    # 1. 入力パラメータ
    # ---------------------------------------------------------
    st.header("1. 条件設定")
    
    with st.expander("👤 患者データ (EPV計算用)", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            weight = st.number_input("体重 (kg)", 20.0, 150.0, 60.0, 0.5)
        with c2:
            # 身長入力 (任意)
            height = st.number_input("身長 (cm) [任意]", 0.0, 250.0, 0.0, 1.0, help="入力すると「小川の式」で精密計算します。0の場合は「簡易式(体重/13)」を使用します。")
        
        sex = st.radio("性別 (小川の式で使用)", ("男性", "女性"), horizontal=True)
        ht = st.number_input("ヘマトクリット (%)", 10.0, 60.0, 30.0, 0.5)
        pre_alb = st.number_input("治療前アルブミン (g/dL)", 1.0, 6.0, 3.0, 0.1)

    with st.expander("⚙️ 膜とターゲット", expanded=True):
        # 膜プリセット
        membrane_preset = st.radio(
            "膜のプリセット選択",
            ("EC-20 (小孔径)", "EC-30 (中孔径)", "EC-40 (大孔径)"),
            index=0,
            horizontal=True
        )
        
        # --- 膜ごとのデフォルト設定 ---
        if "EC-20" in membrane_preset:
            def_sc_target = 0.20
            def_sc_alb = 0.40 
            desc = "小孔径: IgG除去は強力だが、二次膜形成によりAlbも抜けやすい(実測SC 0.35~0.4)。"
        elif "EC-30" in membrane_preset:
            def_sc_target = 0.40
            def_sc_alb = 0.70
            desc = "中孔径: バランス型。"
        else: # EC-40
            def_sc_target = 0.70
            def_sc_alb = 0.85
            desc = "大孔径: Albはよく戻る(SC高)が、除去効率は悪い。"
            
        st.caption(f"特徴: {desc}")

        # スライダー
        col_sc1, col_sc2 = st.columns(2)
        with col_sc1:
            sc_target = st.slider(
                "目的物質 SC", 0.0, 1.0, def_sc_target, 0.01, 
                help="低いほどよく抜ける（除去される）。",
                key=f"sc_target_{membrane_preset}"
            )
        with col_sc2:
            sc_alb = st.slider(
                "アルブミン SC", 0.0, 1.0, def_sc_alb, 0.01, 
                help="高いほど体内に戻る（回収される）。",
                key=f"sc_alb_{membrane_preset}"
            )

        st.markdown("---")
        target_rr_pct = st.number_input("🎯 目的物質の目標除去率 (%)", 10.0, 99.9, 70.0, 1.0)

    # ---------------------------------------------------------
    # 2. 運用条件
    # ---------------------------------------------------------
    with st.expander("⏱️ 運用計画 (流量算出)", expanded=True):
        st.write("目標の処理量をどれくらいの時間で回すか計画します")
        target_time_hr = st.number_input("目標治療時間 (時間)", 1.0, 6.0, 3.0, 0.5)
        discard_ratio_pct = st.slider("廃棄率 (QD/QP比) %", 5, 30, 20)
        
        # レシピ設定
        st.markdown("---")
        st.write("🧪 **補充液レシピ設定**")
        recipe_mode = st.radio(
            "調製モード",
            ("喪失量に合わせる (推奨)", "濃度固定 (4.0%)"),
            help="通常は「喪失量に合わせる」を選択してください。EC-20等でAlb喪失が多い場合、4%固定では補充不足になります。"
        )

# --- 計算ロジック ---
def run_simulation():
    # --- EPV計算ロジック分岐 ---
    calc_method_name = ""
    calc_description = ""
    bv_liter = 0.0
    
    if height > 0:
        # 1. 小川の式 (身長入力あり)
        h_m = height / 100.0
        if sex == "男性":
            # 男性: V = 0.168*H^3 + 0.050*W + 0.444
            bv_liter = 0.168 * (h_m**3) + 0.050 * weight + 0.444
        else:
            # 女性: V = 0.250*H^3 + 0.0625*W + 0.662
            bv_liter = 0.250 * (h_m**3) + 0.0625 * weight + 0.662
        
        epv = bv_liter * (1 - ht / 100)
        calc_method_name = "小川の式 (Ogawa Formula)"
        calc_description = f"身長({height}cm)・体重・性別から精密計算"
    else:
        # 2. 簡易式 (身長入力なし = 体重とHtのみ)
        bv_liter = weight / 13.0
        epv = bv_liter * (1 - ht / 100)
        calc_method_name = "簡易式 (Weight based)"
        calc_description = "体重 ÷ 13 × (1 - Ht) で計算"

    efficiency_target = 1 - sc_target
    efficiency_alb = 1 - sc_alb
    
    if efficiency_target <= 0.001: return None, "⚠️ SCが高すぎて計算不可"
    
    target_rr = target_rr_pct / 100.0
    if target_rr >= 0.999: target_rr = 0.999
    
    try:
        required_pv = -math.log(1 - target_rr) / efficiency_target
    except:
        required_pv = 100.0
        
    v_treated = required_pv * epv
    
    # 濃度一定モデルでのAlb喪失量
    total_alb_loss = v_treated * (pre_alb * 10) * efficiency_alb
    
    # 流量計算
    req_qp = (v_treated * 1000) / (target_time_hr * 60)
    req_qd = req_qp * (discard_ratio_pct / 100.0)
    total_waste_vol = req_qd * (target_time_hr * 60) / 1000
    
    return epv, v_treated, required_pv, total_alb_loss, req_qp, req_qd, total_waste_vol, calc_method_name, calc_description

results = run_simulation()

if results[0] is None:
    st.error(results[1])
else:
    epv, v_treated, required_pv, loss_alb_mass, req_qp, req_qd, total_waste_vol, calc_name, calc_desc = results

    # --- 右カラム：結果表示 ---
    with right_col:
        st.header("2. シミュレーション結果")
        
        if required_pv > 2.0:
            st.warning(f"⚠️ **高負荷警告**: {required_pv:.1f} PV の処理が必要です。")

        # --- 計算式の明示 ---
        if "小川" in calc_name:
            st.success(f"✅ **{calc_name}** を使用: {calc_desc}")
        else:
            st.info(f"ℹ️ **{calc_name}** を使用: {calc_desc}")

        m1, m2, m3 = st.columns(3)
        m1.metric("推定循環血漿量 (EPV)", f"{epv:.2f} L", help=f"計算式: {calc_name}")
        m2.metric("必要な総処理量", f"{v_treated:.1f} L", f"{required_pv:.2f} PV", delta_color="inverse")
        
        # 予想Alb喪失量
        bottles_needed = math.ceil(loss_alb_mass / 10.0)
        m3.metric(
            "予想Alb喪失量", 
            f"{loss_alb_mass:.0f} g", 
            f"補充目安: {bottles_needed} 本 (20% 50mL)", 
            delta_color="inverse",
            help="この量を補充液に混ぜて戻す必要があります"
        )
        
        st.info(f"📋 **処方目安** ({target_time_hr}時間): QP **{req_qp:.0f}** mL/min / QD **{req_qd:.1f}** mL/min / 置換液 **{total_waste_vol:.1f}** L")

        # -----------------------------------------------------
        # 🧪 補充液調製シミュレーション
        # -----------------------------------------------------
        st.markdown("---")
        st.subheader("🧪 補充液調製レシピ (フィジオ140 + 20%Alb)")
        
        if "喪失量に合わせる" in recipe_mode:
            needed_alb_g = loss_alb_mass
            needed_alb_vol_L = needed_alb_g / 200.0 # 20% = 200g/L
            final_conc_percent = (needed_alb_g / (total_waste_vol * 10))
            
            if needed_alb_vol_L > total_waste_vol:
                st.error("⚠️ **警告**: アルブミン喪失量が多すぎて、予定の置換液量(廃液量)に収まりません！QDを増やすか、別経路での補充を検討してください。")
            else:
                needed_physio_vol_L = total_waste_vol - needed_alb_vol_L
                
                st.markdown(f"##### ✅ 目標: 喪失した **{loss_alb_mass:.0f}g** を完全に補充する")
                
                rec_c1, rec_c2 = st.columns(2)
                with rec_c1:
                    st.warning(f"**推奨レシピ (全体量 {total_waste_vol:.1f}L 分)**")
                    st.code(f"""
[ ベース液 ]
フィジオ140  : {needed_physio_vol_L:.2f} L

[ 添加剤 ]
20%アルブミン : {needed_alb_vol_L*1000:.0f} mL
             (約 {needed_alb_vol_L*1000 / 50:.1f} 本)
---------------------------
合計液量     : {total_waste_vol:.2f} L
アルブミン量 : {loss_alb_mass:.0f} g ({final_conc_percent:.1f}%)
                    """, language="text")
                with rec_c2:
                    st.info("**作成のポイント**")
                    if final_conc_percent > 6.0:
                        st.write("⚠️ **高濃度です**: EC-20等を使用時は喪失量が多いため、通常より高濃度の補充が必要です。")
                    else:
                        st.write("標準的な濃度範囲です。")
        else:
            # 濃度固定モード (4.0%)
            fixed_conc = 4.0
            supplied_alb_g = total_waste_vol * 10 * fixed_conc 
            diff_g = supplied_alb_g - loss_alb_mass
            
            st.markdown(f"##### ⚠️ 設定: 濃度 **4.0%** で固定作成")
            if diff_g < -5.0:
                st.error(f"⛔ **危険**: アルブミンが **{abs(diff_g):.0f} g 不足** します！")
            elif diff_g > 5.0:
                st.warning(f"アルブミンが **{diff_g:.0f} g 過剰** です。")
            else:
                st.success("バランスは概ね良好です。")

            vol_alb_L = total_waste_vol * 0.2
            vol_physio_L = total_waste_vol * 0.8
            
            st.code(f"""
[ 4%固定レシピ ]
フィジオ140  : {vol_physio_L:.2f} L
20%アルブミン : {vol_alb_L*1000:.0f} mL ({vol_alb_L*1000/50:.1f} 本)
補充Alb量    : {supplied_alb_g:.0f} g (不足: {abs(diff_g):.0f} g)
            """, language="text")

        # -----------------------------------------------------
        # 🖼️ 回路図と設定流量 (レイアウト変更)
        # -----------------------------------------------------
        st.markdown("---")
        st.subheader("🖼️ 回路図と設定流量")
        
        # 左右に分割
        col_img, col_metrics = st.columns([1, 1])

        # 左側: 画像
        with col_img:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            image_path = os.path.join(current_dir, "dfpp_circuit.png")
            try:
                st.image(image_path, caption="DFPP回路図", use_container_width=True)
            except:
                st.warning(f"⚠️ 画像が見つかりません: {image_path}")

        # 右側: 計算された流量
        with col_metrics:
            st.markdown("#### ⚙️ 計算された流量")
            st.metric("🟡 QP (血漿流量)", f"{req_qp:.0f} mL/min", help="分離器への供給流量")
            st.metric("🔴 QD (廃棄流量)", f"{req_qd:.1f} mL/min", help="成分分離器からの廃棄流量")
            st.metric("🟢 置換液 (=補充液)", f"{total_waste_vol:.1f} L", help="総廃液量と同じ量を補充します")
            
            st.markdown(f"""
            <div style="background-color:#f0f2f6; padding:10px; border-radius:5px; font-size:0.9em;">
            <b>設定内容:</b><br>
            治療時間: {target_time_hr} 時間<br>
            廃棄率: {discard_ratio_pct} %
            </div>
            """, unsafe_allow_html=True)

        # -----------------------------------------------------
        # 📊 グラフ
        # -----------------------------------------------------
        st.markdown("---")
        st.subheader("📊 除去量・喪失量シミュレーション")
        x_pv = np.linspace(0, max(2.0, required_pv * 1.2), 100)
        y_rr = (1 - np.exp( -x_pv * (1 - sc_target) )) * 100
        slope = epv * (pre_alb * 10) * (1 - sc_alb)
        y_alb_loss = x_pv * slope
        
        chart_data = pd.DataFrame({
            "処理量 (PV)": x_pv,
            "目的物質 除去率 (%)": y_rr,
            "Alb 喪失量 (g)": y_alb_loss
        })
        st.line_chart(chart_data, x="処理量 (PV)", y=["目的物質 除去率 (%)", "Alb 喪失量 (g)"])

        # -----------------------------------------------------
        # 📚 詳細用語解説
        # -----------------------------------------------------
        st.markdown("---")
        st.subheader("📚 専門医・研修医のための詳細用語解説")

        with st.expander("🔍 1. QP と QD の臨床的意義 (Detailed)", expanded=True):
            st.markdown(f"""
            #### **QP (Plasma Flow: 血漿流量)**
            * **定義**: 一次膜（分離器）で血液から分離され、二次膜（成分分離器）へ送られる血漿の流量。
            * **設定目安**: $20 \\sim 40$ mL/min。
            * **注意点**: QPを上げすぎると二次膜の膜圧(TMP)が上昇し、Foulingを引き起こします。逆に低すぎると治療時間が延びます。
            
            #### **QD (Drainage Flow: 廃棄流量)**
            * **定義**: 二次膜内で濃縮され、最終的に廃棄バッグへ捨てられる流量。
            * **設定目安**: QPの $10 \\sim 20$\% 程度。
            * **意義**: QDが高いほど濃縮率が上がりAlb回収率は良くなりますが、目詰まりが早まります。QDが低いとAlb喪失が増えます。
            """)
        
        with st.expander("💉 2. アルブミン補充目安 (20%製剤)", expanded=True):
             st.info("現在は **20%アルブミン製剤** が主流のため、**50mL = 10g** で計算しています。")

        with st.expander("⚗️ 3. SC (ふるい係数) と 阻止率 (RC)", expanded=True):
            st.markdown("""
            * **SC (Sieving Coefficient)**: 膜を「通り抜けて体に戻る」割合 ($0.0 \\sim 1.0$)。
            * **RC (Rejection Coefficient)**: 膜で「阻止されて廃棄される」割合 ($RC = 1 - SC$)。
            """)

        # --- 解説文を修正 ---
        with st.expander("⚠️ 4. カタログ値・他サイトとの乖離理由 (重要)", expanded=True):
            st.info("""
            **「メーカーの計算サイトと結果が違う」** 場合、使用しているデータの前提が異なることが主な要因です。
            """)
            st.markdown("""
            #### **① ふるい係数 (SC) の基準差 (In vitro vs In vivo)**
            * **他サイト**: 
                * 添付文書に記載された **牛アルブミン血清 (In vitro)** のデータである **SC=0.6 (EC-20)** や、
                * 旭化成カスケードフロー資料にある **SC=0.35 (ヒト血漿 In vitro)** など、
                * データソースが混在しており、他サイトの予測式もこれら（特に仕様値の0.6）を参照している場合が多いと思われます。
            
            * **本アプリ**: 
                * ヒト血漿での **二次膜形成 (Fouling)** を考慮し、実測値に近い **SC=0.4** で厳しく計算しています。
            
            * **結果**: 
                * 本アプリの方がアルブミン喪失量（補充必要量）が多く算出されます。これは **補充不足による低血圧等のトラブルを防ぐため、安全サイド** の数値を出すように設計しているためです。

            #### **② 循環血漿量 (EPV) 計算式の違い**
            * **簡易式**: `体重 ÷ 13`。簡便ですが、肥満や痩せ型で誤差が出ます。
            * **小川の式**: 日本人の体格に合わせた精密式。身長・体重・性別を用います。
            * **結果**: 身長を入力して小川の式を使うと、簡易式より正確なPVが算出され、処理量設定の精度が上がります。
            """)

        with st.expander("🩸 5. 循環血漿量 (EPV) の計算ロジック詳細", expanded=True):
            st.markdown("""
            **EPV (Estimated Plasma Volume)** は、治療のベースとなる「患者さんの体内の血漿総量」です。
            * **簡易式**: $EPV = \\text{Weight}/13 \\times (1 - Ht/100)$
            * **小川の式**: 身長・体重・性別から $BV$ を求め、$(1-Ht)$ を掛けて算出します。
            """)

        with st.expander("🧮 6. 必要処理量の計算ロジック (One-compartment model) 詳細", expanded=True):
            st.markdown("""
            血液浄化では、浄化された血液が体内に戻って混ざるため、濃度は対数的に減衰します。
            #### **計算式**
            """)
            st.latex(r"V_{treated} = \frac{- EPV \times \ln(1 - RR)}{RC}")
            st.markdown(f"""
            1.  **$RR$ (Removal Rate)**: 目標除去率。
            2.  **$\\ln$ (自然対数)**: 「薄まりながら減る」効率低下を補正。
            3.  **$RC$ (Rejection Coefficient)**: 膜の実質的な除去能力 ($1-SC$)。
            """)
