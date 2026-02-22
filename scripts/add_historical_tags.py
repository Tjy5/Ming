import json
import os

MINISTERS_FILE = r"d:\1something\Ming\backend\data\ministers.json"
OUTPUT_FILE = r"d:\1something\Ming\backend\data\ministers.json"

# Explicitly known Hanlin figures
HANLIN_NAMES = {
    "周延儒", "钱谦益", "温体仁", "黄道周", "倪元璐", 
    "李标", "王应熊", "韩爌", "钱龙锡", "魏藻德"
}

# Explicitly known Military generals
TRUE_MILITARY = {"满桂", "赵率教", "毛文龙", "祖大寿"}

def main():
    with open(MINISTERS_FILE, 'r', encoding='utf-8') as f:
        ministers = json.load(f)
        
    for m in ministers:
        tags = m.setdefault("personality_tags", [])
        
        # 1. Nobility logic: faction is '勋贵集团'
        if m.get("faction") == "勋贵集团":
            if "勋贵" not in tags:
                tags.append("勋贵")
                print(f"Added [勋贵] tag to {m['name']}")
                
        # 2. Hanlin logic: explicit names or positions containing 学士, 编修, 修撰
        has_hanlin_pos = any(pos in ["翰林学士", "翰林编修", "翰林修撰", "首辅大学士", "次辅大学士", "东阁大学士", "文渊阁大学士", "武英殿大学士"] for pos in m.get("positions", []))
        if m["name"] in HANLIN_NAMES or has_hanlin_pos:
            if "翰林" not in tags:
                tags.append("翰林")
                print(f"Added [翰林] tag to {m['name']}")
                
        # 3. Military logic: explicit names or position containing 总兵
        has_military_pos = any("总兵" in pos for pos in m.get("positions", []))
        if m["name"] in TRUE_MILITARY or has_military_pos:
            if "武将" not in tags:
                tags.append("武将")
                print(f"Added [武将] tag to {m['name']}")
                
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(ministers, f, ensure_ascii=False, indent=2)
        
    print("Tags updated successfully!")

if __name__ == '__main__':
    main()
