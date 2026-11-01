import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gas_client import GasClient

def main():
    print("=== GasClient 動作検証 ===")
    client = GasClient()

    # 1. プロジェクト一覧
    projects = client.list_projects(limit=5)
    print(f"Projects ({len(projects)}):")
    for p in projects:
        print(f" - {p['name']}: {p['id']}")

    target_project = sys.argv[1] if len(sys.argv) > 1 else (projects[0]["name"] if projects else "")
    if not target_project:
        print("検証対象のプロジェクトが見つかりません。")
        return

    # 2. ファイル一覧
    files = client.list_files(target_project)
    print(f"\nFiles in {target_project}:")
    for f in files:
        print(f" - {f['name']}.{f['type']} ({f['length']} chars)")

    # 3. 関数一覧テスト
    funcs_list = client.list_functions(target_project)
    print(f"\nFunctions in {target_project}:")
    for item in funcs_list:
        if item.get("functions"):
            print(f" - {item['file']}: {[fn['name'] for fn in item['functions']]}")

if __name__ == "__main__":
    main()
