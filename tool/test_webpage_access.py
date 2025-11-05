#!/usr/bin/env python3
"""
测试飞书文档网页抓取
"""

import requests

def test_webpage_access():
    """测试网页抓取方式访问飞书文档"""
    print("=== 测试网页抓取访问飞书文档 ===\n")

    test_url = "https://mi.feishu.cn/docx/C2WOdnFb0ovAl2x2q5hcjlNhnLe"
    print(f"测试URL: {test_url}")

    try:
        # 直接使用requests进行网页抓取
        r = requests.get(test_url, timeout=10, headers={"User-Agent": "TestCaseGenBot/1.0"})
        print(f"HTTP状态码: {r.status_code}")
        print(f"响应头: {dict(r.headers)}")
        
        if r.status_code != 200:
            print(f"❌ HTTP错误: {r.status_code}")
            print(f"响应内容预览: {r.text[:500]}")
            return
        
        text = r.text
        print(f"原始内容长度: {len(text)}")
        
        # 简单去标签
        import re
        text = re.sub(r"<script[\s\S]*?</script>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "\n", text)
        text = re.sub(r"\n{2,}", "\n", text)
        text = text.strip()
        
        print(f"处理后内容长度: {len(text)}")
        print(f"内容预览: {text[:500]}...")
        
        if len(text) < 120:
            print("❌ 内容过短，可能是需要登录或文档不存在")
        else:
            print("✅ 网页抓取成功！")

    except Exception as e:
        print(f"❌ 异常: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_webpage_access()