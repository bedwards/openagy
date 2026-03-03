"""Tests for probe_antigravity.py."""
import subprocess
import unittest
from unittest.mock import MagicMock, patch

import probe_antigravity as probe


class TestProbeCli(unittest.TestCase):
    """Tests for probe_cli function."""

    @patch("probe_antigravity.subprocess.run")
    def test_chat_help_with_modes(self, mock_run):
        """Detects modes in chat help output."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Usage: chat -m [ask|edit|agent]\n",
            stderr="",
        )
        results = probe.probe_cli()
        self.assertTrue(
            results["chat_help"]["has_modes"]
        )

    @patch("probe_antigravity.subprocess.run")
    def test_chat_help_timeout(self, mock_run):
        """Handles timeout gracefully."""
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd="antigravity", timeout=10,
        )
        results = probe.probe_cli()
        self.assertEqual(
            results["chat_help"]["error"], "timeout"
        )

    @patch("probe_antigravity.subprocess.run")
    def test_chat_help_not_found(self, mock_run):
        """Handles missing binary gracefully."""
        mock_run.side_effect = FileNotFoundError()
        results = probe.probe_cli()
        self.assertEqual(
            results["chat_help"]["error"], "not found"
        )

    @patch("probe_antigravity.subprocess.run")
    def test_version_extraction(self, mock_run):
        """Extracts version string."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="antigravity/1.107.0\n",
            stderr="",
        )
        results = probe.probe_cli()
        self.assertEqual(
            results["version"], "antigravity/1.107.0"
        )


class TestProbePorts(unittest.TestCase):
    """Tests for probe_ports function."""

    @patch("probe_antigravity.subprocess.run")
    def test_finds_ports(self, mock_run):
        """Extracts ports from lsof output."""
        lsof_output = (
            "Antigravi 123 LISTEN *:53704\n"
            "Antigravi 124 LISTEN *:53705\n"
        )
        mock_run.return_value = MagicMock(
            stdout=lsof_output,
        )
        results = probe.probe_ports()
        self.assertIn(53704, results["listening_ports"])
        self.assertIn(53705, results["listening_ports"])

    @patch("probe_antigravity.subprocess.run")
    def test_no_ports(self, mock_run):
        """Returns empty list when no ports found."""
        mock_run.return_value = MagicMock(stdout="")
        results = probe.probe_ports()
        self.assertEqual(results["listening_ports"], [])

    @patch("probe_antigravity.subprocess.run")
    def test_timeout_handling(self, mock_run):
        """Handles timeout gracefully."""
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd="lsof", timeout=10,
        )
        results = probe.probe_ports()
        self.assertEqual(results["listening_ports"], [])


class TestProbeExtensionServers(unittest.TestCase):
    """Tests for probe_extension_servers function."""

    @patch("probe_antigravity.subprocess.run")
    def test_finds_servers(self, mock_run):
        """Extracts server info from ps output."""
        ps_line = (
            "user 1 language_server_macos_x64"
            " --extension_server_port 53704"
            " --csrf_token abc123"
            " --extension_server_csrf_token def456"
            " --workspace_id ws1"
            " --cloud_code_endpoint https://gcp.com"
        )
        mock_run.return_value = MagicMock(
            stdout=ps_line + "\n",
        )
        servers = probe.probe_extension_servers()
        self.assertEqual(len(servers), 1)
        self.assertEqual(
            servers[0]["extension_server_port"], "53704"
        )
        self.assertEqual(
            servers[0]["workspace_id"], "ws1"
        )

    @patch("probe_antigravity.subprocess.run")
    def test_csrf_tokens_redacted(self, mock_run):
        """CSRF tokens are redacted in output."""
        ps_line = (
            "user 1 language_server_macos_x64"
            " --extension_server_port 53704"
            " --csrf_token secret123"
            " --extension_server_csrf_token secret456"
            " --workspace_id ws1"
        )
        mock_run.return_value = MagicMock(
            stdout=ps_line + "\n",
        )
        servers = probe.probe_extension_servers()
        self.assertEqual(
            servers[0]["csrf_token"], "[REDACTED]"
        )
        self.assertEqual(
            servers[0]["extension_csrf_token"],
            "[REDACTED]",
        )

    @patch("probe_antigravity.subprocess.run")
    def test_no_servers(self, mock_run):
        """Returns empty list when no servers."""
        mock_run.return_value = MagicMock(
            stdout="python3 some_other_process\n",
        )
        servers = probe.probe_extension_servers()
        self.assertEqual(servers, [])

    @patch("probe_antigravity.subprocess.run")
    def test_timeout_returns_empty(self, mock_run):
        """Returns empty on timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd="ps", timeout=5,
        )
        servers = probe.probe_extension_servers()
        self.assertEqual(servers, [])


class TestProbeSummary(unittest.TestCase):
    """Tests for probe_summary function."""

    def test_summary_with_modes(self):
        """Summary recommends CLI when modes found."""
        cli = {
            "chat_help": {"has_modes": True},
            "version": "1.107.0",
        }
        ports = {"listening_ports": [53704]}
        servers = [{"port": "53704"}]
        summary = probe.probe_summary(
            cli, ports, servers,
        )
        self.assertIn("CLI", summary)
        self.assertIn("RECOMMENDED", summary)

    def test_summary_without_modes(self):
        """Summary still generates when no modes."""
        cli = {"chat_help": {}, "version": "unknown"}
        ports = {"listening_ports": []}
        summary = probe.probe_summary(cli, ports, [])
        self.assertIn("NO", summary)


if __name__ == "__main__":
    unittest.main()
