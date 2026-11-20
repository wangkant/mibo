"""How well find_tools finds the right MCP tool: the app's own search over the tool lists of ten real servers
(tools.json, listed from the servers themselves), with the queries a model passes on from a person's message.

    python tools/mcp_find/check.py                  word matching only (no model)
    python tools/mcp_find/check.py --env <.env>     the model in that .env writes each tool's search words first,
                                                    as the app does when a server connects (kept in words.json
                                                    beside this file, so a rerun costs nothing)

Prints the share of queries whose tool is among the five find_tools returns, for Chinese and English queries,
and the Chinese ones it missed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from persona_agent import mcp_hub, mcp_tools as mt  # noqa: E402

# A query and the tools that answer it ("server/tool").
ZH = [
    ("现在几点", "time/get_current_time"),
    ("东京现在几点", "time/get_current_time"),
    ("把北京时间换算成纽约时间", "time/convert_time"),
    ("三天前是几号", "time/get_time_ago"),
    ("打开这个网址看看内容", "fetch/fetch playwright/browser_navigate"),
    ("把网页转成markdown", "fetch/fetch microsoft-learn/microsoft_docs_fetch"),
    ("读取文件内容", "filesystem/read_text_file filesystem/read_file"),
    ("写入文件", "filesystem/write_file"),
    ("新建文件夹", "filesystem/create_directory"),
    ("列出目录里的文件", "filesystem/list_directory filesystem/list_directory_with_sizes filesystem/directory_tree"),
    ("重命名文件", "filesystem/move_file"),
    ("复制文件", "filesystem/copy_file"),
    ("按文件名搜索文件", "filesystem/search_files"),
    ("查看文件大小和修改时间", "filesystem/get_file_info filesystem/list_directory_with_sizes"),
    ("看看这张图片文件", "filesystem/read_media_file"),
    ("追加内容到文件末尾", "filesystem/append_file"),
    ("修改文件中的几行", "filesystem/edit_file"),
    ("同时读取多个文件", "filesystem/read_multiple_files"),
    ("能访问哪些文件夹", "filesystem/list_allowed_directories"),
    ("记住我喜欢喝咖啡", "memory/create_entities memory/add_observations"),
    ("我之前跟你说过什么", "memory/search_nodes memory/read_graph memory/open_nodes"),
    ("删除关于我的记忆", "memory/delete_entities memory/delete_observations"),
    ("记下小明是我的同事", "memory/create_relations memory/create_entities"),
    ("查一下明天北京到上海的火车票", "12306/get-tickets"),
    ("需要中转的车票", "12306/get-interline-tickets"),
    ("G1次列车经停哪些站", "12306/get-train-route-stations"),
    ("上海有哪些火车站", "12306/get-stations-code-in-city"),
    ("今天几号", "12306/get-current-date time/get_current_time"),
    ("网页截图", "playwright/browser_take_screenshot"),
    ("在网页上点击按钮", "playwright/browser_click"),
    ("填写网页表单", "playwright/browser_fill_form playwright/browser_type"),
    ("在浏览器里打开网页", "playwright/browser_navigate"),
    ("关闭浏览器", "playwright/browser_close"),
    ("上传文件到网页", "playwright/browser_file_upload"),
    ("返回上一页", "playwright/browser_navigate_back"),
    ("切换标签页", "playwright/browser_tabs"),
    ("下拉框选择选项", "playwright/browser_select_option"),
    ("鼠标悬停", "playwright/browser_hover"),
    ("拖拽元素", "playwright/browser_drag playwright/browser_drop"),
    ("按回车键", "playwright/browser_press_key"),
    ("等待页面出现文字", "playwright/browser_wait_for"),
    ("在页面上执行JavaScript", "playwright/browser_evaluate playwright/browser_run_code_unsafe"),
    ("调整浏览器窗口大小", "playwright/browser_resize"),
    ("看看网页的网络请求", "playwright/browser_network_requests"),
    ("网页控制台报错", "playwright/browser_console_messages"),
    ("切换深色模式", "playwright/browser_emulate_media"),
    ("这个GitHub仓库的代码是怎么组织的", "deepwiki/ask_wiki_question deepwiki/read_wiki_structure"),
    ("查微软官方文档", "microsoft-learn/microsoft_docs_search"),
    ("找一段Azure的示例代码", "microsoft-learn/microsoft_code_sample_search"),
    ("画一张流程图", "drawio/create_diagram drawio/create_semantic_diagram"),
    ("快速画个草图", "drawio/create_semantic_diagram drawio/create_diagram"),
    ("两个数相加", "everything/get-sum"),
    ("压缩文件", "everything/gzip-file-as-resource"),
    ("查看环境变量", "everything/get-env"),
]
EN = [
    ("current time", "time/get_current_time"),
    ("convert time zone", "time/convert_time"),
    ("fetch a web page", "fetch/fetch playwright/browser_navigate"),
    ("read a file", "filesystem/read_text_file filesystem/read_file"),
    ("make a folder", "filesystem/create_directory"),
    ("rename a file", "filesystem/move_file"),
    ("remember a fact about me", "memory/create_entities memory/add_observations"),
    ("train tickets", "12306/get-tickets"),
    ("screenshot of the page", "playwright/browser_take_screenshot"),
    ("click a button", "playwright/browser_click"),
    ("go back", "playwright/browser_navigate_back"),
    ("explain a github repository", "deepwiki/ask_wiki_question deepwiki/read_wiki_structure"),
    ("microsoft documentation", "microsoft-learn/microsoft_docs_search"),
    ("draw a flowchart", "drawio/create_diagram drawio/create_semantic_diagram"),
    ("add two numbers", "everything/get-sum"),
]


class _Workspace:
    def __init__(self, home: Path) -> None:
        self.home = home


def hub_for(home: Path) -> mcp_hub.Hub:
    """A hub whose servers are all connected with the listed tools."""
    hub = mcp_hub.Hub(_Workspace(home))
    for server, tools in json.loads((HERE / "tools.json").read_text(encoding="utf-8")).items():
        runner = mcp_hub.Runner(server, {"url": "https://example.invalid/" + server})
        runner.state, runner.tools = "connected", mt.clean_tools(tools)
        hub.runners[server] = runner
    return hub


def recall(hub: mcp_hub.Hub, rows: list) -> tuple[float, list]:
    missed = []
    for query, wanted in rows:
        got = [f"{t['server']}/{t['tool']}" for t in hub.find(query)["tools"]]
        if not set(wanted.split()) & set(got):
            missed.append((query, wanted, got[:3]))
    return 1 - len(missed) / len(rows), missed


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", help="a .env whose model writes the search words")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as folder:
        home = Path(folder)
        hub = hub_for(home)
        kept = HERE / "words.json"
        if args.env:
            values = {}
            for line in Path(args.env).read_text(encoding="utf-8").splitlines():
                key, sep, value = line.partition("=")
                if sep and not line.lstrip().startswith("#"):
                    values[key.strip()] = value.strip().strip('"')
            if kept.exists():
                mt.keep_words(home, json.loads(kept.read_text(encoding="utf-8")))
            for runner in hub.runners.values():
                asyncio.run(mt.write_words(home, values, runner.tools))
            kept.write_text(json.dumps(mt.kept_words(home), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        zh, missed = recall(hub, ZH)
        en, _ = recall(hub, EN)
    print(f"tools {sum(len(r.tools) for r in hub.runners.values())}, words {'model' if args.env else 'none'}")
    print(f"found in the top five: zh {zh:.0%} of {len(ZH)}, en {en:.0%} of {len(EN)}")
    for query, wanted, got in missed:
        print(f"  missed {query}: wanted {wanted}, got {', '.join(got) or 'nothing'}")


if __name__ == "__main__":
    main()
