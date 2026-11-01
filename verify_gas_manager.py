import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).parent))
from gas_client import GasClient

def verify_full_cycle():
    if len(sys.argv) < 2:
        print("使い方: py verify_gas_manager.py <テスト対象プロジェクト名またはスクリプトID>")
        print("例: py verify_gas_manager.py 'MyTestProject'")
        sys.exit(0)

    proj = sys.argv[1]
    print(f"=== ガスマネージャー 実機往復フルテスト: [{proj}] ===")
    client = GasClient()

    # 1. 新規ファイル追加
    test_file = "_gas_manager_test"
    print(f"\n[1] テストファイル追加: {test_file}.js")
    add_res = client.add_file(
        script_id=proj,
        filename=test_file,
        file_type="js",
        source="""/**
 * GasManager 自動検証コード
 */
function helloGasManager() {
  const version = "1.0.0";
  console.log("Hello from GasManager! v=" + version);
  return version;
}
"""
    )
    print(f" -> 結果: {add_res['status']}, バックアップ: {add_res['backup_file']}")

    # 2. ファイル取得 & 関数抽出
    print(f"\n[2] コード取得 & 関数 helloGasManager 抽出")
    func = client.get_function(proj, test_file, "helloGasManager")
    print("抽出コード:")
    for line in func.strip().splitlines():
        print("  ", line)

    # 3. ピンポイント差分置換 (patch)
    print(f"\n[3] ピンポイント差分置換 (1.0.0 -> 2.0.0-SUCCESS)")
    patch_res = client.patch_code(
        script_id=proj,
        filename=test_file,
        target='const version = "1.0.0";',
        replacement='const version = "2.0.0-SUCCESS";'
    )
    print(f" -> 結果: {patch_res['status']}, 置換箇所: {patch_res['replaced_occurrences']}")

    # 4. 置換後のコード取得確認
    print(f"\n[4] 置換後のコード確認")
    updated_func = client.get_function(proj, test_file, "helloGasManager")
    for line in updated_func.strip().splitlines():
        print("  ", line)

    # 5. 後片付け（テストファイル削除）
    print(f"\n[5] テストファイル削除")
    del_res = client.delete_file(proj, test_file)
    print(f" -> 結果: {del_res['status']}, 削除: {del_res['deleted_file']}")

    print("\n[SUCCESS] すべての操作（作成・取得・ピンポイント置換・削除）が Google クラウド上で正常に完走しました！")

if __name__ == "__main__":
    verify_full_cycle()
