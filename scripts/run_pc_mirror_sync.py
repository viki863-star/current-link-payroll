from __future__ import annotations

from app import create_app
from app.backup_service import sync_pc_mirror_copy


def main() -> int:
    app = create_app()
    with app.app_context():
        result = sync_pc_mirror_copy(app)
    print(result["message"])
    if result.get("log_path"):
        print(f"Log: {result['log_path']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
