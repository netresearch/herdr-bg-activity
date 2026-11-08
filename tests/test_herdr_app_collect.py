"""Tests for herdr-app/mods/agents-bg/collect.py, the Herdr app mod's collector."""

import importlib.util
import json
import unittest
from pathlib import Path
from typing import ClassVar
from unittest import mock

COLLECT = (
    Path(__file__).resolve().parent.parent
    / "herdr-app"
    / "mods"
    / "agents-bg"
    / "collect.py"
)
spec = importlib.util.spec_from_file_location("collect", COLLECT)
collect = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collect)

RULE = "─" * 60


class FooterTest(unittest.TestCase):
    def test_background_work_below_the_last_rule(self):
        lines = [
            "● 1 monitor still running",  # transcript text: not counted
            RULE,
            "❯",
            RULE,
            "  ⏵⏵ bypass permissions on · 1 shell, 2 monitors · ← 3 agents",
        ]
        screen = "\n".join(lines)
        counts = collect.background_counts(collect.footer(screen))
        self.assertEqual(counts, {"shell": 1, "monitor": 2})
        self.assertEqual(collect.describe(counts), "⧗ 2 monitors, 1 shell")

    def test_no_rule_no_footer(self):
        self.assertEqual(collect.footer("just text\n1 monitor"), [])

    def test_model_abbrev(self):
        self.assertEqual(collect.model_abbrev("claude-opus-5-5[1m]"), "O55")
        self.assertIsNone(collect.model_abbrev("claude-3-opus"))


def ss_line(addr, name, pid):
    return f'LISTEN 0 5 {addr} 0.0.0.0:* users:(("{name}",pid={pid},fd=3))'


class ProcessLinksTest(unittest.TestCase):
    """Process tree: 10 bash (terminal t3) -> 20 claude -> 30 bash -> 40 server,
    and claude -> 50 uv -> 60 python (an MCP server)."""

    TREE: ClassVar[dict] = {
        40: ("python3", 30),
        30: ("bash", 20),
        20: ("claude", 10),
        10: ("bash", 1),
        60: ("python", 50),
        50: ("uv", 20),
        70: ("go", 1),  # started outside any terminal
    }

    def links(self, ss_output):
        with (
            mock.patch.object(collect, "run_json_lines", return_value=ss_output),
            mock.patch.object(collect, "proc_stat", side_effect=self.TREE.get),
            mock.patch.object(collect, "git_toplevel", return_value="/p/app"),
            mock.patch.object(collect.os, "readlink", return_value="/p/app/sub"),
        ):
            return collect.process_links({10: "t3"}, {20: "t3"})

    def test_server_started_through_the_agents_shell_belongs_to_it(self):
        links = self.links(ss_line("127.0.0.1:5175", "python3", 40))
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["terminal"], "t3")
        self.assertEqual(links[0]["port"], 5175)
        self.assertTrue(links[0]["loopback"])
        self.assertEqual(links[0]["root"], "/p/app")

    def test_mcp_server_of_the_agent_is_left_out(self):
        self.assertEqual(self.links(ss_line("127.0.0.1:24282", "python", 60)), [])

    def test_unrelated_process_has_no_terminal_but_a_root(self):
        links = self.links(ss_line("0.0.0.0:8080", "go", 70))
        self.assertIsNone(links[0]["terminal"])
        self.assertFalse(links[0]["loopback"])

    def test_ephemeral_and_foreign_addresses_are_left_out(self):
        out = "\n".join(
            [
                ss_line("127.0.0.1:40000", "python3", 40),
                ss_line("10.255.255.254:53", "python3", 40),
            ]
        )
        self.assertEqual(self.links(out), [])


class DockerAndDdevTest(unittest.TestCase):
    def test_published_ports_by_compose_folder_and_ddev_skipped(self):
        boxes = [
            {
                "Names": "app-web-1",
                "Ports": "0.0.0.0:8080->80/tcp, [::]:8080->80/tcp, 5432/tcp",
                "Labels": "com.docker.compose.service=web,"
                "com.docker.compose.project.working_dir=/p/app",
            },
            {
                "Names": "ddev-router",
                "Ports": "127.0.0.1:80->80/tcp",
                "Labels": "com.ddev.platform=ddev",
            },
        ]
        out = "\n".join(json.dumps(b) for b in boxes)
        with mock.patch.object(collect, "run_json_lines", return_value=out):
            links = collect.docker_links()
        self.assertEqual(
            links,
            [
                {
                    "kind": "docker",
                    "port": 8080,
                    "loopback": False,
                    "label": "web",
                    "cwd": "/p/app",
                }
            ],
        )

    def test_running_ddev_projects_only(self):
        out = json.dumps(
            {
                "raw": [
                    {
                        "name": "shop",
                        "status": "running",
                        "primary_url": "https://shop.ddev.site",
                        "approot": "/p/shop",
                    },
                    {
                        "name": "old",
                        "status": "stopped",
                        "primary_url": "https://old.ddev.site",
                        "approot": "/p/old",
                    },
                ]
            }
        )
        with mock.patch.object(collect, "run_json_lines", return_value=out):
            links = collect.ddev_links()
        self.assertEqual([link["label"] for link in links], ["shop"])
        self.assertEqual(links[0]["url"], "https://shop.ddev.site")


if __name__ == "__main__":
    unittest.main()
