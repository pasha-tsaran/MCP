"""Live comparison through the same MCP process as Telegram, without a bot token."""
import argparse
import asyncio
import json
import sys
from bot.mcp_client import open_mcp


async def run(product_id):
    async with open_mcp() as client:
        result = await client.call('compare_competitors', {'product_id': product_id})
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get('offers') else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Проверка реальных цен конкурентов через MCP')
    parser.add_argument('--product-id', type=int, default=18)
    args = parser.parse_args()
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(asyncio.run(run(args.product_id)))
