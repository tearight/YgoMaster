import argparse
from .app import DecisionApp
from .bridge import BridgeClient
from .metadata import CardCatalog, TextCatalog
from .provider import JevProvider, MockProvider


def main():
    parser = argparse.ArgumentParser(description="YgoMaster 외부 Jev 결정 앱")
    parser.add_argument("--bridge-config", required=True)
    parser.add_argument("--provider", choices=("human", "mock", "jev"), default="human")
    parser.add_argument("--human-endpoint", default="http://127.0.0.1:49173/v1/systemone")
    parser.add_argument("--card-data", help="추출된 CardData 폴더")
    parser.add_argument("--language", default="en-US")
    parser.add_argument("--text-catalog", help="확인된 문자열 ID -> 문구 JSON")
    args = parser.parse_args()
    cards = CardCatalog.from_game(args.card_data, args.language) if args.card_data else CardCatalog()
    texts = (TextCatalog.from_json(args.text_catalog) if args.text_catalog else
             TextCatalog.from_game(args.card_data, args.language) if args.card_data else TextCatalog())
    provider = (MockProvider() if args.provider == "mock" else
                JevProvider(endpoint=args.human_endpoint, human=True) if args.provider == "human" else JevProvider())
    try:
        DecisionApp(BridgeClient(args.bridge_config), provider, cards, texts).run()
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
