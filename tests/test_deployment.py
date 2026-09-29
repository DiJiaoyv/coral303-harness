import os
import unittest

# 在导入应用模块前设置，避免本机 .env 干扰测试
os.environ["SECRET_KEY"] = "test-secret-key-for-deployment-tests"
os.environ["CORS_ORIGINS"] = "http://localhost:3000"

from app import create_app


class DeploymentHealthTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
        })
        self.client = self.app.test_client()

    def test_health_endpoint(self):
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("version", data)

    def test_unauthenticated_admin_redirects(self):
        res = self.client.get("/admin/", follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        self.assertIn("/auth/login", res.headers.get("Location", ""))

    def test_debug_disabled_in_production_config(self):
        self.assertNotEqual(self.app.config.get("DEBUG"), True)


class DeploymentFilesTest(unittest.TestCase):
    BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_docker_files_exist(self):
        for name in (
            "Dockerfile",
            "docker-compose.yml",
            ".env.example",
            ".dockerignore",
            "DEPLOYMENT.md",
            "deploy/entrypoint.sh",
            "deploy/healthcheck.py",
            "deploy/nginx.conf",
            "deploy/nginx.http.conf",
        ):
            self.assertTrue(
                os.path.isfile(os.path.join(self.BASE, name)),
                f"缺少文件: {name}",
            )

    def test_env_example_no_real_secrets(self):
        path = os.path.join(self.BASE, ".env.example")
        with open(path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("SECRET_KEY=", content)
        self.assertIn("your-secret-key-here", content)
        self.assertNotIn("Admin123456", content)

    def test_dockerignore_excludes_env(self):
        path = os.path.join(self.BASE, ".dockerignore")
        with open(path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn(".env", content)


class HealthcheckScriptTest(unittest.TestCase):
    def test_healthcheck_script_exists(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "deploy",
            "healthcheck.py",
        )
        self.assertTrue(os.path.isfile(path))


if __name__ == "__main__":
    unittest.main()
