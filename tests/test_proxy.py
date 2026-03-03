"""Tests for antigravity_proxy.py."""
import json
import subprocess
import unittest
from http.server import HTTPServer
from threading import Thread
from unittest.mock import MagicMock, patch

# Import the proxy module
import antigravity_proxy as proxy


class TestCallAntigravityCli(unittest.TestCase):
    """Tests for call_antigravity_cli function."""

    @patch("antigravity_proxy.subprocess.run")
    def test_successful_response(self, mock_run):
        """CLI returns stdout on success."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Hello from Claude\n",
            stderr="",
        )
        result = proxy.call_antigravity_cli("Hi")
        self.assertEqual(result, "Hello from Claude")

    @patch("antigravity_proxy.subprocess.run")
    def test_cli_stderr_error(self, mock_run):
        """CLI returns error message on stderr."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Connection failed\n",
        )
        result = proxy.call_antigravity_cli("Hi")
        self.assertTrue(result.startswith("Error:"))
        self.assertIn("Connection failed", result)

    @patch("antigravity_proxy.subprocess.run")
    def test_cli_no_output(self, mock_run):
        """CLI returns error when no output."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr="",
        )
        result = proxy.call_antigravity_cli("Hi")
        self.assertTrue(result.startswith("Error:"))

    @patch("antigravity_proxy.subprocess.run")
    def test_cli_timeout(self, mock_run):
        """CLI returns error on timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd="antigravity", timeout=120,
        )
        result = proxy.call_antigravity_cli("Hi")
        self.assertTrue(result.startswith("Error:"))
        self.assertIn("timed out", result)

    @patch("antigravity_proxy.subprocess.run")
    def test_cli_not_found(self, mock_run):
        """CLI returns error when binary missing."""
        mock_run.side_effect = FileNotFoundError()
        result = proxy.call_antigravity_cli("Hi")
        self.assertTrue(result.startswith("Error:"))

    @patch("antigravity_proxy.subprocess.run")
    def test_cli_os_error(self, mock_run):
        """CLI returns error on OS error."""
        mock_run.side_effect = OSError("Permission denied")
        result = proxy.call_antigravity_cli("Hi")
        self.assertTrue(result.startswith("Error:"))
        self.assertIn("Permission denied", result)


class TestFindExtensionServers(unittest.TestCase):
    """Tests for find_extension_servers function."""

    @patch("antigravity_proxy.subprocess.run")
    def test_finds_servers(self, mock_run):
        """Extracts server info from ps output."""
        ps_output = (
            "user  123 language_server_macos_x64"
            " --extension_server_port 53704"
            " --csrf_token abc123"
            " --extension_server_csrf_token def456"
            " --workspace_id ws1\n"
        )
        mock_run.return_value = MagicMock(
            stdout=ps_output,
        )
        servers = proxy.find_extension_servers()
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]["port"], "53704")
        self.assertEqual(servers[0]["workspace"], "ws1")

    @patch("antigravity_proxy.subprocess.run")
    def test_no_servers(self, mock_run):
        """Returns empty list when no servers."""
        mock_run.return_value = MagicMock(stdout="")
        servers = proxy.find_extension_servers()
        self.assertEqual(servers, [])

    @patch("antigravity_proxy.subprocess.run")
    def test_timeout_returns_empty(self, mock_run):
        """Returns empty list on timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd="ps", timeout=5,
        )
        servers = proxy.find_extension_servers()
        self.assertEqual(servers, [])


class TestMessagesToPrompt(unittest.TestCase):
    """Tests for _messages_to_prompt method."""

    def setUp(self):
        """Create a proxy handler instance."""
        self.handler = proxy.AntigravityProxy.__new__(
            proxy.AntigravityProxy
        )

    def test_user_message(self):
        """Converts user message correctly."""
        messages = [{"role": "user", "content": "Hello"}]
        result = self.handler._messages_to_prompt(messages)
        self.assertEqual(result, "Hello")

    def test_system_message(self):
        """Wraps system message in brackets."""
        messages = [
            {"role": "system", "content": "Be helpful"},
        ]
        result = self.handler._messages_to_prompt(messages)
        self.assertIn("[System instruction:", result)
        self.assertIn("Be helpful", result)

    def test_assistant_message(self):
        """Wraps assistant message in brackets."""
        messages = [
            {"role": "assistant", "content": "Sure"},
        ]
        result = self.handler._messages_to_prompt(messages)
        self.assertIn("[Previous response:", result)

    def test_multimodal_content(self):
        """Extracts text from multimodal content."""
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": "Hello"},
                {"type": "image_url", "url": "..."},
                {"type": "text", "text": "World"},
            ],
        }]
        result = self.handler._messages_to_prompt(messages)
        self.assertIn("Hello", result)
        self.assertIn("World", result)

    def test_multi_turn(self):
        """Handles multi-turn conversation."""
        messages = [
            {"role": "system", "content": "Be brief"},
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
            {"role": "user", "content": "How are you?"},
        ]
        result = self.handler._messages_to_prompt(messages)
        self.assertIn("Be brief", result)
        self.assertIn("Hi", result)
        self.assertIn("Hello", result)
        self.assertIn("How are you?", result)


class TestProxyEndpoints(unittest.TestCase):
    """Integration tests for proxy HTTP endpoints."""

    @classmethod
    def setUpClass(cls):
        """Start proxy server on a test port."""
        cls.port = 18462
        cls.server = HTTPServer(
            ("localhost", cls.port),
            proxy.AntigravityProxy,
        )
        cls.thread = Thread(
            target=cls.server.serve_forever,
            daemon=True,
        )
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        """Shut down the test server."""
        cls.server.shutdown()

    def _get(self, path: str) -> dict:
        """Make a GET request to the test server."""
        import urllib.request
        url = f"http://localhost:{self.port}{path}"
        with urllib.request.urlopen(url) as resp:
            return json.loads(resp.read())

    def _post(self, path: str, data: dict) -> tuple:
        """Make a POST request to the test server.

        Returns:
            Tuple of (status_code, response_dict).
        """
        import urllib.request
        import urllib.error
        url = f"http://localhost:{self.port}{path}"
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return (
                    resp.status,
                    json.loads(resp.read()),
                )
        except urllib.error.HTTPError as e:
            return (
                e.code,
                json.loads(e.read()),
            )

    def test_root_endpoint(self):
        """Root returns server info."""
        data = self._get("/")
        self.assertEqual(data["name"], "Antigravity Proxy")
        self.assertIn("/v1/models", data["endpoints"])
        self.assertIn("/health", data["endpoints"])

    def test_models_endpoint(self):
        """Models returns model list."""
        data = self._get("/v1/models")
        self.assertEqual(data["object"], "list")
        self.assertEqual(len(data["data"]), 1)
        model = data["data"][0]
        self.assertEqual(model["id"], "claude-opus-4-6")
        self.assertEqual(model["object"], "model")

    @patch("antigravity_proxy.find_extension_servers")
    def test_health_endpoint(self, mock_find):
        """Health returns status info."""
        mock_find.return_value = [{"port": "123"}]
        data = self._get("/health")
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["model"], "claude-opus-4-6")

    def test_post_missing_messages(self):
        """POST with empty messages returns 400."""
        status, data = self._post(
            "/v1/chat/completions",
            {"messages": []},
        )
        self.assertEqual(status, 400)

    def test_post_invalid_json(self):
        """POST with invalid body returns 400."""
        import urllib.request
        import urllib.error
        url = (
            f"http://localhost:{self.port}"
            "/v1/chat/completions"
        )
        req = urllib.request.Request(
            url, data=b"not json",
            headers={
                "Content-Type": "application/json",
            },
        )
        try:
            urllib.request.urlopen(req)
            self.fail("Expected HTTPError")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)

    @patch("antigravity_proxy.call_backend")
    def test_post_sync_success(self, mock_cli):
        """POST returns successful completion."""
        mock_cli.return_value = "Test response"
        status, data = self._post(
            "/v1/chat/completions",
            {"messages": [
                {"role": "user", "content": "Hi"},
            ]},
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            data["object"], "chat.completion"
        )
        content = data["choices"][0]["message"]["content"]
        self.assertEqual(content, "Test response")

    @patch("antigravity_proxy.call_backend")
    def test_post_cli_error_returns_502(self, mock_cli):
        """POST returns 502 when CLI fails."""
        mock_cli.return_value = "Error: CLI crashed"
        status, data = self._post(
            "/v1/chat/completions",
            {"messages": [
                {"role": "user", "content": "Hi"},
            ]},
        )
        self.assertEqual(status, 502)
        self.assertIn("error", data)

    def test_404_on_unknown_path(self):
        """Unknown path returns 404."""
        import urllib.request
        import urllib.error
        url = f"http://localhost:{self.port}/v1/unknown"
        req = urllib.request.Request(url)
        try:
            urllib.request.urlopen(req)
            self.fail("Expected 404")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)


if __name__ == "__main__":
    unittest.main()
