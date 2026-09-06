import itertools
from copy import deepcopy


class _DBs:
    def __init__(self, fake):
        self.fake = fake

    def create(self, parent, title, properties):
        db_id = f"db{next(self.fake.seq)}"
        props = {name: {**deepcopy(prop), "id": f"prop{next(self.fake.seq)}"}
                 for name, prop in properties.items()}
        self.fake.dbs[db_id] = {
            "id": db_id, "parent": parent["page_id"],
            "title": title[0]["text"]["content"],
            "properties": props, "pages": {}}
        return {"id": db_id, "properties": props}

    def retrieve(self, database_id):
        d = self.fake.dbs[database_id]
        return {"id": d["id"], "properties": d["properties"]}

    def query(self, database_id, start_cursor=None, page_size=100):
        pages = list(self.fake.dbs[database_id]["pages"].values())
        return {"results": pages, "has_more": False, "next_cursor": None}

    def update(self, database_id, properties):
        props = self.fake.dbs[database_id]["properties"]
        for key, value in properties.items():
            name = next((name for name, prop in props.items()
                         if prop["id"] == key), key)
            props[name].update(deepcopy(value))
        return self.retrieve(database_id)


class _Pages:
    def __init__(self, fake):
        self.fake = fake

    def create(self, parent, properties):
        page_id = f"pg{next(self.fake.seq)}"
        page = {"id": page_id, "properties": properties}
        self.fake.dbs[parent["database_id"]]["pages"][page_id] = page
        return page

    def update(self, page_id, properties):
        for database in self.fake.dbs.values():
            if page_id in database["pages"]:
                database["pages"][page_id]["properties"].update(properties)
                return database["pages"][page_id]
        raise KeyError(page_id)


class _Children:
    def __init__(self, fake):
        self.fake = fake

    def list(self, block_id):
        return {"results": [
            {"id": d["id"], "type": "child_database",
             "child_database": {"title": d["title"]}}
            for d in self.fake.dbs.values() if d["parent"] == block_id]}


class _Blocks:
    def __init__(self, fake):
        self.children = _Children(fake)


class FakeNotionClient:
    def __init__(self):
        self.seq = itertools.count(1)
        self.dbs = {}
        self.databases = _DBs(self)
        self.pages = _Pages(self)
        self.blocks = _Blocks(self)


# --- 노션 응답 형식 헬퍼 (테스트에서 페이지 주입용) ---

def rich(text):
    return {"rich_text": [{"plain_text": text, "text": {"content": text}}]}


def title(text):
    return {"title": [{"plain_text": text, "text": {"content": text}}]}


def select(name):
    return {"select": {"name": name}}


def checkbox(v):
    return {"checkbox": v}


def date(iso):
    return {"date": {"start": iso}}
