import sys
path = sys.argv[1]
text = open(path, encoding="utf-8").read()
parts = text.split("<node ")
print("nodes", len(parts) - 1)
for part in parts[1:]:
    def grab(key):
        token = key + '="'
        start = part.find(token)
        if start < 0:
            return ""
        end = part.find('"', start + len(token))
        return part[start + len(token):end]
    cls = grab("class").split(".")[-1]
    rid = grab("resource-id")
    tx = grab("text")
    cd = grab("content-desc")
    bounds = grab("bounds")
    if rid or tx or cd or "Edit" in cls or "Button" in cls:
        print(cls, rid, tx[:50], cd[:50], bounds)
