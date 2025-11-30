import streamlit as st
import pandas as pd
import numpy as np
import re
import io

# ==========================================
# ページ設定
# ==========================================
st.set_page_config(page_title="配置馬券術判定", layout="wide")

st.title("🏇 配置馬券術 判定アプリ (Mobile Ver)")
st.write("ExcelまたはCSVファイルをアップロードしてください。")

# ==========================================
# ロジック関数群
# ==========================================

def to_half_width(text):
    """全角数字を半角数字に変換し、数字以外の文字を除去する"""
    if pd.isna(text): return text
    text = str(text)
    
    # 1. 全角数字を半角に変換
    table = str.maketrans('０１２３４５６７８９', '0123456789')
    text = text.translate(table)
    
    # 2. 数字とドット以外を除去 (例: "11R" -> "11", "第1レース" -> "1")
    # 小数点(単オッズなど)も考慮してドットは残す
    text = re.sub(r'[^\d\.]', '', text)
    
    return text

def normalize_name(x):
    if pd.isna(x): return ''
    normalized_name = str(x).strip().replace('　', '').replace(' ', '')
    normalized_name = re.sub(r'[★☆▲△◇]', '', normalized_name)
    if ',' in normalized_name: normalized_name = normalized_name.split(',')[0]
    text = re.sub(r'[0-9\.]+[Rr]', '', normalized_name)
    text = re.sub(r'\(.*?\)', '', text)
    return text.replace('/', '').strip()

def load_and_clean_data(file_obj, filename, sheet_name=None):
    # ファイル読み込み
    if filename.lower().endswith('.csv'):
        try: df = pd.read_csv(file_obj, encoding='cp932', on_bad_lines='skip')
        except: df = pd.read_csv(file_obj, encoding='utf-8', on_bad_lines='skip')
    else:
        # Excelの場合
        if sheet_name:
            df = pd.read_excel(file_obj, sheet_name=sheet_name, engine='openpyxl')
        else:
            df = pd.read_excel(file_obj, engine='openpyxl')

    # 列名のクリーニング (空白除去)
    df.columns = df.columns.str.strip()
    
    # ★ヘッダー名のゆらぎ吸収 (全角R、レース表記など)
    rename_map = {
        '場所': '場名', 
        '単オッズ': '単ｵｯｽﾞ', 
        '調教師': '厩舎', 
        'レース': 'R',
        'Ｒ': 'R'  # 全角Rに対応
    }
    df = df.rename(columns=rename_map)

    if '場名' not in df.columns: df['場名'] = 'Unknown'
    
    # ★数値列の全角・半角統一とクリーニング
    target_numeric_cols = ['R', '正番', '単ｵｯｽﾞ', '逆番', '正循環', '逆循環', '頭数']
    for col in target_numeric_cols:
        if col in df.columns:
            # 全角->半角変換 & 余計な文字削除
            df[col] = df[col].apply(to_half_width)
            # 数値化 (変換できないものはNaNに)
            df[col] = pd.to_numeric(df[col], errors='coerce')
    
    # Rと正番が有効な行だけ残す
    df = df.dropna(subset=['R', '正番'])
    df['R'] = df['R'].astype(int)
    df['正番'] = df['正番'].astype(int)

    # 名前正規化
    for col in ['騎手', '厩舎', '馬主']:
        if col in df.columns:
            df[col] = df[col].apply(normalize_name)
        else:
            df[col] = '' 

    # 必要な列の確保
    potential_cols = ['R', '場名', '馬名', '正番', '騎手', '厩舎', '馬主', '単ｵｯｽﾞ', '逆番', '正循環', '逆循環', '頭数']
    for col in potential_cols:
        if col not in df.columns: df[col] = np.nan
            
    return df[potential_cols].copy()

def calc_haichi_numbers(df: pd.DataFrame) -> pd.DataFrame:
    # 既存の値があれば優先
    if df[['逆番', '正循環', '逆循環']].notna().all().all():
        df['計算_逆番'] = df['逆番']
        df['計算_正循環'] = df['正循環']
        df['計算_逆循環'] = df['逆循環']
        df['頭数'] = df['頭数'] if '頭数' in df.columns else 16
        return df

    # 頭数計算
    if '頭数' in df.columns and df['頭数'].notna().any():
        df['使用頭数'] = df['頭数'].fillna(16).astype(int)
    else:
        race_counts = df.groupby(['場名', 'R'])['正番'].max().to_dict()
        df['使用頭数'] = df.apply(lambda x: race_counts.get((x['場名'], x['R']), 16), axis=1)

    def calc_row(row):
        total = int(row['使用頭数'])
        seiban = int(row['正番'])
        gyakuban = int(row['逆番']) if pd.notna(row['逆番']) else (total + 1) - seiban
        sei_j = int(row['正循環']) if pd.notna(row['正循環']) else total + seiban
        gyaku_j = int(row['逆循環']) if pd.notna(row['逆循環']) else total + gyakuban
        return pd.Series([total, gyakuban, sei_j, gyaku_j])
    
    df[['頭数', '計算_逆番', '計算_正循環', '計算_逆循環']] = df.apply(calc_row, axis=1)
    return df

def get_pair_pattern(row1, row2):
    def val(x):
        try: return int(float(x)) 
        except: return None
    r1 = [val(row1.get('正番')), val(row1.get('計算_逆番')), val(row1.get('計算_正循環')), val(row1.get('計算_逆循環'))]
    r2 = [val(row2.get('正番')), val(row2.get('計算_逆番')), val(row2.get('計算_正循環')), val(row2.get('計算_逆循環'))]
    label = list("ABCDEFGHIJKLMNOP")
    pairs = [label[i * 4 + j] for i in range(4) for j in range(4)
             if r1[i] is not None and r2[j] is not None and r1[i] == r2[j] and r1[i] != 0]
    b1, b2 = val(row1.get('正番')), val(row2.get('正番'))
    if b1 is not None and b2 is not None:
        if str(b1)[-1] == str(b2)[-1]:
            if b1 < 10 and b2 >= 10: pairs.append('Q')
            elif b1 >= 10 and b2 < 10: pairs.append('R')
    return ",".join(pairs)

def get_common_values(group: pd.DataFrame):
    cols = ['正番', '計算_逆番', '計算_正循環', '計算_逆循環']
    common_set = None
    for _, row in group.iterrows():
        current_set = set()
        for col in cols:
            val = row.get(col)
            if pd.notna(val):
                try:
                    num = int(float(val))
                    if num != 0: current_set.add(num)
                except: continue
        if common_set is None: common_set = current_set
        else: common_set = common_set.intersection(current_set)
        if not common_set: return None
    if common_set: return ','.join(map(str, sorted(list(common_set))))
    return None

def find_all_pairs(df: pd.DataFrame) -> pd.DataFrame:
    all_pairs = []
    df = df.sort_values(by=['R', '場名']).reset_index(drop=True)
    # 騎手
    for name, group in df.groupby('騎手'):
        if name == "": continue
        group = group.sort_values('R').to_dict('records')
        for i in range(len(group) - 1):
            curr, next_r = group[i], group[i+1]
            if curr['場名'] != next_r['場名']: continue
            detected = get_pair_pattern(curr, next_r)
            if detected:
                all_pairs.append({'場名': curr['場名'], '対象名': name, '属性': '騎手', 'レースA': curr['R'], '馬名A': curr['馬名'], 'レースB': next_r['R'], '馬名B': next_r['馬名'], 'パターン': detected, '総出走数': len(group)})
    # 厩舎
    if '厩舎' in df.columns:
        for (place, name), group in df.groupby(['場名', '厩舎']):
            if name == "": continue
            races = group.sort_values('R').to_dict('records')
            for i in range(len(races)):
                for j in range(i + 1, len(races)):
                    curr, next_r = races[i], races[j]
                    detected = get_pair_pattern(curr, next_r)
                    if detected:
                        all_pairs.append({'場名': place, '対象名': name, '属性': '厩舎', 'レースA': curr['R'], '馬名A': curr['馬名'], 'レースB': next_r['R'], '馬名B': next_r['馬名'], 'パターン': detected, '総出走数': len(races)})
    # 馬主
    if '馬主' in df.columns:
        for name, group in df.groupby('馬主'):
            if name == "": continue
            races = group.sort_values(['R', '場名']).to_dict('records')
            for i in range(len(races)):
                for j in range(i + 1, len(races)):
                    curr, next_r = races[i], races[j]
                    detected = get_pair_pattern(curr, next_r)
                    if detected:
                        loc = f"{curr['場名']}→{next_r['場名']}" if curr['場名'] != next_r['場名'] else curr['場名']
                        all_pairs.append({'場名': loc, '対象名': name, '属性': '馬主', 'レースA': curr['R'], '馬名A': curr['馬名'], 'レースB': next_r['R'], '馬名B': next_r['馬名'], 'パターン': detected, '総出走数': len(races)})
    return pd.DataFrame(all_pairs)

def get_blue_recommendations(df_calculated: pd.DataFrame) -> pd.DataFrame:
    blue_recs = []
    for col in ['騎手', '厩舎', '馬主']:
        if col not in df_calculated.columns: continue
        group_keys = ['場名', col] if col == '騎手' else [col]
        try:
            for name, group in df_calculated.groupby(group_keys):
                target_name = None
                if len(group_keys) == 2:
                    if isinstance(name, tuple) and len(name) == 2: location, target_name = name
                else:
                    if isinstance(name, tuple) and len(name) == 1: target_name = name[0]
                    elif isinstance(name, str): target_name = name
                
                if not target_name or target_name == "" or len(group) < 2: continue
                common_vals = get_common_values(group)
                if common_vals:
                    remark = f'{col}共通値 ({common_vals})'
                    if len(group) == 2: remark += " (2鞍限定)"
                    for _, row in group.iterrows():
                        blue_recs.append({'場名': row['場名'], 'R': row['R'], '馬名': row['馬名'], '属性': col, '対象名': target_name, '判定': '★ 青塗対象', '条件': remark, '重要度': 9})
        except: continue
    df_blue = pd.DataFrame(blue_recs)
    if not df_blue.empty:
        df_blue = df_blue.drop_duplicates(subset=['場名', 'R', '馬名', '判定'], keep='last')
        df_blue = pd.merge(df_blue, df_calculated[['場名', 'R', '馬名', '単ｵｯｽﾞ']], on=['場名', 'R', '馬名'], how='left')
        return df_blue
    return pd.DataFrame()

def evaluate_and_score(df_pairs: pd.DataFrame, df_original_data: pd.DataFrame) -> pd.DataFrame:
    recommendations = []
    high_prob_patterns = ['C', 'D', 'G', 'H']
    for _, row in df_pairs.iterrows():
        race_a, race_b = row['レースA'], row['レースB']
        horse_a, horse_b = row['馬名A'], row['馬名B']
        target_name, pattern = row['対象名'], row['パターン']
        place_name, attribute = row['場名'], row['属性']
        is_blue = (row['総出走数'] == 2 and attribute == '騎手')
        
        jb, pb = ("◎ 狙い目", 3)
        if is_blue: jb, pb = ("☆ 2鞍ペア", 5)
        elif any(p in pattern for p in high_prob_patterns): jb, pb = ("○ チャンス", 4)
        recommendations.append({'場名': place_name, 'R': race_b, '馬名': horse_b, '騎手/厩舎/馬主': f"{attribute}:{target_name}", '判定': jb, '条件': f"ペア({race_a}R {horse_a})凡走待ち/パターン:{pattern}", '重要度': pb})
        
        ja, pa = ('▲ 先買いリスク', 1) if not is_blue else ('○ 2鞍先買い', 2)
        recommendations.append({'場名': place_name, 'R': race_a, '馬名': horse_a, '騎手/厩舎/馬主': f"{attribute}:{target_name}", '判定': ja, '条件': f"次走{race_b}Rにペアあり/パターン:{pattern}", '重要度': pa})
    
    df_rec = pd.DataFrame(recommendations)
    if df_rec.empty: return pd.DataFrame()
    df_rec = pd.merge(df_rec, df_original_data[['R', '馬名', '単ｵｯｽﾞ']], on=['R', '馬名'], how='left')
    
    final_list = []
    for _, row in df_rec.iterrows():
        odds = row['単ｵｯｽﾞ']
        priority = row['重要度']
        if pd.isna(odds): pass
        elif odds > 49.9:
            if priority >= 3:
                row['判定'] = '△ 紐候補'
                row['重要度'] = 0
                row['条件'] = f'【高配】' + row['条件']
            else: continue 
        elif 10.0 <= odds <= 20.0 and priority >= 3:
            row['判定'] = row['判定'].replace('狙い目', '狙い目(高)')
            row['重要度'] += 1
        final_list.append(row)
    return pd.DataFrame(final_list)

# ==========================================
# メイン UI 処理
# ==========================================

uploaded_file = st.file_uploader("", type=['xlsx', 'xlsm', 'csv'])

if uploaded_file is not None:
    sheet_name = None
    if uploaded_file.name.endswith(('.xlsx', '.xlsm')):
        try:
            xl = pd.ExcelFile(uploaded_file, engine='openpyxl')
            sheet_list = xl.sheet_names
            if len(sheet_list) > 1:
                sheet_name = st.selectbox("シートを選択してください", sheet_list)
            else:
                sheet_name = sheet_list[0]
        except Exception as e:
            st.error(f"Excel読み込みエラー: {e}")

    if st.button('判定実行'):
        with st.spinner('分析中...'):
            try:
                uploaded_file.seek(0)
                df_all = load_and_clean_data(uploaded_file, uploaded_file.name, sheet_name)
                
                if df_all.empty:
                    st.warning("有効なデータが見つかりませんでした。")
                else:
                    df_calculated = calc_haichi_numbers(df_all.copy())
                    
                    df_all_pairs = find_all_pairs(df_calculated)
                    df_blue = get_blue_recommendations(df_calculated)
                    df_ar = evaluate_and_score(df_all_pairs, df_all)
                    
                    if not df_blue.empty:
                        df_blue = df_blue.rename(columns={'対象名': '騎手/厩舎/馬主'})
                        df_blue = df_blue.assign(**{'騎手/厩舎/馬主': lambda x: x['属性'] + ':' + x['騎手/厩舎/馬主']}).drop(columns=['属性'])
                        df_final = pd.concat([df_blue, df_ar], ignore_index=True)
                    else:
                        df_final = df_ar

                    if df_final.empty:
                        st.info("推奨馬は見つかりませんでした。")
                    else:
                        # 重複まとめ
                        df_final = df_final.sort_values('重要度', ascending=False)
                        agg_rules = {
                            '騎手/厩舎/馬主': lambda x: ' + '.join(sorted(set(x))), 
                            '単ｵｯｽﾞ': 'first',
                            '判定': 'first',
                            '条件': lambda x: ' / '.join(x),
                            '重要度': 'sum'
                        }
                        df_final = df_final.groupby(['場名', 'R', '馬名'], as_index=False).agg(agg_rules)
                        # ソート: 場名 > レース > 重要度
                        df_final = df_final.sort_values(['場名', 'R', '重要度'], ascending=[True, True, False])

                        st.success("分析完了！")
                        
                        cols = ['場名', 'R', '馬名', '騎手/厩舎/馬主', '単ｵｯｽﾞ', '判定', '条件']
                        
                        buffer = io.BytesIO()
                        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                            df_final.to_excel(writer, index=False, sheet_name='結果')
                        
                        st.download_button(
                            label="💾 結果をExcelでダウンロード",
                            data=buffer.getvalue(),
                            file_name="result.xlsx",
                            mime="application/vnd.ms-excel"
                        )
                        st.dataframe(df_final[cols], hide_index=True, use_container_width=True)

            except Exception as e:
                st.error(f"エラーが発生しました: {e}")
