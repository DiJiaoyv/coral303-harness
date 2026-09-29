# web_ui.py - Flask Web 界面入口（多用户登录 + 管理后台）
import argparse
import sys

from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    parser = argparse.ArgumentParser(description="Harness Web UI (Flask)")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="启动 Web 服务（默认）")
    run_parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    run_parser.add_argument("--port", type=int, default=7860, help="监听端口")
    run_parser.add_argument("--debug", action="store_true", help="开启调试模式")

    admin_parser = subparsers.add_parser(
        "create-admin",
        help="创建或提升管理员账户（交互式，密码不回显）",
    )
    admin_parser.add_argument("--username", help="管理员用户名（省略则交互输入）")
    admin_parser.add_argument("--password", help="密码（省略则交互输入，不推荐在命令行传递）")

    args = parser.parse_args()

    if args.command == "create-admin":
        from app import create_app
        from app.cli import create_admin_account

        app = create_app()
        with app.app_context():
            create_admin_account(
                username=args.username,
                password=args.password,
            )
        return

    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", 7860)
    debug = getattr(args, "debug", False)

    from app import create_app

    app = create_app()
    print(f"Harness Web UI: http://{host}:{port}")
    print(f"管理后台: http://{host}:{port}/admin/")
    print(f"角色弧光详情: http://{host}:{port}/character/<id>")
    print(f"记忆管理: http://{host}:{port}/memory/manage/<character_id>")
    print(f"创建角色向导: http://{host}:{port}/characters/create")
    print(f"管理后台创建向导: http://{host}:{port}/admin/characters/create")
    print(f"角色记忆: http://{host}:{port}/memory")
    print(f"流式对话 SSE: GET http://{host}:{port}/stream/chat?message=...")
    print(f"取消生成: POST http://{host}:{port}/cancel")
    print("未登录将重定向到 /auth/login")
    print("创建管理员: python web_ui.py create-admin  或  flask --app web_ui:create_flask_app create-admin")
    # threaded=True 以便 SSE 流式响应与取消请求并发
    app.run(host=host, port=port, debug=debug, threaded=True)


def create_flask_app():
    """供 `flask --app web_ui:create_flask_app` 与 gunicorn 使用的应用工厂。

    健康检查: GET /health → {"status": "ok", "version": "1.0.0"}
    （路由在 app.create_app() 中注册，供 Nginx / Docker HEALTHCHECK 探活）
    """
    from app import create_app
    return create_app()


if __name__ == "__main__":
    if len(sys.argv) == 1:
        sys.argv.append("run")
    main()
