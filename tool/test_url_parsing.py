#!/usr/bin/env python3
"""
飞书URL解析测试脚本
"""

import re

def test_url_parsing():
    """测试URL解析功能"""
    print("=== 飞书URL解析测试 ===\n")

    test_urls = [
        "https://mi.feishu.cn/wiki/UCyVwffRsiTXgYk9TlHcV2lUn8c",
        "https://mi.feishu.cn/docx/ABC123DEF456",
        "https://mi.feishu.cn/docs/DEF789GHI012",
        "UCyVwffRsiTXgYk9TlHcV2lUn8c",  # 纯ID
    ]

    patterns = [
        r"/(?:docx|wiki|docs)/([A-Za-z0-9]+)",  # 标准文档和wiki
    ]

    for url in test_urls:
        print(f"测试URL: {url}")
        doc_id = None
        for pattern in patterns:
            m = re.search(pattern, url)
            if m:
                doc_id = m.group(1)
                print(f"  ✓ 匹配模式: {pattern}")
                print(f"  ✓ 提取ID: {doc_id}")
                break

        if not doc_id:
            doc_id = url
            print(f"  ⚠ 使用原URL/ID作为文档ID: {doc_id}")

        is_wiki = "/wiki/" in url
        print(f"  ℹ 是否为Wiki: {is_wiki}")
        print()

if __name__ == "__main__":
    test_url_parsing()