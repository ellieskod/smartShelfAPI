from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
from config import token_secret

app = FastAPI()

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

#finding the best match for a return when multiple items are removed and returned
def find_match_return(delta, registry, tolerance=500):
    best_id = None
    best_distance = float('inf')
    returned_weight = sum(delta)

    for id, item in registry.items():

        # item can only have lost weight, not gained
        if returned_weight > item["weight"]:
            continue
        distance = sum((delta[i] - item["signature"][i])**2 for i in range(4)) ** 0.5
        if distance < best_distance:
            best_distance = distance
            best_id = id

    if best_distance < tolerance:
        return best_id
    return None

def find_match(delta, registry, tolerance=50):
    best_id = None
    best_distance = float('inf')
    
    #calvulate euclidean distance between delta and each item in registry
    for id, item in registry.items():
        distance = sum((delta[i] - item["signature"][i])**2 for i in range(4)) ** 0.5
        if distance < best_distance:
            best_distance = distance
            best_id = id

    if best_distance < tolerance:
        return best_id
    return None

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

    #return
    if weight > 0:
        #if only one item is removed, assume it's a return
        if len(removed_items) == 1:
            match_id = next(iter(removed_items))
            item = removed_items.pop(match_id)
            item["signature"] = delta
            item["weight"] = weight
            items[match_id] = item
            return {"event": "returned", "item_id": match_id, "name": item["name"], "new_weight": weight}

        match_id = find_match(delta, removed_items)
        if match_id:
            item = removed_items.pop(match_id)
            item["signature"] = delta
            item["weight"] = weight
            items[match_id] = item
            return {"event": "returned", "item_id": match_id, "name": item["name"], "new_weight": weight}

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