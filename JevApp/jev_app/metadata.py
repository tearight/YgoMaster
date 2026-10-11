import json
import struct
from pathlib import Path


def strings_by_offset(raw):
    result, offset = {}, 0
    while offset < len(raw):
        end = raw.find(b"\0", offset)
        if end == -1:
            raise ValueError("unterminated_string")
        result[offset] = raw[offset:end].decode("utf-8")
        offset = end + 1
    return result


class CardCatalog:
    def __init__(self, cards=None):
        self.cards = cards or {}

    @classmethod
    def from_game(cls, root, language="en-US"):
        root = Path(root)
        return cls.from_files(root / language / "CARD_Indx.bytes", root / language / "CARD_Name.bytes",
                              root / language / "CARD_Desc.bytes", root / "#" / "CARD_Prop.bytes")

    @classmethod
    def from_files(cls, index_path, name_path, desc_path, prop_path):
        index, prop = Path(index_path).read_bytes(), Path(prop_path).read_bytes()
        if len(index) < 8 or len(index) % 8 or len(prop) < len(index) - 8:
            raise ValueError("invalid_card_index")
        names, descriptions = strings_by_offset(Path(name_path).read_bytes()), strings_by_offset(Path(desc_path).read_bytes())
        cards = {}
        # Upstream's final index pair is a sentinel, not a card.
        for i in range(len(index) // 8 - 1):
            name, desc = struct.unpack_from("<II", index, i * 8)
            prop_a, prop_b = struct.unpack_from("<II", prop, i * 8)
            card_id = prop_a & 0xFFFF
            if name not in names or desc not in descriptions:
                raise ValueError("invalid_card_offset")
            if card_id:
                if card_id in cards:
                    raise ValueError("duplicate_card_id")
                cards[card_id] = {"name": names[name], "description": descriptions[desc]}
        return cls(cards)

    def get(self, card_id):
        return self.cards.get(card_id)


class TextCatalog:
    def __init__(self, texts=None):
        self.texts = texts or {}

    @classmethod
    def from_json(cls, path):
        # Only verified ID -> text exports; do not assume DLG offsets equal engine IDs.
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict) or any(not isinstance(v, str) for group in data.values() for v in group.values()):
            raise ValueError("invalid_text_catalog")
        return cls(data)

    def resolve(self, group, string_id):
        return self.texts.get(group, {}).get(str(string_id))
