import sys, json
sys.path.insert(0, 'src')
from coze_skills.core.registry import build_default_registry

r = build_default_registry()
cc = r.require('check_compliance').handler
dr = r.require('draft_reply').handler
ar = r.require('analyze_reviews').handler

print("=== Sample 1: check_compliance ===")
res = cc(text="全网第一！治疗脱发神器，7天见效，100%有效", platform="xhs")
d = res.data
print("ok:", res.ok, "risk_level:", d["risk_level"], "hit_count:", d["hit_count"])
words = sorted({h["word"] for h in d["hits"]})
print("hit words:", words)
print("rewritten_text:", repr(d["rewritten_text"]))
for must in ["全网第一", "治疗", "脱发", "100%"]:
    print(f"  contains {must!r}:", must in d["rewritten_text"])
print("hits detail:")
print(json.dumps(d["hits"], ensure_ascii=False, indent=2))

print("\n=== Sample 2: analyze_reviews (5 EN bad reviews) ===")
reviews = [
    "The delivery was very late and it arrived damaged",
    "box broken on arrival, terrible quality",
    "size too small, not as described, I want a refund",
    "smell is awful, cheap material, worst purchase",
    "customer service response was bad, never again",
]
res = ar(reviews=reviews, marketplace="amazon", top_n=5)
d = res.data
print("ok:", res.ok, "total:", d["total"], "negative_ratio:", d["negative_ratio"])
print("themes:")
print(json.dumps(d["themes"], ensure_ascii=False, indent=2))
print("sample_quotes:", json.dumps(d["sample_quotes"], ensure_ascii=False))
print("action_items:")
for a in d["action_items"]:
    print("  -", a)

print("\n=== Sample 3: draft_reply three tones ===")
review = "box broken on arrival and size too small, quality cheap, want refund"
for tone in ["professional", "friendly", "concise"]:
    res = dr(review=review, tone=tone, marketplace="amazon", refund_ready=True)
    d = res.data
    print(f"--- tone={tone} theme={d['theme']} apology={d['apology_level']} wc={d['word_count']}")
    print("draft:", d["reply_draft"])
    print("has placeholder:", "{{support_email}}" in d["reply_draft"])
