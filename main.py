from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
from config import token_secret

app = FastAPI()

#weights for confidence score calculation
WEIGHT_SCORE = 1.0
NORMALIZED_SIGNATURE = 2.0
RAW_SIGNATURE = 1.5
CONFIDENCE_THRESHOLD = 0.2

# states
baseline_signature = [0, 0, 0, 0]
items = {} 
removed_items = {}
next_id = 1

#todo: replace with secure token management
TOKEN = token_secret.TOKEN

#models
class SensorUpdate(BaseModel):
    token: str
    signature: list[float]
    name: Optional[str] = None

class RegisterItem(BaseModel):
    token: str
    item_id: int
    signature: list[float]

class AddItem(BaseModel):
    token: str
    name: str

class Item(BaseModel):
    item_id: int
    name: str
    signature: list[float]
    weight: float

class GetItems(BaseModel):
    token: str


#helpers

def compute_delta(data):
    return [data[i] - baseline_signature[i] for i in range(4)]

def compute_weight(delta):
    return sum(delta)

#layer 1: euclidean distance on raw signature, same position return
def euclidean_distance(sig1, sig2):
    return sum((sig1[i] - sig2[i])**2 for i in range(4))**0.5

#layer 2: euclidean distance on normalized signature
def normalized_distance(sig1, sig2):
    norm1 = sum(sig1)
    norm2 = sum(sig2)
    if norm1 == 0 or norm2 == 0:
        return float('inf')
    normalized_sig1 = [sig1[i] / norm1 for i in range(4)]
    normalized_sig2 = [sig2[i] / norm2 for i in range(4)]
    return sum((normalized_sig1[i] - normalized_sig2[i])**2 for i in range(4))**0.5

#layer 3: weight elimination + closest match
#item can only have lost weight, not gained, so we can eliminate any items that have more weight than the returned weight. Then we can find the closest match among the remaining items.
def have_lost_weight(delta):
    return sum(delta) < 0

def closest_match(delta, registry):
    best_id = None
    best_distance = float('inf')
    for id, item in registry.items():
        if not have_lost_weight(delta) and item["weight"] > sum(delta):
            return 0
        distance = sum((delta[i] - item["signature"][i])**2 for i in range(4)) ** 0.5
        if distance < best_distance:
            best_distance = distance
            best_id = id
    return best_id

#confidence score calculation
#combine weight score, normalized signature score, and raw signature score into a single confidence score. The weight score is based on how close the total weight change is to the expected weight change for the item. The normalized signature score is based on how close the normalized sensor signature is to the expected normalized signature for the item. The raw signature score is based on how close the raw sensor signature is to the expected raw signature for the item. The confidence score is a weighted average of these three scores.
def calculate_confidence(delta, item):
    weight_score = max(0, 1 - abs(sum(delta) - item["weight"]) / max(abs(item["weight"]), 1))
    normalized_score = max(0, 1 - normalized_distance(delta, item["signature"]) / 10)
    raw_score = max(0, 1 - euclidean_distance(delta, item["signature"]) / 10)
    confidence = (WEIGHT_SCORE * weight_score + NORMALIZED_SIGNATURE * normalized_score + RAW_SIGNATURE * raw_score) / (WEIGHT_SCORE + NORMALIZED_SIGNATURE + RAW_SIGNATURE)
    return confidence

#add confidence score to array


# compare confidence scores for returned items 


    

#check token
def check_token(token):
    if token != TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")

#endpoints

@app.get("/")
async def root():
    return {"message": "ok", "status": "200"}

@app.post("/update")
def update(data: SensorUpdate):
    check_token(data.token)
    global baseline_signature, next_id

    delta = compute_delta(data.signature)
    weight = compute_weight(delta)
    baseline_signature = data.signature.copy()

    #remove
    if weight < 0:
        match_id = find_match([-d for d in delta], items)
        if match_id:
            removed_items[match_id] = items.pop(match_id)
            return {"event": "removed", "item_id": match_id, "name": removed_items[match_id]["name"]}
        return {"event": "removed", "item_id": None, "name": "unknown"}

    #if just one item removed
    if len(removed_items) == 1:
        match_id = list(removed_items.keys())[0]
        items[match_id] = removed_items.pop(match_id)
        return {"event": "returned", "item_id": match_id, "name": items[match_id]["name"]}
    

    return {"event": "no_change"}

#add new item name to registry
@app.post("/add_item")
def add_item(data: AddItem):
    check_token(data.token)
    global next_id
    global baseline_signature
    item_id = next_id
    next_id += 1
    items[item_id] = {"name": data.name, "signature": baseline_signature.copy(), "weight": 0}
    return {"item_id": item_id, "name": data.name}

#register item with sensor signature and id
@app.post("/register_item")
def register_item(data: RegisterItem):
    check_token(data.token)
    global baseline_signature
    if data.item_id not in items:
        raise HTTPException(status_code=404, detail="Item not found by id")
    item_id = data.item_id
    delta = compute_delta(data.signature)
    weight = compute_weight(delta)
    baseline_signature = data.signature.copy()

    items[item_id]["signature"] = delta
    items[item_id]["weight"] = weight
    return {"item_id": item_id, "name": items[item_id]["name"], "signature": delta, "weight": weight}

#check current state
@app.get("/items")
def get_items(token: str):
    check_token(token)
    return {"items": items, "removed": removed_items, "baseline": baseline_signature}