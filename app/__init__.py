import os

from flask import Flask

from config import DATABASE_PATH, Config
from database import init_sqlite_schema
from extensions import csrf, db, login_manager
from app.models.user import User


def create_app(config_overrides: dict | None = None) -> Flask:
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = Flask(
        __name__,
        static_folder=os.path.join(project_root, "static"),
        static_url_path="/static",
    )
    app.config.from_object(Config)
    if config_overrides:
        app.config.update(config_overrides)

    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id: str):
        return db.session.get(User, int(user_id))

    db_uri = app.config["SQLALCHEMY_DATABASE_URI"]
    db_path = (
        db_uri.replace("sqlite:///", "", 1)
        if db_uri.startswith("sqlite:///")
        else DATABASE_PATH
    )

    with app.app_context():
        db.create_all()
        if not db_path.endswith(":memory:") and ":memory:" not in db_uri:
            init_sqlite_schema(db_path)
            from database.migrate_admin_schema import migrate_admin_schema
            migrate_admin_schema(db_path)

    from app.routes.auth import auth_bp
    from app.routes.data_routes import data_bp
    from app.routes.memory_routes import memory_bp
    from app.routes.character_wizard_routes import character_wizard_bp
    from admin.blueprint import admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(data_bp)
    app.register_blueprint(memory_bp)
    app.register_blueprint(character_wizard_bp)
    app.register_blueprint(admin_bp)

    from app.cli import init_app as init_cli
    init_cli(app)

    @app.route("/health")
    def health():
        import os
        from flask import jsonify
        return jsonify({
            "status": "ok",
            "version": os.environ.get("HARNESS_VERSION", "1.0.0"),
        })

    @app.errorhandler(404)
    def not_found(_e):
        from flask import jsonify
        return jsonify({"error": "未找到"}), 404

    @app.errorhandler(500)
    def server_error(_e):
        from flask import jsonify
        return jsonify({"error": "服务器内部错误"}), 500

    return app
