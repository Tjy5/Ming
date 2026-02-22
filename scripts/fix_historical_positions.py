import json

MINISTERS_FILE = r"d:\1something\Ming\backend\data\ministers.json"
OUTPUT_FILE = r"d:\1something\Ming\backend\data\ministers.json"

def main():
    with open(MINISTERS_FILE, 'r', encoding='utf-8') as f:
        ministers = json.load(f)
        
    # Build maps
    name_to_idx = {m['name']: i for i, m in enumerate(ministers)}
    pos_to_idx = {m.get('position', ''): i for i, m in enumerate(ministers)}
    
    def get_pos(name):
        return ministers[name_to_idx[name]]['position']
        
    def set_pos(name, pos):
        ministers[name_to_idx[name]]['position'] = pos
        print(f"Setting {name} to {pos}")

    # Swaps to make things more historical for 1627
    
    # Swap 1: 崔呈秀 (太仆寺卿 -> 左都御史), 曹于汴 (左都御史 -> 太仆寺卿)
    c_pos = get_pos("崔呈秀")
    cyb_pos = get_pos("曹于汴")
    set_pos("崔呈秀", cyb_pos)
    set_pos("曹于汴", c_pos)
    
    # Swap 2: 张瑞图 (刑部主事 -> 次辅大学士), 张凤翔 (次辅大学士 -> 刑部主事)
    z_pos = get_pos("张瑞图")
    zf_pos = get_pos("张凤翔")
    set_pos("张瑞图", zf_pos)
    set_pos("张凤翔", z_pos)
    
    # Swap 3: 瞿式耜 (大理寺卿 -> 户科给事中), 吴昌时 (户科给事中 -> 大理寺卿)
    q_pos = get_pos("瞿式耜")
    w_pos = get_pos("吴昌时")
    set_pos("瞿式耜", w_pos)
    set_pos("吴昌时", q_pos)

    # Swap 4: 王永光 (户部侍郎 -> 吏部尚书), 房壮丽 (吏部尚书 -> 户部侍郎)
    wy_pos = get_pos("王永光")
    fz_pos = get_pos("房壮丽")
    set_pos("王永光", fz_pos)
    set_pos("房壮丽", wy_pos)

    # 3-way Swap 5: 
    # 周延儒 wants 翰林学士 (currently 温体仁)
    # 温体仁 wants 礼部尚书 (currently 王应熊)
    # 王应熊 gets 吏科给事中 (currently 周延儒)
    zyr_pos = get_pos("周延儒")
    wtr_pos = get_pos("温体仁")
    wyx_pos = get_pos("王应熊")
    
    set_pos("周延儒", wtr_pos)
    set_pos("温体仁", wyx_pos)
    set_pos("王应熊", zyr_pos)
    
    # Verify unique constraints
    positions = [m.get('position') for m in ministers if m.get('position')]
    if len(positions) != len(set(positions)):
        print("ERROR: Duplicate positions found!")
        for p in set(positions):
            if positions.count(p) > 1:
                print(f"Duplicate: {p}")
        return
        
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(ministers, f, ensure_ascii=False, indent=2)
        
    print("Positions updated successfully!")

if __name__ == '__main__':
    main()
