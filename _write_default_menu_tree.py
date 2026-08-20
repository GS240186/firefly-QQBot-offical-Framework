"""一次性脚本：把默认菜单树写入 data/menu_tree.yaml（覆盖）。
通过 reset_tree() 触发：构建默认树 → 写文件 → 同步内存缓存。
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from modules import feature_menu  # noqa: E402

ok, msg = feature_menu.reset_tree()
print("reset_tree:", ok, msg)
print("写入文件:", feature_menu._TREE_FILE)

# 立即读一次，确认可正常加载（即不再有 'dict' has no attribute 'strip' 错误）
tree = feature_menu.load_tree(force=True)
paths = feature_menu.list_all_paths()
print("加载成功：root.children 个数 =", len(tree.get("root", {}).get("children", {})))
print("全部路径条数 =", len(paths))
print("前 5 条路径 =", paths[:5])
